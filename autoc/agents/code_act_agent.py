"""CodeActAgent — 全栈实现者，完成 编码→验证→修复 完整闭环

设计理念:
  一个 Agent 完成 "理解规约 → 写代码 → 自验证 → 修复" 的完整闭环。
  上下文在整个任务周期内保持连续，具备持续的规划-执行-反馈能力。
  通过 clone() 支持并行执行多个独立任务（Sub Agent 模式）。
"""

import json
import logging
import re
import uuid

from rich.console import Console

from autoc.agents.base import BaseAgent
from autoc.core.project.memory import TaskStatus, Task, TestResult, BugReport
from autoc.tools.schemas import (
    FILE_TOOLS, SHELL_TOOLS, SEND_INPUT_TOOL,
    THINK_TOOL, SUBMIT_REPORT_TOOL, ASK_HELPER_TOOL,
)

console = Console()
logger = logging.getLogger("autoc.agent.code_act")


class CodeActAgent(BaseAgent):
    """全栈实现者 (CodeActAgent)

    职责:
    1. 消费规划阶段规约，按照 data_models / api_contracts / file 清单实现代码
    2. 实现完成后，自行执行 verification_steps 验证
    3. 验证失败则立即修复并重新验证（同一会话，无上下文丢失）
    4. 全部通过后输出结构化验收报告
    5. 支持 clone() 创建并行实例（Sub Agent 模式）
    """

    agent_role = "main"

    progress_nudge_threshold = 0.55
    progress_warn_threshold = 0.8

    # 工具 schema 由 Pydantic 模型自动生成（autoc/tools/schemas.py）
    _THINK_TOOL = THINK_TOOL
    _SUBMIT_REPORT_TOOL = SUBMIT_REPORT_TOOL

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._submitted_report: dict | None = None
        # 恢复/重试场景下 Agent 会先读取多个文件了解现状，默认 threshold=5 过低
        # 对标 CritiqueAgent(threshold=12)，CodeActAgent 设为 8 以兼顾读文件阶段和停滞检测
        self._stuck_detector._empty_output_threshold = 8
        self._registry.register_handler(
            "submit_test_report", self._handle_submit_report,
            category="report", description="提交结构化验收报告",
        )

    def clone(self) -> "CodeActAgent":
        """覆盖 BaseAgent.clone()，确保子类 mutable 状态被隔离"""
        cloned = super().clone()
        cloned._submitted_report = None
        cloned._stuck_detector._empty_output_threshold = self._stuck_detector._empty_output_threshold
        cloned._submit_hint_injected = False
        if hasattr(cloned, '_plan_condensed'):
            cloned._plan_condensed = False
        if hasattr(cloned, '_output_drift_warning'):
            cloned._output_drift_warning = ""
        cloned._changed_files = set()
        return cloned

    def _handle_submit_report(self, args: dict) -> str:
        """接收验收报告。参数已经过 Pydantic validate_tool_args 处理，
        此处仅做类型兜底（防 validation fallback 传入原始 args）。
        """
        def _safe_list(v):
            if isinstance(v, list):
                return v
            return []

        def _safe_int(v, default=5):
            try:
                val = int(v)
            except (TypeError, ValueError):
                return default
            return max(1, min(val, 10))

        self._submitted_report = {
            "pass": bool(args.get("pass", False)),
            "summary": str(args.get("summary", "")),
            "quality_score": _safe_int(args.get("quality_score"), 5),
            "bugs": _safe_list(args.get("bugs")),
            "task_verification": _safe_list(args.get("task_verification")),
            "test_results": _safe_list(args.get("test_results")),
            "test_files_created": _safe_list(args.get("test_files_created")),
        }
        logger.info("收到结构化验收报告（via submit_test_report tool）")
        return "验收报告已提交，流程结束。"

    def _get_missing_tools_hint(self) -> str:
        missing = self.shell.missing_tools if self.shell else []
        hint = "\n## 环境适配\n"
        hint += (
            "- 遇到 `command not found` 时，**自行安装**：`apt-get update && apt-get install -y <pkg>`\n"
            "- 遇到 Python 包缺失时，直接 `pip install <pkg>`\n"
            "- 遇到 Node.js 包缺失时，直接 `npm install <pkg>`\n"
        )
        if not missing:
            return hint
        alternatives = {
            "curl": "- **curl 不可用**：运行 `apt-get update && apt-get install -y curl`，或改用 `python -c \"import urllib.request; ...\"`",
            "git": "- **git 不可用**：运行 `apt-get update && apt-get install -y git`（若只读不需要 git 则跳过）",
        }
        lines = [alternatives.get(t, f"- **{t} 不可用**：尝试 `apt-get install -y {t}`") for t in missing]
        return hint + "\n".join(lines) + "\n"

    def get_system_prompt(self) -> str:
        """完整 system prompt — Jinja2 模板渲染，支持条件变量和 few-shot 示例。

        保持 ~500-600 tokens 以确保超过 GLM/OpenAI 的缓存触发门槛（推测 ≥1024 tokens
        含 tool schemas），同时缓存命中后按 1/5 价格计费，实际成本约 100-120 tokens/轮。
        """
        from autoc.core.infra.cn_mirror import get_agent_mirror_instructions
        from autoc.prompts import PromptEngine

        engine = PromptEngine()
        if engine.has_template("code_act_agent"):
            return engine.render(
                "code_act_agent",
                mirror_section=get_agent_mirror_instructions(),
                missing_tools_hint=self._get_missing_tools_hint(),
            )
        return self._fallback_system_prompt()

    def _fallback_system_prompt(self) -> str:
        """硬编码降级（模板文件不存在时使用）"""
        from autoc.core.infra.cn_mirror import get_agent_mirror_instructions
        mirror_section = get_agent_mirror_instructions()
        missing_tools_hint = self._get_missing_tools_hint()

        return f"""你是全栈实现者 (CodeActAgent)，独立完成 编码→验证→修复 闭环。

## 工作流程
1. 阅读规约中的 data_models、文件清单、验证步骤
2. 按 PM 文件清单逐个 write_file，路径命名完全一致
3. data_models/api_design 是蓝图，照抄实现，不改字段名/类型
4. 如需第三方库，pip install 并更新 requirements.txt
5. 写完后逐条跑 verification_steps，失败立即修复再重试
6. 全部通过后调 submit_test_report 提交验收报告
7. 不加 PM 未要求的功能/文件
{missing_tools_hint}
## 硬约束
- 所有路径只用相对路径，绝对禁止绝对路径
- 环境已隔离，直接 pip install，不用 venv
- 优先创建文件，不花迭代去探索
- 阻塞时标 [BLOCKED] + 原因 + 已尝试方案
{mirror_section}"""

    # submit_test_report 注入时机：在总迭代数的后 35% 才注入（节省前期 schema 传输开销）
    # 比率设计：max=20 → 第 13 轮注入；max=10 → 第 7 轮注入；min 保留 3 轮可见窗口
    _SUBMIT_REPORT_LATE_RATIO = 0.35

    def get_tools(self) -> list[dict]:
        """CodeActAgent 核心工具: 文件操作 + Shell + 验收报告 + Helper 咨询

        Git / CodeQuality 工具不暴露给 CodeActAgent（由 Orchestrator 统一调度），
        减少每次 LLM 调用的 tool schema 开销 (~200 tokens/call)。
        注意：submit_test_report 通过 _get_iteration_tools 延迟注入（前几轮省 schema 开销）。
        """
        tools = FILE_TOOLS + SHELL_TOOLS + [THINK_TOOL, SUBMIT_REPORT_TOOL]
        if self.shell and self.shell.supports_interactive:
            tools.append(SEND_INPUT_TOOL)
        if self._helper_llm:
            tools.append(ASK_HELPER_TOOL)
        return tools

    def _get_iteration_tools(self, iteration: int, base_tools: list[dict]) -> list[dict]:
        """前期隐藏 submit_test_report，后 35% 轮次才注入，减少每轮 Schema 传输开销

        用 _initial_max_iterations（run 开始时固定）而非动态 max_iterations 计算阈值，
        避免 SAIC 自动延伸时阈值漂移导致工具在关键阶段忽现忽消失。
        阈值单调递增：一旦工具出现，后续轮次保证持续可见。
        比率设计：max=20 → 第 13 轮注入；max=10 → 第 7 轮注入（最少保留 3 轮窗口）。
        """
        initial_max = getattr(self, "_initial_max_iterations", self.max_iterations)
        earliest_iter = max(1, int(initial_max * (1 - self._SUBMIT_REPORT_LATE_RATIO)))
        if iteration < earliest_iter:
            return [
                t for t in base_tools
                if t.get("function", {}).get("name") != "submit_test_report"
            ]
        return base_tools

    def _get_submit_hint(self, iteration: int) -> str:
        """最后 3 轮若仍未提交报告，注入一次性兜底提示（覆盖 BaseAgent 默认空实现）

        使用 self.max_iterations（动态值）而非 _initial_max_iterations，
        确保 SAIC 延伸后的窗口判断准确；_submit_hint_injected 标志保证只注入一次，
        避免连续轮次重复追加相同消息造成对话膨胀。
        """
        if getattr(self, "_submit_hint_injected", False):
            return ""
        if iteration >= self.max_iterations - 3 and self._submitted_report is None:
            self._submit_hint_injected = True
            return "⚠️ 即将到达迭代上限，请确认所有验证通过后立即调用 **submit_test_report** 提交验收报告。"
        return ""

    # ==================== 核心入口: PLAN.md 驱动实现 ====================

    def execute_plan(self, plan_md: str, feedback: str | None = None,
                     preview_url: str | None = None) -> dict:
        """基于 PLAN.md 自组织实现全部工作 (OpenHands V1.1 模式)

        Args:
            plan_md: PLAN.md 内容
            feedback: CritiqueAgent 上轮反馈（修复轮次时非空）
            preview_url: 已部署应用的 URL（Web 项目，可选）

        Returns:
            验收报告 dict

        会话管理（对齐 OpenHands conversation 持续累积）：
        - Round 1 (feedback=None): 全新会话，注入 plan_md
        - Round 2+ (feedback!=None): 保留上轮 conversation，追加反馈继续执行
        """
        # 空字符串视为无反馈（等同 None），避免误触发 continuation 模式
        is_continuation = bool(feedback) and len(self.conversation_history) > 0
        self._submitted_report = None
        self._submit_hint_injected = False
        # 清理上一轮残留的偏离警告，避免跨轮次注入本轮报告
        if hasattr(self, '_output_drift_warning'):
            del self._output_drift_warning
        # continuation 轮次保留已有 _plan_condensed 状态，避免重复触发摘要化（缺陷 #1）
        if not is_continuation:
            self._plan_condensed = False

        if not is_continuation:
            self.conversation_history = []
            self._log("开始基于 PLAN.md 实现项目")
        else:
            self._log("收到评审反馈，在已有上下文上继续修复")

        if not self._registry.has("submit_test_report"):
            self._registry.register_handler(
                "submit_test_report", self._handle_submit_report,
                category="report", description="提交结构化验收报告",
            )

        if is_continuation:
            prompt = self._build_feedback_continuation_prompt(feedback, preview_url)
        else:
            prompt = self._build_plan_execution_prompt(plan_md, feedback=None,
                                                       preview_url=preview_url)

        try:
            output = self.run(prompt, continuation=is_continuation)
        except Exception as e:
            logger.error(f"执行异常: {e}")
            return self._build_plan_error_report(str(e))

        if not self._changed_files:
            logger.warning("未产出任何文件")
            return self._build_plan_error_report("未产出任何文件，任务未完成")

        # 产出一致性检查：检测实际产出文件是否严重偏离 PLAN.md 中的文件清单
        if not is_continuation:
            drift_warning = self._check_output_drift(plan_md)
            if drift_warning:
                logger.warning(f"产出一致性警告: {drift_warning}")
                # 将偏离信息记录到报告中，但不阻断流程（由 Critique Agent 做最终裁决）
                self._output_drift_warning = drift_warning

        if self._submitted_report is not None:
            logger.info("使用 submit_test_report 提交的结构化报告")
            report = self._submitted_report
            if hasattr(self, '_output_drift_warning'):
                report.setdefault("warnings", []).append(self._output_drift_warning)
                del self._output_drift_warning
            return report

        return self._parse_plan_report_from_output(output)

    # ==================== Plan Prompt 摘要化 ====================

    # 迭代 2 后激活（早于滑动窗口 trigger=12，避免 plan prompt 被压缩器先行吞掉）
    _PLAN_CONDENSE_AFTER_ITER = 2
    _PLAN_SECTION_MARKER = "## 实现计划"

    def _pre_condense_hook(self):
        """迭代 2 后将完整 Plan Prompt 摘要化，节省 ~600 tokens/轮。

        只在 execute_plan() 初始化的会话中生效（_plan_condensed 必须存在），
        防止非 plan 模式调用时每轮做无效遍历（缺陷 #6）。
        """
        # _plan_condensed 由 execute_plan() 显式初始化；未初始化说明非 plan 模式，直接跳过
        if not hasattr(self, '_plan_condensed'):
            return
        if self._iteration_count <= self._PLAN_CONDENSE_AFTER_ITER:
            return
        if self._plan_condensed:
            return

        for msg in self.conversation_history:
            if (msg.get("role") == "user"
                    and self._PLAN_SECTION_MARKER in str(msg.get("content", ""))):
                original_len = len(msg["content"])
                condensed = self._condense_plan_prompt(msg["content"])
                # 仅在确实缩短时才替换，避免对已摘要化内容重复操作（缺陷 #1 兜底）
                if len(condensed) < original_len:
                    msg["content"] = condensed
                    logger.info(
                        f"[{self.name}] Plan Prompt 摘要化: "
                        f"{original_len} → {len(condensed)} 字符 "
                        f"(迭代 {self._iteration_count})"
                    )
                self._plan_condensed = True
                break

    @staticmethod
    def _condense_plan_prompt(prompt: str) -> str:
        """将完整 plan execution prompt 摘要化：保留计划骨架，去除静态指引"""
        marker = "## 实现计划"
        idx = prompt.find(marker)
        if idx < 0:
            return prompt

        plan_start = idx
        # 分离 plan section 和后续 section
        rest_match = re.search(r'\n\n## (?!实现计划)', prompt[plan_start + len(marker):])
        if rest_match:
            split_pos = plan_start + len(marker) + rest_match.start()
            plan_text = prompt[plan_start:split_pos]
            rest_text = prompt[split_pos:]
        else:
            plan_text = prompt[plan_start:]
            rest_text = ""

        # 按行截断：取 500 字符内最后一个换行处，避免切断 Markdown 行中间（缺陷 #3）
        if len(plan_text) > 500:
            cut = plan_text.rfind('\n', 0, 500)
            if cut < 100:  # 找不到合适换行点则退回字符截断
                cut = 500
            plan_text = plan_text[:cut].rstrip() + "\n\n...(计划详情已省略，参见 PLAN.md)"

        # 从后续 section 只保留动态内容，去除静态指引（环境信息/执行要求）
        kept_sections = []
        if rest_text:
            for section in re.split(r'\n\n(?=## )', rest_text.lstrip()):
                if section.startswith("## 已有文件") or section.startswith("## 应用已部署"):
                    kept_sections.append(section)

        parts = [plan_text] + kept_sections
        return "\n\n".join(parts)

    def _build_feedback_continuation_prompt(self, feedback: str,
                                            preview_url: str | None = None) -> str:
        """构造评审反馈续接 prompt（不重复注入 plan_md）"""
        parts = [feedback]
        if preview_url:
            parts.append(f"\n应用地址: {preview_url}")
        parts.append(
            "\n请根据以上评审反馈修复代码，完成后调用 **submit_test_report** 提交验收报告。"
        )
        return "\n\n".join(parts)

    def _build_plan_execution_prompt(self, plan_md: str,
                                     feedback: str | None = None,
                                     preview_url: str | None = None) -> str:
        parts = []

        # 次需求场景：注入主需求上下文，让 Agent 理解项目全貌
        if (self.memory.plan_source == "secondary"
                and self.memory.requirement
                and self.memory.requirement not in plan_md):
            parts.append(
                f"## 项目核心目标（主需求）\n\n{self.memory.requirement}\n\n"
                f"> 以下实现计划是针对追加功能的增量开发，"
                f"实现时须确保不破坏主需求已有功能。"
            )

        parts.append(f"## 实现计划\n\n{plan_md}")

        if self.memory.files:
            existing = [f"- `{f.path}`" for f in self.memory.files.values()]
            if existing:
                parts.append(f"## 已有文件\n" + "\n".join(existing[:15]))

        if preview_url:
            parts.append(
                f"## 应用已部署\n"
                f"应用在 Docker 容器中运行: **{preview_url}**\n"
                f"验证时可直接 curl 该地址。"
            )

        from autoc.core.infra.cn_mirror import get_mirror_env_hint
        parts.append(
            "\n## 环境信息\n"
            "- 工作目录: `.`，所有路径使用相对路径\n"
            "- Python 环境已就绪，可直接 pip install\n"
            "- 不要手动创建或激活 venv"
            + get_mirror_env_hint()
        )

        parts.append(
            "\n## 执行要求\n"
            "1. **严格按照计划实现**：新建文件用 write_file；修改已有文件用 edit_file 精确替换\n"
            "2. 安装必要依赖（pip install + 更新 requirements.txt）\n"
            "3. **执行计划中的验证方案**（execute_command），确认功能正确\n"
            "4. 如果验证失败，**立即修复代码并重新验证**\n"
            "5. 全部完成后，调用 **submit_test_report** 提交验收报告"
        )

        return "\n\n".join(parts)

    @staticmethod
    def _build_plan_error_report(error: str) -> dict:
        return {
            "pass": False,
            "summary": error,
            "quality_score": 0,
            "bugs": [],
            "task_verification": [],
            "test_results": [],
            "test_files_created": [],
        }

    def _check_output_drift(self, plan_md: str) -> str | None:
        """检测实际产出文件是否严重偏离 PLAN.md 中的文件清单。

        通过提取 PLAN.md 中列出的关键文件名后缀（.vue/.py/.ts 等）
        与实际 _changed_files 对比，若技术栈完全不匹配则告警。

        Returns:
            偏离警告字符串，或 None（无偏离）
        """
        if not plan_md or not self._changed_files:
            return None

        # 从 PLAN.md 中提取文件扩展名集合
        plan_exts: set[str] = set()
        for line in plan_md.splitlines():
            # 匹配如 `backend/app/main.py`、`frontend/src/App.vue` 等
            matches = re.findall(r'`[^`]+\.([a-zA-Z]+)`', line)
            plan_exts.update(m.lower() for m in matches)

        # 检测技术栈关键标志
        plan_has_vue = "vue" in plan_exts
        plan_has_fastapi = any(
            kw in plan_md.lower() for kw in ["fastapi", "uvicorn", "from fastapi"]
        )

        actual_files = list(self._changed_files)
        actual_exts = {f.rsplit(".", 1)[-1].lower() for f in actual_files if "." in f}
        actual_names = [f.split("/")[-1].lower() for f in actual_files]

        warnings = []

        # 检测前端技术栈偏离：PLAN 要 Vue 但实际写了 React
        if plan_has_vue:
            actual_has_react = any(n in actual_names for n in ["app.tsx", "app.jsx", "react"])
            if actual_has_react or ("tsx" in actual_exts and "vue" not in actual_exts):
                warnings.append(
                    "技术栈偏离：PLAN.md 要求 Vue 3，实际产出 React (*.tsx) 文件"
                )

        # 检测后端技术栈偏离：PLAN 要 FastAPI 但实际写了 Flask
        if plan_has_fastapi and self._changed_files:
            flask_files = [f for f in actual_files if "requirements" in f]
            for req_file in flask_files:
                try:
                    content = self.file_ops.read_file(req_file) if self.file_ops else ""
                    if "flask" in content.lower() and "fastapi" not in content.lower():
                        warnings.append(
                            f"技术栈偏离：PLAN.md 要求 FastAPI，{req_file} 中检测到 Flask"
                        )
                except Exception:
                    pass

        return "; ".join(warnings) if warnings else None

    def _parse_plan_report_from_output(self, output: str) -> dict:
        """从 LLM 输出中解析验收报告（兜底）"""
        data = self._validate_json_output(output)
        if data is not None and "pass" in data:
            return data

        has_pass = output and any(
            w in output.lower()
            for w in ["所有测试通过", "all tests passed", '"pass": true', '"pass":true',
                      "验证通过", "实现完成"]
        )
        return {
            "pass": has_pass,
            "summary": f"[自动推断] {'实现完成' if has_pass else '实现可能未完成'}",
            "quality_score": 7 if has_pass else 4,
            "bugs": [],
            "task_verification": [],
            "test_results": [],
            "test_files_created": [],
        }

    # ==================== 逐任务实现 ====================

    def implement_and_verify(self, task: Task, preview_url: str | None = None) -> dict:
        """实现任务并自行验证 — 一个连续会话完成 Dev + Test + Fix

        Args:
            task: PM 定义的任务
            preview_url: 已部署应用的 URL（Web 项目，可选）

        Returns:
            验收报告 dict
        """
        # 对话历史持续累积，由 Condenser 自动管理长度
        self._submitted_report = None
        self._submit_hint_injected = False
        self.memory.update_task(task.id, status=TaskStatus.IN_PROGRESS, assignee=self.name)
        self._log(f"开始实现并验证: [{task.id}] {task.title}")

        if not self._registry.has("submit_test_report"):
            self._registry.register_handler(
                "submit_test_report", self._handle_submit_report,
                category="report", description="提交结构化验收报告",
            )

        prompt = self._build_implement_and_verify_prompt(task, preview_url)

        try:
            output = self.run(prompt)
        except Exception as e:
            logger.error(f"任务 {task.id} 执行异常: {e}")
            return self._build_error_report(task, str(e))

        # 检查阻塞标记
        if output and ("[BLOCKED]" in output or "[阻塞]" in output):
            self.memory.update_task(
                task.id, status=TaskStatus.BLOCKED,
                block_reason=output[:500],
                block_attempts=task.block_attempts + 1,
            )
            return self._build_error_report(task, f"任务阻塞: {output[:300]}")

        # 产出自检: 没有创建或修改任何文件
        if not self._changed_files:
            logger.warning(f"任务 {task.id} 未产出任何文件")
            self.memory.update_task(task.id, status=TaskStatus.FAILED,
                                    error="未产出任何文件")
            return self._build_error_report(task, "未产出任何文件，任务未完成")

        # 优先使用工具提交的结构化报告
        if self._submitted_report is not None:
            report = self._submitted_report
            logger.info("使用 submit_test_report 提交的结构化报告")
        else:
            report = self._parse_report_from_output(output, task)

        self._process_report(report, task)
        return report

    def _build_implement_and_verify_prompt(self, task: Task,
                                           preview_url: str | None = None) -> str:
        parts = [
            f"## 当前任务\n- ID: {task.id}\n- 标题: {task.title}\n- 描述:\n{task.description}",
        ]

        if task.files:
            file_list = "\n".join(f"  - `{f}`" for f in task.files)
            parts.append(
                f"## 必须创建的文件（PM 契约）\n{file_list}\n"
                "**你必须创建以上每个文件，路径和命名必须完全一致。**"
            )

        if self.memory.project_plan:
            plan = self.memory.project_plan
            if plan.data_models and len(plan.data_models.strip()) > 10:
                parts.append(
                    f"## 数据模型规约（PM 定义，必须照抄实现）\n"
                    f"```\n{plan.data_models}\n```"
                )
            if plan.api_design and len(plan.api_design.strip()) > 10:
                parts.append(
                    f"## API 契约（PM 定义，必须实现）\n"
                    f"```\n{plan.api_design}\n```"
                )

        if task.verification_steps:
            steps = "\n".join(f"  {i}. `{step}`" for i, step in enumerate(task.verification_steps, 1))
            parts.append(
                f"## 验证步骤（写完代码后必须逐条执行）\n{steps}\n"
                "**写完所有文件后，用 execute_command 逐条运行以上命令验证。\n"
                "如果某条验证失败，立即修复代码并重新验证。**"
            )

        if task.dependencies:
            parts.append(f"## 依赖任务: {', '.join(task.dependencies)}")
            for dep_id in task.dependencies:
                dep_task = self.memory.tasks.get(dep_id)
                if dep_task and dep_task.result:
                    parts.append(f"  - {dep_id} 结果: {dep_task.result[:200]}")

        if self.memory.files:
            existing = [f"- `{f.path}`" for f in self.memory.files.values()]
            if existing:
                parts.append(f"## 已有文件\n" + "\n".join(existing[:15]))

        if preview_url:
            parts.append(
                f"## 应用已部署\n"
                f"应用在 Docker 容器中运行: **{preview_url}**\n"
                f"验证时可直接 curl 该地址。"
            )

        from autoc.core.infra.cn_mirror import get_mirror_env_hint
        parts.append(
            "\n## 环境信息\n"
            "- 工作目录: `.`，所有路径使用相对路径\n"
            "- Python 环境已就绪，可直接 pip install\n"
            "- 不要手动创建或激活 venv"
            + get_mirror_env_hint()
        )

        parts.append(
            "\n## 执行步骤\n"
            "1. 按文件清单逐个创建文件（write_file），代码写完整\n"
            "2. 安装必要依赖（pip install + 更新 requirements.txt）\n"
            "3. **逐条执行验证步骤**（execute_command），全部通过才算完成\n"
            "4. 如果验证失败，**立即修复代码并重新验证**\n"
            "5. 全部通过后，调用 **submit_test_report** 提交验收报告"
        )

        return "\n\n".join(parts)

    # ==================== Bug 修复 ====================

    FIX_STRATEGIES = [
        "",
        "提示：之前的修改未解决问题。你可以考虑更大范围的修改（如重构相关函数），但请根据实际错误信息自行判断最佳方案。",
        "提示：多次修复未成功。重写可能比修补更高效，但这不是强制要求——请根据错误根因选择最合适的方式。",
    ]

    def fix_bugs(self, bugs: list, reflection: str = "",
                 failure_context: str = "",
                 on_progress=None) -> int:
        """修复 Bug"""
        if not bugs:
            return 0

        fixed_count = 0
        groups = self._group_related_bugs(bugs)
        total = len(bugs)
        current_idx = 0
        self._log(f"开始修复 {total} 个 Bug（{len(groups)} 组）...")

        for group in groups:
            for bug in group:
                current_idx += 1
                attempt = getattr(bug, "fix_attempts", 0)
                strategy_idx = min(attempt, len(self.FIX_STRATEGIES) - 1)
                strategy = self.FIX_STRATEGIES[strategy_idx]

                if on_progress:
                    on_progress(bug, "fixing", current_idx, total)

                prompt = self._build_fix_prompt(bug, strategy, reflection, failure_context)
                try:
                    self.run(prompt)
                    self.memory.update_bug(bug.id, status="pending_verification", fixed_by=self.name)
                    bug.fix_attempts = attempt + 1
                    fixed_count += 1
                    if on_progress:
                        on_progress(bug, "fixed", current_idx, total)
                except Exception as e:
                    logger.error(f"修复 Bug {bug.id} 失败: {e}")
                    self.memory.update_bug(bug.id, status="open")
                    bug.fix_attempts = attempt + 1
                    if on_progress:
                        on_progress(bug, "failed", current_idx, total)

        return fixed_count

    @staticmethod
    def _group_related_bugs(bugs: list) -> list[list]:
        from collections import defaultdict
        groups_map: defaultdict[str, list] = defaultdict(list)
        no_file = []
        for bug in bugs:
            fp = getattr(bug, "file_path", "") or ""
            if fp:
                groups_map[fp].append(bug)
            else:
                no_file.append(bug)
        groups = list(groups_map.values())
        if no_file:
            groups.append(no_file)
        return groups

    def _build_fix_prompt(self, bug, strategy: str = "",
                          reflection: str = "", failure_context: str = "") -> str:
        prompt = f"""## Bug 修复任务

### Bug 信息
- ID: {bug.id}
- 标题: {bug.title}
- 严重程度: {bug.severity}
- 描述: {bug.description}
"""
        if bug.file_path:
            prompt += f"- 文件: {bug.file_path}\n"
        if bug.line_number:
            prompt += f"- 行号: {bug.line_number}\n"
        if getattr(bug, "root_cause", ""):
            prompt += f"- 根因分析: {bug.root_cause}\n"
        if bug.suggested_fix:
            prompt += f"- 建议修复方案: {bug.suggested_fix}\n"

        attempt = getattr(bug, "fix_attempts", 0)
        if attempt > 0:
            prompt += f"\n### 这是第 {attempt + 1} 次修复尝试\n"
        if strategy:
            prompt += f"\n### 修复策略参考\n{strategy}\n"
        if reflection:
            prompt += f"\n### 反思分析\n{reflection}\n"
        if failure_context:
            prompt += f"\n### 失败模式诊断\n{failure_context}\n"

        prompt += """
### 修复流程
1. 读取相关文件，理解代码上下文
2. 复现问题，观察具体错误输出
3. 基于运行时证据实施修复
4. 修复后立即运行相关验证确认问题已解决"""
        return prompt

    # ==================== 报告处理 ====================

    def _process_report(self, report: dict, task: Task):
        """处理验收报告: 记录测试结果、Bug、更新任务状态"""
        for tr in report.get("test_results", []):
            self.memory.add_test_result(TestResult(
                test_name=tr.get("test_name") or "未命名测试",
                passed=bool(tr.get("passed", False)),
                output=tr.get("output") or "",
                error=tr.get("error") or "",
                file_path=tr.get("file_path") or "",
            ))

        for bug_data in report.get("bugs", []):
            if not isinstance(bug_data, dict):
                continue
            bug_title = bug_data.get("title") or ""
            bug_desc = bug_data.get("description") or ""
            if not bug_title and not bug_desc:
                continue
            bug = BugReport(
                id=f"bug-{uuid.uuid4().hex[:8]}",
                title=bug_title or f"Bug in {bug_data.get('file_path', 'unknown')}",
                description=bug_desc,
                severity=bug_data.get("severity") or "medium",
                file_path=bug_data.get("file_path") or "",
                line_number=bug_data.get("line_number") or 0,
                suggested_fix=bug_data.get("suggested_fix") or "",
                root_cause=bug_data.get("root_cause") or "",
                fix_strategy=bug_data.get("fix_strategy") or "",
                affected_functions=bug_data.get("affected_functions") or [],
                reported_by=self.name,
            )
            self.memory.add_bug_report(bug)

        for tv in report.get("task_verification", []):
            task_id = tv.get("task_id", "")
            passes = tv.get("passes", False)
            details = tv.get("verification_details", "")
            if task_id and task_id in self.memory.tasks:
                self.memory.update_task(task_id, passes=passes)
                if self.progress_tracker:
                    self.progress_tracker.update_task_passes(task_id, passes, details)

        passed = report.get("pass", False)
        quality_score = report.get("quality_score", 0)
        status = TaskStatus.COMPLETED if passed else TaskStatus.FAILED
        self.memory.update_task(task.id, status=status, result=report.get("summary", "")[:500])

        self._log(
            f"{'验证通过' if passed else '验证未通过'} [{task.id}]\n"
            f"- 质量评分: {quality_score}/10\n"
            f"- Bug: {len(report.get('bugs', []))}\n"
            f"- 总结: {report.get('summary', 'N/A')}"
        )

    def _parse_report_from_output(self, output: str, task: Task) -> dict:
        """从 LLM 输出中解析验收报告（兜底逻辑）"""
        data = self._validate_json_output(output)
        if data is not None:
            if "pass" not in data:
                bugs = data.get("bugs", [])
                has_blocking = any(
                    b.get("severity") in ("critical", "high") for b in bugs
                )
                data["pass"] = not has_blocking
            return data

        # 尝试提取 JSON
        json_str = output.strip()
        if json_str.startswith("```"):
            lines = json_str.split("\n")
            start, end = 0, len(lines)
            for i, line in enumerate(lines):
                if line.strip().startswith("{"):
                    start = i
                    break
            for i in range(len(lines) - 1, -1, -1):
                if lines[i].strip().startswith("}"):
                    end = i + 1
                    break
            json_str = "\n".join(lines[start:end])

        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            start = output.find("{")
            end_pos = output.rfind("}") + 1
            if start >= 0 and end_pos > start:
                try:
                    return json.loads(output[start:end_pos])
                except json.JSONDecodeError:
                    pass

        logger.warning("无法解析验收报告，使用兜底逻辑")
        has_pass = any(
            w in output.lower()
            for w in ["所有测试通过", "all tests passed", '"pass": true', '"pass":true']
        )
        return {
            "pass": has_pass,
            "summary": f"[自动生成] 报告解析失败。原始输出: {output[:300]}",
            "quality_score": 6 if has_pass else 4,
            "bugs": [],
            "task_verification": [{
                "task_id": task.id,
                "passes": has_pass,
                "verification_details": "自动推断（报告解析失败）",
            }],
            "test_results": [],
            "test_files_created": [],
        }

    @staticmethod
    def _build_error_report(task: Task, error: str) -> dict:
        return {
            "pass": False,
            "summary": error,
            "quality_score": 0,
            "bugs": [],
            "task_verification": [{
                "task_id": task.id,
                "passes": False,
                "verification_details": error,
            }],
            "test_results": [],
            "test_files_created": [],
        }
