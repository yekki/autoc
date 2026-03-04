"""PlanningAgent — 项目规划师，通过 ReAct 循环探索代码库并生成 PLAN.md

设计理念 (对齐 OpenHands V1.1 PlanningAgent):
  独立 Agent 持有只读工具（read_file / list_files / glob_files / search_in_files），
  探索工作区后通过 submit_plan 提交 Markdown 格式的实现计划。
  submit_plan 通过 Function Calling schema 约束输出格式，同时写入 PLAN.md 文件。
  不修改任何代码文件、不执行任何命令——纯规划。
"""

import json
import logging

from autoc.agents.base import BaseAgent
from autoc.tools.schemas import FILE_TOOLS

logger = logging.getLogger("autoc.agent.planner")


class PlanningAgent(BaseAgent):
    """项目规划 Agent

    职责:
    1. 接收用户需求，分析技术可行性
    2. 用 read_file / list_files / glob_files / search_in_files 探索已有代码库
    3. 制定自由格式的 Markdown 实现计划（PLAN.md）
    4. 通过 submit_plan 工具提交计划，结束 ReAct 循环
    """

    agent_role = "planner"

    progress_nudge_threshold = 0.5
    progress_warn_threshold = 0.75
    progress_explore_limit = 0.7

    _SUBMIT_PLAN_TOOL = {
        "type": "function",
        "function": {
            "name": "submit_plan",
            "description": "提交实现计划并写入 PLAN.md 文件。探索完代码库并制定计划后，必须调用此工具提交最终的 Markdown 格式计划。",
            "parameters": {
                "type": "object",
                "properties": {
                    "plan_content": {
                        "type": "string",
                        "description": (
                            "完整的实现计划（Markdown 格式），包含：目标、上下文摘要、"
                            "实现方案、实现步骤（含文件清单）、验证方案"
                        ),
                    },
                },
                "required": ["plan_content"],
            },
        },
    }

    _TOOL_PHASES: dict[str, str] = {
        "read_file": "explore",
        "list_files": "explore",
        "glob_files": "explore",
        "search_in_files": "explore",
        "submit_plan": "produce",
    }

    _EXPLORE_ONLY_TOOLS: set[str] = {
        "read_file", "list_files", "glob_files", "search_in_files",
    }

    _ALLOWED_TOOLS: set[str] = {
        "read_file", "list_files", "glob_files", "search_in_files", "submit_plan",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._submitted_plan: str | None = None
        self._register_plan_handler()

    def _register_plan_handler(self):
        self._registry.register_handler(
            "submit_plan", self._handle_submit_plan,
            category="report", description="提交实现计划",
        )

    def clone(self) -> "PlanningAgent":
        cloned = super().clone()
        cloned._submitted_plan = None
        cloned._register_plan_handler()
        return cloned

    def _handle_tool_call(self, name: str, arguments: dict) -> str:
        """白名单校验：PlanningAgent 只允许只读工具 + submit_plan"""
        if name not in self._ALLOWED_TOOLS:
            return f"[错误] PlanningAgent 不允许调用工具: {name}"
        return super()._handle_tool_call(name, arguments)

    def _handle_submit_plan(self, args: dict) -> str:
        content = args.get("plan_content", "")
        if not content.strip():
            return "[错误] 计划内容不能为空"
        self._submitted_plan = content
        try:
            self.file_ops.write_file("PLAN.md", content)
        except Exception as e:
            logger.warning(f"写入 PLAN.md 文件失败: {e}")
        logger.info(f"收到实现计划 ({len(content)} chars)")
        return "计划已提交并写入 PLAN.md，规划阶段结束。"

    _prompt_cache: str | None = None

    def get_system_prompt(self) -> str:
        if self._prompt_cache is not None:
            return self._prompt_cache

        from autoc.prompts import PromptEngine
        engine = PromptEngine()
        if engine.has_template("planner_agent"):
            self._prompt_cache = engine.render("planner_agent")
        else:
            self._prompt_cache = self._fallback_system_prompt()
        return self._prompt_cache

    def _fallback_system_prompt(self) -> str:
        return """你是项目规划师 (Planning Agent)，负责分析需求并制定实现计划。

## 工作流程
1. 仔细阅读用户需求，理解目标
2. 用 glob_files 扫描项目结构（如 **/*.py）
3. 用 read_file 阅读关键文件
4. 用 search_in_files 查找相关代码和模式
5. 制定详细的实现计划
6. 调用 submit_plan 提交计划

## 计划格式 (Markdown)
```
# 目标
(要构建/实现什么)

# 上下文
(已有代码库的相关信息，或新项目的技术选型)

# 实现方案
(高层设计思路)

# 实现步骤
1. 步骤一: 描述 + 涉及的文件
2. 步骤二: ...
...

# 验证方案
(如何验证实现是否正确)
```

## 约束
- 只使用只读工具，不修改任何文件
- 计划必须具体可执行，包含明确的文件清单
- 对于简单需求（如 hello world），计划也要完整但简洁
- 用中文输出
- 完成后必须调用 submit_plan"""

    def get_tools(self) -> list[dict]:
        """PlanningAgent 工具: 只读探索 + 提交计划"""
        read_file = self._find_tool(FILE_TOOLS, "read_file")
        list_files = self._find_tool(FILE_TOOLS, "list_files")
        glob_files = self._find_tool(FILE_TOOLS, "glob_files")
        search = self._find_tool(FILE_TOOLS, "search_in_files")
        return [read_file, list_files, glob_files, search, self._SUBMIT_PLAN_TOOL]

    @staticmethod
    def _find_tool(tools: list[dict], name: str) -> dict:
        for t in tools:
            fn = t.get("function", {})
            if fn.get("name") == name:
                return t
        raise ValueError(f"工具 '{name}' 未找到")

    def execute_plan(self, requirement: str, workspace_info: str = "") -> str:
        """执行规划：探索代码库 + 生成 PLAN.md

        Args:
            requirement: 用户需求文本
            workspace_info: 工作区目录信息（可选，空字符串表示全新空目录项目）

        Returns:
            PLAN.md 内容（Markdown 字符串）
        """
        self.conversation_history = []
        self._submitted_plan = None

        # 空目录快速路径：新建项目无需 ReAct 探索，单次 LLM 调用直接生成计划
        if not workspace_info:
            fast_plan = self._single_shot_plan(requirement)
            if fast_plan:
                return fast_plan

        parts = [f"## 用户需求\n{requirement}"]

        if workspace_info:
            parts.append(f"## 工作区信息\n{workspace_info}")

        parts.append(
            "\n请分析需求，探索代码库（如有），然后制定实现计划并调用 submit_plan 提交。"
        )

        prompt = "\n\n".join(parts)

        try:
            output = self.run(prompt)
        except Exception as e:
            logger.error(f"PlanningAgent 执行异常: {e}")
            if self._submitted_plan:
                return self._submitted_plan
            return self._build_minimal_plan(requirement, str(e))

        if self._submitted_plan:
            return self._submitted_plan

        logger.warning("PlanningAgent 未调用 submit_plan，从输出中提取")
        if output and len(output) > 100 and any(kw in output for kw in ("# ", "## ", "步骤", "实现")):
            return output
        return self._build_minimal_plan(requirement, "Agent 未产出有效计划")

    def _single_shot_plan(self, requirement: str) -> str | None:
        """空目录快速路径：跳过 ReAct 探索，单次 LLM 调用生成 PLAN.md

        节省约 2 次 LLM 调用（~10-20K tokens，30-60s latency）。
        失败时返回 None，调用方回退到完整 ReAct 流程。
        """
        logger.info(f"[{self.name}] 空目录快速路径：单次 LLM 调用生成计划")
        self._emit("thinking", iteration=1, max_iterations=1)
        try:
            response = self.llm.chat(
                messages=[
                    {"role": "system", "content": self.get_system_prompt()},
                    {
                        "role": "user",
                        "content": (
                            f"## 用户需求\n{requirement}\n\n"
                            "工作区为空（全新项目），请直接制定完整实现计划，"
                            "然后调用 submit_plan 提交。"
                        ),
                    },
                ],
                tools=[self._SUBMIT_PLAN_TOOL],
            )
        except Exception as e:
            logger.warning(f"[{self.name}] 空目录快速路径 LLM 调用失败，回退到 ReAct: {e}")
            return None

        # 优先从 tool_calls 中提取 submit_plan
        # LLM 返回格式: {"name": "submit_plan", "arguments": {...}}
        for tc in response.get("tool_calls") or []:
            if tc.get("name") == "submit_plan":
                raw_args = tc.get("arguments", {})
                if isinstance(raw_args, str):
                    try:
                        args = json.loads(raw_args)
                    except Exception:
                        args = {}
                elif isinstance(raw_args, dict):
                    args = raw_args
                else:
                    args = {}
                plan = args.get("plan_content", "").strip()
                if plan:
                    self._submitted_plan = plan
                    try:
                        self.file_ops.write_file("PLAN.md", plan)
                    except Exception as e:
                        logger.warning(f"写入 PLAN.md 失败: {e}")
                    self._emit("planning_done", plan_length=len(plan), fast_path=True)
                    logger.info(f"[{self.name}] 快速路径成功（{len(plan)} chars）")
                    return plan

        # 若 LLM 返回纯文本（未调用工具），直接当 plan 使用
        content = (response.get("content") or "").strip()
        if len(content) > 100:
            self._submitted_plan = content
            try:
                self.file_ops.write_file("PLAN.md", content)
            except Exception as e:
                logger.warning(f"写入 PLAN.md 失败: {e}")
            self._emit("planning_done", plan_length=len(content), fast_path=True)
            logger.info(f"[{self.name}] 快速路径（文本模式）成功（{len(content)} chars）")
            return content

        logger.warning(f"[{self.name}] 快速路径未获得有效计划，回退到 ReAct")
        return None

    @staticmethod
    def _build_minimal_plan(requirement: str, error: str = "") -> str:
        error_note = f"\n> 注意: 规划阶段出现问题 — {error}\n" if error else ""
        return f"""# 目标
{requirement}
{error_note}
# 实现方案
直接实现用户需求。

# 实现步骤
1. 根据需求创建必要的文件
2. 实现核心功能
3. 验证功能正确性

# 验证方案
运行程序，确认输出符合预期。
"""
