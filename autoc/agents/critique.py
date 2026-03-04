"""Critique Agent — 代码级质量评审，替代 PM Review

设计理念 (参考 OpenHands Iterative Refinement):
  独立 Agent 读取实际代码 + 运行测试，产出 4 维量化评分和代码级 issues。
  与旧 PM Review 的本质区别：PM Review 基于文本报告做 pass/fail，
  Critique Agent 基于代码和运行时证据做结构化评审。

4 维评分体系:
  - correctness (25分): 功能是否正确实现、测试是否通过
  - quality (25分): 代码质量、可读性、错误处理
  - completeness (25分): 需求覆盖度、边界情况
  - best_practices (25分): 架构模式、命名规范、安全实践
"""

import json
import logging

from autoc.agents.base import BaseAgent
from autoc.tools.schemas import FILE_TOOLS, SHELL_TOOLS

logger = logging.getLogger("autoc.agent.critique")

# Critique 评审的 4 个维度及权重
CRITIQUE_DIMENSIONS = ("correctness", "quality", "completeness", "best_practices")
MAX_SCORE_PER_DIM = 25
PASS_THRESHOLD = 85


class CritiqueAgent(BaseAgent):
    """代码级质量评审 Agent

    职责:
    1. 读取任务产出的实际代码文件
    2. 运行 verification_steps 和测试命令
    3. 按 4 维度量化评分 (各 25 分，满分 100)
    4. 产出代码级 issues 列表（精确到文件和行号）
    5. 低于阈值时触发 CodeActAgent 修复
    """

    agent_role = "critique"

    progress_nudge_threshold = 0.6
    progress_warn_threshold = 0.85

    _SUBMIT_CRITIQUE_TOOL = {
        "type": "function",
        "function": {
            "name": "submit_critique",
            "description": "提交结构化评审报告。完成所有代码审查和测试后，必须调用此工具提交评审结果。",
            "parameters": {
                "type": "object",
                "properties": {
                    "scores": {
                        "type": "object",
                        "description": "4 维评分，各 0-25 分",
                        "properties": {
                            "correctness": {"type": "integer", "minimum": 0, "maximum": 25},
                            "quality": {"type": "integer", "minimum": 0, "maximum": 25},
                            "completeness": {"type": "integer", "minimum": 0, "maximum": 25},
                            "best_practices": {"type": "integer", "minimum": 0, "maximum": 25},
                        },
                        "required": list(CRITIQUE_DIMENSIONS),
                    },
                    "summary": {"type": "string", "description": "评审总结（中文）"},
                    "issues": {
                        "type": "array",
                        "description": "代码级问题列表",
                        "items": {
                            "type": "object",
                            "properties": {
                                "file_path": {"type": "string"},
                                "line_number": {"type": "integer"},
                                "severity": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
                                "dimension": {"type": "string", "enum": list(CRITIQUE_DIMENSIONS)},
                                "description": {"type": "string"},
                                "suggestion": {"type": "string"},
                            },
                            "required": ["file_path", "severity", "dimension", "description"],
                        },
                    },
                    "passed": {"type": "boolean", "description": "总分 >= 85 为 true"},
                },
                "required": ["scores", "summary", "issues", "passed"],
            },
        },
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._submitted_critique: dict | None = None
        # 评审工作流以读取文件为主（list_files + read_file × N），默认 threshold=5 过低
        self._stuck_detector._empty_output_threshold = 12
        self._registry.register_handler(
            "submit_critique", self._handle_submit_critique,
            category="report", description="提交结构化评审报告",
        )

    def clone(self) -> "CritiqueAgent":
        """覆盖 BaseAgent.clone()，确保自定义 stuck_detector 阈值被继承"""
        cloned = super().clone()
        # 恢复 CritiqueAgent 自定义的 stuck_detector 配置
        cloned._stuck_detector._empty_output_threshold = self._stuck_detector._empty_output_threshold
        cloned._submitted_critique = None
        return cloned

    def _handle_submit_critique(self, args: dict) -> str:
        raw_scores = args.get("scores", {})
        if not isinstance(raw_scores, dict):
            raw_scores = {}
        # 对每个维度做类型强转和范围钳制，防止 LLM 返回字符串或越界值
        scores = {
            d: max(0, min(25, int(float(raw_scores.get(d, 0)))))
            for d in CRITIQUE_DIMENSIONS
        }
        issues = args.get("issues", [])
        if not isinstance(issues, list):
            issues = []
        self._submitted_critique = {
            "scores": scores,
            "summary": str(args.get("summary", "")),
            "issues": issues,
            "passed": bool(args.get("passed", False)),
        }
        total = sum(scores.values())
        logger.info(f"收到 Critique 评审报告: 总分 {total}/100")
        return f"评审报告已提交 (总分 {total}/100)，流程结束。"

    def get_system_prompt(self) -> str:
        from autoc.prompts import PromptEngine

        engine = PromptEngine()
        if engine.has_template("critique"):
            return engine.render("critique", pass_threshold=PASS_THRESHOLD)

        return f"""你是代码评审专家 (Critique Agent)，负责对已完成的任务进行代码级质量评审。
总分 >= {PASS_THRESHOLD} 为通过，任何维度 < 10 则强制不通过。
评审完成后必须调用 submit_critique。"""

    @staticmethod
    def _find_tool(tools: list[dict], name: str) -> dict:
        """按名称查找工具定义，避免硬编码索引"""
        for t in tools:
            fn = t.get("function", {})
            if fn.get("name") == name:
                return t
        raise ValueError(f"工具 '{name}' 未找到，可用: {[t.get('function',{}).get('name') for t in tools]}")

    def get_tools(self) -> list[dict]:
        """Critique Agent 工具: 读文件 + Shell 执行 + 提交评审"""
        tools = [
            self._find_tool(FILE_TOOLS, "read_file"),
            self._find_tool(FILE_TOOLS, "list_files"),
            self._find_tool(FILE_TOOLS, "search_in_files"),
            self._find_tool(SHELL_TOOLS, "execute_command"),
            self._SUBMIT_CRITIQUE_TOOL,
        ]
        return tools

    def review_plan(self, plan_md: str, requirement: str = "") -> dict:
        """评审 PLAN.md 的实现质量 (OpenHands V1.1 模式)

        Args:
            plan_md: PLAN.md 内容（评审标准）
            requirement: 原始用户需求

        Returns:
            评审报告 dict: {scores, summary, issues, passed, total_score}
        """
        self.conversation_history = []
        self._submitted_critique = None
        self._stuck_detector.reset()
        self._log("开始评审 PLAN.md 实现")

        prompt = self._build_plan_review_prompt(plan_md, requirement)

        try:
            self.run(prompt)
        except Exception as e:
            logger.error(f"Critique 评审异常: {e}")
            # 真正的基础设施异常（API/网络/Docker 崩溃），降级允许通过
            return self._build_fallback_report("plan", str(e), is_infra_failure=True)

        if self._submitted_critique is not None:
            report = self._submitted_critique
        else:
            # Agent 未调用 submit_critique，尝试从对话历史文本中解析 JSON
            parsed = self._extract_critique_from_history()
            if parsed is not None:
                logger.info("从对话历史文本中成功解析评审报告")
                report = parsed
            else:
                # Agent 行为异常（未提交也无法解析），按失败处理，不自动通过
                logger.warning("Critique Agent 未提交结构化报告且无法从文本解析")
                report = self._build_fallback_report("plan", "未提交结构化报告", is_infra_failure=False)

        report["total_score"] = sum(report.get("scores", {}).values())
        report["task_id"] = "plan"

        scores = report.get("scores", {})
        any_dim_critical = any(scores.get(d, 0) < 10 for d in CRITIQUE_DIMENSIONS)
        if any_dim_critical:
            report["passed"] = False

        return report

    @staticmethod
    def _parse_critique_from_history(content: str) -> dict | None:
        """从文本中提取 critique JSON（正则无法处理嵌套，改用 raw_decode）"""
        decoder = json.JSONDecoder()
        for i, ch in enumerate(content):
            if ch == '{':
                try:
                    obj, _ = decoder.raw_decode(content, i)
                    if isinstance(obj, dict) and "scores" in obj:
                        scores = obj.get("scores", {})
                        if (isinstance(scores, dict) and
                                any(d in scores for d in CRITIQUE_DIMENSIONS)):
                            return obj
                except json.JSONDecodeError:
                    continue
        return None

    def _extract_critique_from_history(self) -> dict | None:
        """从对话历史的最后几条 assistant 消息中提取 JSON 格式的评审报告。

        当 Agent 已完成分析但未调用 submit_critique 时，尝试从文本输出中恢复结果。
        只提取包含完整 4 维评分的 JSON 块，避免误匹配无关 JSON。
        """
        for msg in reversed(self.conversation_history):
            if msg.get("role") != "assistant":
                continue
            content = str(msg.get("content", ""))
            if not content:
                continue
            data = self._parse_critique_from_history(content)
            if data is None:
                continue
            scores_raw = data.get("scores", {})
            if not isinstance(scores_raw, dict):
                continue
            has_valid_dim = any(d in scores_raw for d in CRITIQUE_DIMENSIONS)
            if not has_valid_dim:
                continue
            scores = {
                d: max(0, min(25, int(float(scores_raw.get(d, 0)))))
                for d in CRITIQUE_DIMENSIONS
            }
            issues = data.get("issues", [])
            if not isinstance(issues, list):
                issues = []
            return {
                "scores": scores,
                "summary": str(data.get("summary", "（从文本解析）")),
                "issues": issues,
                "passed": bool(data.get("passed", False)),
            }
        return None

    def _build_plan_review_prompt(self, plan_md: str, requirement: str = "") -> str:
        parts = [
            "## 评审任务\n"
            "请对照 PLAN.md 评审当前工作区的实现质量。\n"
            "逐个读取代码文件，运行验证命令，然后提交评审报告。",
        ]

        if requirement:
            parts.append(f"## 原始需求\n{requirement[:1000]}")

        parts.append(f"## 实现计划 (PLAN.md)\n{plan_md}")

        parts.append(
            "\n## 执行步骤\n"
            "1. 用 list_files 查看工作区文件结构\n"
            "2. 逐个 read_file 审查关键代码文件\n"
            "3. 运行 PLAN.md 中的验证命令（execute_command）\n"
            "4. 对照需求和计划，按 4 维度打分\n"
            "5. 调用 submit_critique 提交评审报告"
        )

        return "\n\n".join(parts)

    # ==================== 逐任务评审 ====================

    def review_task(
        self,
        task_id: str,
        task_title: str,
        task_description: str,
        task_files: list[str],
        verification_steps: list[str],
        acceptance_criteria: list[str] | None = None,
        requirement: str = "",
        data_models: str = "",
        api_design: str = "",
    ) -> dict:
        """评审单个任务的实现质量

        Returns:
            评审报告 dict: {scores, summary, issues, passed, total_score}
        """
        self.conversation_history = []
        self._submitted_critique = None
        self._stuck_detector.reset()
        self._log(f"开始评审: [{task_id}] {task_title}")

        prompt = self._build_review_prompt(
            task_id, task_title, task_description, task_files,
            verification_steps, acceptance_criteria, requirement,
            data_models, api_design,
        )

        try:
            self.run(prompt)
        except Exception as e:
            logger.error(f"Critique 评审异常: {e}")
            return self._build_fallback_report(task_id, str(e), is_infra_failure=True)

        if self._submitted_critique is not None:
            report = self._submitted_critique
        else:
            parsed = self._extract_critique_from_history()
            if parsed is not None:
                logger.info(f"从对话历史文本中成功解析评审报告 [{task_id}]")
                report = parsed
            else:
                logger.warning(f"Critique Agent 未提交结构化报告且无法从文本解析 [{task_id}]")
                report = self._build_fallback_report(task_id, "未提交结构化报告", is_infra_failure=False)

        report["total_score"] = sum(report.get("scores", {}).values())
        report["task_id"] = task_id

        # 强制不通过规则：任何维度 < 10
        scores = report.get("scores", {})
        any_dim_critical = any(scores.get(d, 0) < 10 for d in CRITIQUE_DIMENSIONS)
        if any_dim_critical:
            report["passed"] = False

        return report

    def review_project(
        self,
        tasks: list[dict],
        requirement: str = "",
        data_models: str = "",
        api_design: str = "",
    ) -> dict:
        """评审整个项目（多任务聚合评审）

        Args:
            tasks: [{"id", "title", "description", "files", "verification_steps", "acceptance_criteria"}]

        Returns:
            项目级评审报告
        """
        task_reports = []
        for task in tasks:
            report = self.review_task(
                task_id=task["id"],
                task_title=task["title"],
                task_description=task.get("description", ""),
                task_files=task.get("files", []),
                verification_steps=task.get("verification_steps", []),
                acceptance_criteria=task.get("acceptance_criteria"),
                requirement=requirement,
                data_models=data_models,
                api_design=api_design,
            )
            task_reports.append(report)

        all_passed = bool(task_reports) and all(r.get("passed", False) for r in task_reports)
        all_issues = []
        for r in task_reports:
            all_issues.extend(r.get("issues", []))

        avg_scores = {}
        for dim in CRITIQUE_DIMENSIONS:
            dim_scores = [r.get("scores", {}).get(dim, 0) for r in task_reports]
            avg_scores[dim] = round(sum(dim_scores) / len(dim_scores)) if dim_scores else 0

        total_score = sum(avg_scores.values())

        return {
            "passed": all_passed,
            "total_score": total_score,
            "scores": avg_scores,
            "summary": f"项目评审: {len(task_reports)} 个任务, "
                       f"总分 {total_score}/100, "
                       f"{'通过' if all_passed else '未通过'}",
            "issues": all_issues,
            "task_reports": task_reports,
        }

    def _build_review_prompt(
        self, task_id, task_title, task_description, task_files,
        verification_steps, acceptance_criteria, requirement,
        data_models, api_design,
    ) -> str:
        parts = [
            f"## 评审任务\n- ID: {task_id}\n- 标题: {task_title}\n- 描述:\n{task_description}",
        ]

        if task_files:
            file_list = "\n".join(f"  - `{f}`" for f in task_files)
            parts.append(f"## 产出文件（逐个 read_file 审查）\n{file_list}")

        if verification_steps:
            steps = "\n".join(f"  {i}. `{s}`" for i, s in enumerate(verification_steps, 1))
            parts.append(f"## 验证步骤（逐条 execute_command 运行）\n{steps}")

        if acceptance_criteria:
            criteria = "\n".join(f"  - {c}" for c in acceptance_criteria)
            parts.append(f"## 验收标准\n{criteria}")

        if requirement:
            parts.append(f"## 原始需求\n{requirement[:500]}")

        if data_models:
            parts.append(f"## 数据模型规约\n```\n{data_models[:500]}\n```")

        if api_design:
            parts.append(f"## API 契约\n```\n{api_design[:500]}\n```")

        parts.append(
            "\n## 执行步骤\n"
            "1. 逐个 read_file 审查产出的代码文件\n"
            "2. 逐条 execute_command 运行验证步骤\n"
            "3. 对照需求和验收标准，检查完整性\n"
            "4. 按 4 维度打分，记录 issues\n"
            "5. 调用 submit_critique 提交评审报告"
        )

        return "\n\n".join(parts)

    @staticmethod
    def _build_fallback_report(task_id: str, error: str, *, is_infra_failure: bool = True) -> dict:
        """构建降级报告。

        Args:
            is_infra_failure: True 表示真正的基础设施异常（网络/Docker/API 崩溃），
                              此时可降级自动通过（避免因基础设施问题误判）。
                              False 表示 Agent 行为异常（未提交报告等），
                              此时应按实际失败处理，不触发自动通过。
        """
        return {
            "scores": {d: 0 for d in CRITIQUE_DIMENSIONS},
            "summary": f"评审失败: {error}",
            "issues": [],
            "passed": False,
            "total_score": 0,
            "task_id": task_id,
            "infrastructure_failure": is_infra_failure,
        }
