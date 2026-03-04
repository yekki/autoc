"""Agent 基类 - 所有 Agent 的抽象基类

增强特性 (参考业界最佳实践):
- ReAct 循环 + Function Calling
- 上下文压缩 (参考 MetaGPT)
- 结构化输出校验 / 去幻觉机制 (参考 ChatDev)
- 思考链展示 (参考 GLM-5)
- Git/代码质量工具集成
- ToolRegistry 注册-分发模式 (替代 if-elif 硬编码)
- clone() 方法支持并行安全执行
"""

import json
import logging
import os
import re
import time
from abc import ABC, abstractmethod
from copy import copy
from typing import Any, Optional

from rich.console import Console
from rich.markup import escape as rich_escape
from rich.panel import Panel
from rich.markdown import Markdown

from autoc.core.llm import LLMClient
from autoc.core.project.memory import SharedMemory
from autoc.core.project.progress import ProgressTracker
from autoc.tools.file_ops import FileOps
from autoc.tools.shell import ShellExecutor
from autoc.tools.git_ops import GitOps, GIT_TOOLS
from autoc.tools.code_quality import CodeQualityTools, CODE_QUALITY_TOOLS
from autoc.tools.registry import ToolRegistry
from autoc.agents.context_compress import _ContextCompressMixin
from autoc.agents.tool_mixin import _ToolMixin
from autoc.agents.saic_mixin import _SAICMixin
from autoc.core.infra.stuck_detector import StuckDetector
from autoc.exceptions import ToolError, LLMAuthError, LLMRateLimitError, LLMTimeoutError, AgentStuckError

console = Console()
logger = logging.getLogger("autoc.agent")


class BaseAgent(_ToolMixin, _SAICMixin, _ContextCompressMixin, ABC):
    """
    Agent 基类

    每个 Agent 具有:
    - 角色身份 (system prompt)
    - LLM 调用能力
    - 工具调用能力 (文件操作, Shell, Git, 代码质量)
    - 共享记忆访问
    - 多轮对话与推理循环
    - 上下文压缩能力（可插拔 Condenser 策略 + 紧急压缩兜底）
    - 结构化输出校验 (去幻觉)
    - clone() 支持并行任务安全
    """

    # 子类可覆盖此属性，用于上下文按角色裁剪
    agent_role: str = "all"

    # ---- 智能迭代控制 (SAIC) 阈值，子类可覆盖 ----
    progress_nudge_threshold: float = 0.5   # 开始温和提醒的预算比例
    progress_warn_threshold: float = 0.75   # 开始强烈警告的预算比例
    progress_explore_limit: float = 0.6     # 探索阶段占比上限

    # 工具 → 阶段映射 (explore / produce / execute)
    _TOOL_PHASES: dict[str, str] = {
        "read_file": "explore", "list_files": "explore",
        "search_in_files": "explore", "git_log": "explore",
        "git_diff": "explore", "git_status": "explore",
        "glob_files": "explore",
        "think": "explore",
        "write_file": "produce", "create_directory": "produce",
        "edit_file": "produce",
        "execute_command": "execute",
        "format_code": "execute", "lint_code": "execute",
    }

    # 工具降级时会被剥离的探索类工具（SAIC Layer 2.5）
    _EXPLORE_ONLY_TOOLS: set[str] = {
        "read_file", "list_files", "search_in_files",
        "git_log", "git_diff", "git_status",
    }

    def __init__(
        self,
        name: str,
        role_description: str,
        llm_client: LLMClient,
        memory: SharedMemory,
        file_ops: FileOps,
        shell: ShellExecutor,
        max_iterations: int = 10,
        color: str = "cyan",
        on_event=None,
        context_limit: int = 35000,
        git_ops: Optional[GitOps] = None,
        code_quality: Optional[CodeQualityTools] = None,
        progress_tracker: Optional[ProgressTracker] = None,
        condenser=None,
    ):
        self.name = name
        self.role_description = role_description
        self.llm = llm_client
        self.memory = memory
        self.file_ops = file_ops
        self.shell = shell
        self.max_iterations = max_iterations
        self.color = color
        self.on_event = on_event
        self.context_limit = context_limit
        self.git_ops = git_ops
        self.code_quality = code_quality
        self.progress_tracker = progress_tracker
        self.condenser = condenser
        self._skill_prompt_cache: str = ""
        self._skill_prompt_cache_ts: float = 0.0
        self.conversation_history: list[dict] = []
        self._iteration_count = 0

        # Trace 双轨日志（JSONL + HTML），由外部注入
        self.trace_logger = None

        self._helper_llm: LLMClient | None = None

        # Ralph guardrails 上下文 (由 inject_guardrails 注入)
        self._guardrails_context: str = ""

        # 文件内容缓存: path -> (content, mtime_ns)
        self._file_cache: dict[str, tuple[str, float]] = {}
        # 记录上轮 Tester 以来被 Developer 修改的文件
        self._changed_files: set[str] = set()

        # SAIC 进度追踪状态 (每次 run() 重置)
        self._phase_counts: dict[str, int] = {}
        self._recent_tools: list[tuple[str, str]] = []  # (tool_name, first_arg_value)
        self._nudge_level: int = 0  # 已发出的最高提醒级别，防止重复

        # 生产力追踪：最近一次 produce/execute 工具调用的迭代号（SAIC Layer 3 使用）
        self._last_produce_iter: int = 0

        # Stuck Detector — Agent 级别的微循环检测
        self._stuck_detector = StuckDetector()

        # 熔断器状态 (每次 run() 重置)
        self._consecutive_errors: int = 0  # 连续工具错误计数
        self._llm_error_count: int = 0     # 连续 LLM 调用错误计数（与工具错误分开统计）
        self._circuit_breaker_warned: bool = False  # 是否已注入熔断警告

        # 构建工具注册表（传入 workspace_dir 供 MCP 路径适配）
        ws_dir = self.file_ops.workspace_dir if self.file_ops else ""
        self._registry = ToolRegistry(workspace_dir=ws_dir)
        self._register_builtin_tools()

    # ==================== 抽象接口 ====================

    @abstractmethod
    def get_system_prompt(self) -> str:
        """获取角色系统提示词"""
        pass

    @abstractmethod
    def get_tools(self) -> list[dict]:
        """获取可用工具定义（子类应调用 _merge_mcp_tools() 合并 MCP 工具）"""
        pass

    def _get_iteration_tools(self, iteration: int, base_tools: list[dict]) -> list[dict]:
        """每轮迭代的工具列表钩子，子类可覆盖实现动态工具注入/剥离

        默认行为：原样返回 base_tools，不做任何修改。
        """
        return base_tools

    def _get_submit_hint(self, iteration: int) -> str:
        """返回兜底提示文本（子类可覆盖）；默认不注入任何提示"""
        return ""

    # ==================== clone() — 并行安全 ====================

    def clone(self) -> "BaseAgent":
        """创建一个并行安全的浅拷贝

        共享不可变/线程安全的资源（llm, memory, file_ops, shell 等），
        但为每个克隆实例创建独立的对话历史和文件追踪状态。
        用于迭代循环中的并行任务执行和上下文轮转。
        """
        cloned = copy(self)
        cloned.conversation_history = []
        cloned._iteration_count = 0
        cloned._file_cache = {}
        cloned._changed_files = set()
        cloned._phase_counts = {}
        cloned._recent_tools = []
        cloned._nudge_level = 0
        cloned._stuck_detector = StuckDetector()
        cloned._last_produce_iter = 0
        cloned._initial_max_iterations = cloned.max_iterations
        cloned._guardrails_context = ""
        # 熔断器状态独立重置，防止主实例的错误计数污染并行克隆
        cloned._consecutive_errors = 0
        cloned._llm_error_count = 0
        cloned._circuit_breaker_warned = False
        # 对话存储隔离：并行克隆不共享 _conversation_store，避免并发写入冲突
        cloned._conversation_store = None
        cloned._conversation_iteration = 0
        cloned._skill_prompt_cache = ""
        cloned._skill_prompt_cache_ts = 0.0
        # 并行执行时创建独立 LLMClient，避免 token 计数器在多线程下竞态
        # clone() 用于 ParallelExecutor：各 clone 使用相同配置但有独立的 call_log 和计数器
        # 仅当 llm.config 为真实 LLMConfig 时才创建新实例（测试中 llm 为 MagicMock 时跳过）
        from autoc.core.llm import LLMClient
        from autoc.core.llm.client import LLMConfig

        def _clone_llm(original: LLMClient | None) -> LLMClient | None:
            if original is None:
                return None
            if not isinstance(getattr(original, "config", None), LLMConfig):
                return original
            new = LLMClient(original.config)
            if original._completion_log_dir:
                new.enable_completion_logging(original._completion_log_dir)
            new.set_tag(original._current_tag)
            return new

        cloned.llm = _clone_llm(self.llm)
        cloned._helper_llm = _clone_llm(self._helper_llm)
        # 重建工具注册表（绑定到新实例的方法）
        ws_dir = cloned.file_ops.workspace_dir if cloned.file_ops else ""
        cloned._registry = ToolRegistry(workspace_dir=ws_dir)
        cloned._register_builtin_tools()
        return cloned

    # ==================== Ralph 上下文轮转支持 ====================

    def reset_context(self):
        """清空对话历史 — Ralph 模式的上下文轮转

        每次 Ralph 迭代开始时调用，确保 Agent 从全新上下文开始。
        保留工具注册表和共享资源，只清空对话历史和迭代状态。
        参考: snarktank/ralph "Each Iteration = Fresh Context"
        """
        self.conversation_history = []
        self._iteration_count = 0
        self._file_cache = {}
        self._changed_files = set()
        self._phase_counts = {}
        self._recent_tools = []
        self._nudge_level = 0
        self._stuck_detector.reset()
        self._last_produce_iter = 0
        self._initial_max_iterations = self.max_iterations
        self._consecutive_errors = 0
        self._llm_error_count = 0
        self._circuit_breaker_warned = False

    def inject_guardrails(self, guardrails: str, codebase_patterns: str = ""):
        """注入 guardrails 和 codebase patterns 到 Agent 上下文

        Ralph 模式下，每次迭代从文件读取 guardrails 和 patterns，
        注入到 Agent 的 system prompt 中，替代累积的对话历史。
        参考: snarktank/ralph AGENTS.md + progress.txt
        """
        parts = []
        if guardrails:
            parts.append(f"\n## Guardrails (必须遵守)\n{guardrails}")
        if codebase_patterns:
            parts.append(f"\n## Codebase Patterns (已知模式)\n{codebase_patterns}")
        self._guardrails_context = "\n".join(parts)

    # ==================== 辅助方法 ====================

    def _guess_language(self, path: str) -> str:
        ext_map = {
            ".py": "python", ".js": "javascript", ".ts": "typescript",
            ".jsx": "react", ".tsx": "react-typescript",
            ".html": "html", ".css": "css", ".scss": "scss",
            ".json": "json", ".yaml": "yaml", ".yml": "yaml",
            ".md": "markdown", ".sh": "shell", ".sql": "sql",
            ".go": "go", ".rs": "rust", ".java": "java",
            ".vue": "vue", ".svelte": "svelte",
        }
        for ext, lang in ext_map.items():
            if path.endswith(ext):
                return lang
        return ""

    def _emit(self, event_type: str, **data):
        if self.on_event:
            self.on_event({
                "type": event_type,
                "agent": self.name,
                "data": data,
            })

    def _log(self, message: str, style: str = ""):
        console.print(
            Panel(
                Markdown(message) if "\n" in message else message,
                title=f"🤖 {self.name}",
                border_style=self.color,
                expand=False,
            )
        )
        self._emit("agent_log", message=message)

    # _validate_json_output / _self_review / _estimate_tokens / _sliding_window_compress /
    # _compress_history 等上下文管理方法由 _ContextCompressMixin 提供
    # 如注入了 condenser（Condenser 实例），则优先使用 condenser 替代滑动窗口

    def _pre_condense_hook(self):
        """迭代开始时、上下文压缩前的预处理钩子（子类可覆盖）"""
        pass

    def _truncate_tool_outputs(self, messages: list[dict], max_chars: int = 16000) -> list[dict]:
        """截断保留消息中过长的 tool 输出，保留首尾关键信息"""
        result = []
        for msg in messages:
            content = str(msg.get("content", ""))
            if msg.get("role") != "tool" or len(content) <= max_chars:
                result.append(msg)
                continue
            lines = content.split("\n")
            if len(lines) <= 30:
                truncated = content[:max_chars] + f"\n... [截断，原始 {len(content)} 字符]"
            else:
                head = "\n".join(lines[:12])
                tail = "\n".join(lines[-8:])
                omitted = len(lines) - 20
                truncated = f"{head}\n\n... [{omitted} 行已省略] ...\n\n{tail}"
                if len(truncated) > max_chars:
                    truncated = truncated[:max_chars] + f"\n... [截断至 {max_chars} 字符]"
            result.append({**msg, "content": truncated})
        return result

    # ==================== 核心运行循环 ====================

    # Skill Registry — 由 Orchestrator 注入
    _skill_registry: Any = None
    _SKILL_CACHE_TTL: float = 300.0  # 5 分钟 TTL

    # 由 Orchestrator 注入
    _conversation_store: Any = None
    _conversation_iteration: int = 0
    _event_log: Any = None
    _user_profile: Any = None

    def _build_session_startup_context(self) -> str:
        """构建 Session 启动上下文 (参考 Anthropic/SamuelQZQ)"""
        parts = []

        if self.progress_tracker:
            session_ctx = self.progress_tracker.get_session_context()
            if session_ctx:
                parts.append(session_ctx)

        if self.git_ops:
            try:
                git_log = self.git_ops.log(5)
                if git_log.strip():
                    parts.append(f"## Git 最近提交\n```\n{git_log[:500]}\n```")
            except Exception:
                pass

        memory_ctx = self.memory.to_context_string(agent_role=self.agent_role)
        if memory_ctx:
            parts.append(memory_ctx)

        # Skill 注入：按技术栈和角色匹配
        skill_prompt = self._get_skill_prompt()
        if skill_prompt:
            parts.append(skill_prompt)

        # F4: UserProfile 注入 — 用户偏好影响 Agent 行为
        if self._user_profile:
            try:
                profile_prompt = self._user_profile.for_agent_prompt(self.agent_role)
                if profile_prompt:
                    parts.append(profile_prompt)
            except Exception:
                pass

        # F3: EventLog 上下文 — 将近期关键事件注入 session
        if self._event_log:
            try:
                summary = self._event_log.export_for_condenser(max_events=10)
                if summary:
                    parts.append(f"## 近期事件\n{summary}")
            except Exception:
                pass

        # 断点续传上下文：由 lifecycle._load_conversation_resume_context 注入
        resume_ctx = getattr(self, "_conversation_resume_context", None)
        if resume_ctx:
            recent = resume_ctx.get("recent_context", "")
            iteration = resume_ctx.get("iteration", 0)
            if recent:
                parts.append(
                    f"## 上次会话断点续传\n"
                    f"（快照 {resume_ctx.get('snapshot_id', '')}, "
                    f"已执行 {iteration} 轮，最近操作：\n{recent}）"
                )

        return "\n\n".join(parts)

    def _get_skill_prompt(self) -> str:
        """获取匹配的 Skill prompt（带 TTL 缓存，防止长 session 中技术栈变化后缓存过期）"""
        import time as _time
        now = _time.time()
        if self._skill_prompt_cache and (now - self._skill_prompt_cache_ts < self._SKILL_CACHE_TTL):
            return self._skill_prompt_cache
        if not self._skill_registry:
            return ""
        tech_stack = []
        if hasattr(self.memory, "tech_profile") and self.memory.tech_profile:
            tech_stack = self.memory.tech_profile.tags
        skills = self._skill_registry.match(
            tech_stack=tech_stack, agent_role=self.agent_role,
        )
        if skills:
            self._skill_prompt_cache = self._skill_registry.format_for_prompt(skills)
        else:
            self._skill_prompt_cache = ""
        self._skill_prompt_cache_ts = now
        return self._skill_prompt_cache

    # 熔断器阈值（子类可覆盖）
    circuit_breaker_warn_at: int = 3   # 连续 N 次错误后注入强制输出警告
    circuit_breaker_abort_at: int = 5  # 连续 N 次错误后提前终止循环

    @property
    def _MAX_TOOL_RESULT_CHARS(self) -> int:
        """工具结果在对话历史中保留的最大字符数（延迟截断策略）。

        计算方式：context_limit 的 10% token 预算，按 ~4 char/token 换算为字符数。
        下限 8000（确保最短的 traceback 可见），上限 30000（防止单条吃掉太多 context）。
        默认 context_limit=35000 → 14000 chars；context_limit=60000 → 24000 chars。
        """
        dynamic = int(self.context_limit * 0.10 * 4)
        return max(8000, min(dynamic, 30000))

    def _truncate_prev_tool_results(self):
        """行级智能裁剪历史中的 tool result（SWE-Pruner 启发）。

        根据内容模式选择裁剪策略，保留结构信息而非暴力字符截断。
        错误消息不裁剪，确保熔断器逻辑可见完整错误。
        """
        for msg in self.conversation_history:
            if msg.get("role") != "tool" or msg.get("_truncated"):
                continue
            content = msg.get("content", "")
            if content.startswith("[错误]") or content.startswith("[超时]"):
                continue
            max_chars = self._MAX_TOOL_RESULT_CHARS
            if len(content) <= max_chars:
                continue
            msg["content"] = self._smart_line_truncate(content, max_chars)
            msg["_truncated"] = True

    @staticmethod
    def _smart_line_truncate(content: str, hard_limit: int = 20000) -> str:
        """按内容模式做行级裁剪，保留结构信息（SWE-Pruner 启发）。

        策略优先级:
        1. Traceback: 保留首 5 行 + 完整 Traceback 块（最后 20 行）
        2. 代码文件: 保留首 15 行 + 签名摘要 + 末 10 行
        3. 通用输出: 保留首 8 行 + 末 20 行
        """
        lines = content.split("\n")
        total = len(lines)
        if total <= 40:
            if len(content) > hard_limit:
                return content[:hard_limit] + f"\n[...裁剪至 {hard_limit} 字符]"
            return content

        # 只用行首 "Traceback" 检测，避免注释/字符串中的 "Error:" 误触发
        has_traceback = any(l.lstrip().startswith("Traceback") for l in lines[-30:])
        code_sig_count = sum(
            1 for l in lines
            if l.lstrip().startswith(("def ", "class ", "import ", "from "))
        )

        if has_traceback:
            # 从后往前找最后一个 Traceback，确保保留最相关的异常栈
            tb_start = 0
            for i in range(len(lines) - 1, -1, -1):
                if lines[i].lstrip().startswith("Traceback"):
                    tb_start = i
                    break
            tb_block = lines[tb_start:][-20:]
            head = lines[:5]
            omitted = total - len(head) - len(tb_block)
            kept = head + ["", f"... [{omitted} 行已省略] ...", ""] + tb_block
        elif code_sig_count >= 3:
            sig_lines = [
                l for l in lines
                if l.lstrip().startswith(("def ", "class ", "import ", "from ", "@"))
            ][:15]
            head = lines[:15]
            tail = lines[-10:]
            kept = head + ["", f"... [签名摘要，共 {total} 行] ..."] + sig_lines + ["", "..."] + tail
        else:
            head = lines[:8]
            tail = lines[-20:]
            omitted = total - len(head) - len(tail)
            kept = head + ["", f"... [{omitted} 行已省略] ...", ""] + tail

        result = "\n".join(kept)
        if len(result) > hard_limit:
            result = result[:hard_limit] + f"\n[...裁剪至 {hard_limit} 字符]"
        return result

    # 致命错误关键字：出现这些直接计为"不可恢复"
    _FATAL_ERROR_KEYWORDS: tuple[str, ...] = (
        "不在工作区", "越界路径",           # 路径错误（绝对路径）
        "Permission denied",               # 权限错误
        "No module named",                 # 依赖缺失（pip install 解决不了的）
        "command not found",               # 命令不存在
        "cannot find", "Cannot find",      # 文件/命令找不到
        "executable file not found",       # 可执行文件缺失
    )

    def run(self, task_prompt: str, *, continuation: bool = False) -> str:
        """运行 Agent 执行任务 — 增强的 ReAct 循环 + SAIC 智能迭代控制

        Args:
            task_prompt: 任务描述
            continuation: 为 True 时保留已有 conversation_history，
                         仅追加新 user message 继续 ReAct 循环（对齐 OpenHands 会话持续累积）。
        """
        self._phase_counts = {}
        self._recent_tools = []
        self._nudge_level = 0
        self._stuck_detector.reset()
        self._last_produce_iter = 0
        self._consecutive_errors = 0
        self._llm_error_count = 0
        self._circuit_breaker_warned = False
        if not continuation:
            self._changed_files = set()

        if continuation and self.conversation_history:
            self._iteration_count = 0
            self._initial_max_iterations = self.max_iterations
            self.conversation_history.append({
                "role": "user",
                "content": task_prompt,
            })
        else:
            self._iteration_count = 0
            self._initial_max_iterations = self.max_iterations

            system_prompt = self.get_system_prompt()
            self.conversation_history = [
                {"role": "system", "content": system_prompt},
            ]

            context = self._build_session_startup_context()
            if context:
                self.conversation_history.append({
                    "role": "user",
                    "content": f"## Session 启动 - 项目当前状态\n\n{context}",
                })
                self.conversation_history.append({
                    "role": "assistant",
                    "content": "我已了解项目当前状态和进度，准备执行任务。",
                })

            self.conversation_history.append({
                "role": "user",
                "content": task_prompt,
            })

        _suffix = "..." if len(task_prompt) > 200 else ""
        self._log(f"开始执行任务...\n\n> {task_prompt[:200]}{_suffix}")

        tools = self.get_tools()
        degraded_tools: list[dict] | None = None  # 降级后的工具列表（惰性构建）
        final_output = ""
        _abort = False  # 熔断器触发标志

        try:
            while self._iteration_count < self.max_iterations and not _abort:
                self._iteration_count += 1
                logger.info(f"[{self.name}] 迭代 {self._iteration_count}/{self.max_iterations}")

                # 延迟截断：上一迭代的工具结果在本迭代开始时截断，
                # 确保 LLM 在产出结果的那一轮能看到完整内容
                self._truncate_prev_tool_results()

                self._pre_condense_hook()

                if self.condenser:
                    self.conversation_history = self.condenser.condense(
                        self.conversation_history, self.name, self._iteration_count,
                    )
                else:
                    self._sliding_window_compress()

                estimated_tokens = self._estimate_tokens(self.conversation_history)
                if estimated_tokens > self.context_limit:
                    logger.warning(
                        f"[{self.name}] 滑动窗口后仍超限 (约 {estimated_tokens} tokens > {self.context_limit})，紧急压缩..."
                    )
                    self._compress_history()
                    # 紧急压缩后仍超限 → 对保留消息做 tool 输出截断（最后防线）
                    if self._estimate_tokens(self.conversation_history) > self.context_limit:
                        self.conversation_history = [
                            self.conversation_history[0]
                        ] + self._truncate_tool_outputs(
                        self.conversation_history[1:],
                        max_chars=self._MAX_TOOL_RESULT_CHARS // 2,
                    )
                elif estimated_tokens > self.context_limit * 0.75:
                    self.conversation_history = [
                        self.conversation_history[0]
                    ] + self._truncate_tool_outputs(self.conversation_history[1:])

                # --- SAIC Layer 3: 生产力驱动的工具剥离 ---
                remaining_iters = self.max_iterations - self._iteration_count
                current_tools = tools
                hard_cap = int(self._initial_max_iterations * 1.5)
                at_hard_cap = self._iteration_count >= hard_cap
                stale_iters = self._iteration_count - self._last_produce_iter
                is_producing = stale_iters <= 2

                # 决策：是否剥离工具
                # 1. 硬上限（初始预算×1.5）：无论如何都终止
                # 2. 软上限到达 + Agent 不再产出：终止
                # 3. 软上限到达 + Agent 仍在产出：自动延伸 1 轮（不超过硬上限）
                strip_tools = False
                nudge_msg = ""

                if at_hard_cap:
                    strip_tools = True
                    nudge_msg = self._build_forced_output_nudge()
                    logger.info(
                        f"[{self.name}] SAIC: 达到硬上限 {hard_cap}，强制输出"
                    )
                elif remaining_iters <= 1:
                    if is_producing and self._iteration_count + 1 < hard_cap:
                        self.max_iterations += 1
                        remaining_iters = self.max_iterations - self._iteration_count
                        logger.info(
                            f"[{self.name}] SAIC: 软上限到达但 Agent 仍在产出"
                            f"（上次写文件在 {stale_iters} 轮前），"
                            f"自动延伸至 {self.max_iterations}/{hard_cap}"
                        )
                    else:
                        strip_tools = True
                        nudge_msg = (
                            f"⏰ 仅剩 {remaining_iters + 1} 次迭代。工具已被禁用，"
                            "请立即整理并输出最终结果（JSON 报告 / 代码分析 / 任务总结）。"
                            "即使工作未 100% 完成，也请输出当前已有的结果。"
                        )
                        logger.info(
                            f"[{self.name}] SAIC: 软上限到达且 Agent 已停滞"
                            f"（{stale_iters} 轮无产出），剥离工具"
                        )

                if strip_tools:
                    current_tools = None
                    self.conversation_history.append({"role": "user", "content": nudge_msg})
                else:
                    # --- SAIC Layer 2 + 2.5: 动态提醒注入 + 工具降级 ---
                    nudge, should_degrade = self._check_progress()
                    if nudge:
                        self.conversation_history.append({"role": "user", "content": nudge})
                        logger.info(f"[{self.name}] SAIC Layer 2: 注入进度提醒 (level={self._nudge_level})")

                    # --- 子类扩展点：最后几轮兜底提示（如 submit_test_report 提醒）---
                    submit_hint = self._get_submit_hint(self._iteration_count)
                    if submit_hint:
                        self.conversation_history.append({"role": "user", "content": submit_hint})
                        logger.info(f"[{self.name}] 注入兜底提示: {submit_hint[:60]}")
                    if should_degrade:
                        if degraded_tools is None:
                            degraded_tools = [
                                t for t in tools
                                if t.get("function", {}).get("name") not in self._EXPLORE_ONLY_TOOLS
                            ]
                            logger.info(
                                f"[{self.name}] SAIC Layer 2.5: 工具降级，"
                                f"{len(tools)} → {len(degraded_tools)} 个工具（剥离探索类）"
                            )
                        current_tools = degraded_tools

                # --- 最终过滤：子类可通过 _get_iteration_tools 动态调整工具集 ---
                # 在所有 SAIC 决策之后执行，确保与 Layer 2.5 工具降级正确组合
                if current_tools is not None:
                    current_tools = self._get_iteration_tools(
                        self._iteration_count, current_tools,
                    )

                self._emit(
                    "thinking",
                    iteration=self._iteration_count,
                    max_iterations=self.max_iterations,
                )
                # 设置 per-tag 标记，支持共享实例下的 Agent 级别 Token 拆分
                self.llm.set_tag(self.__class__.__name__)
                try:
                    response = self.llm.chat(
                        messages=self.conversation_history,
                        tools=current_tools if current_tools else None,
                    )
                except LLMAuthError:
                    self._log("🔴 API Key 无效或已过期，无法继续")
                    _abort = True
                    break
                except (LLMRateLimitError, LLMTimeoutError) as e:
                    self._llm_error_count += 1
                    # 指数退避：2^(errors-1) 秒，最长 60 秒，避免立刻重打后端
                    backoff = min(60, 2 ** (self._llm_error_count - 1))
                    logger.warning(
                        f"[{self.name}] LLM 瞬态错误: {e}，第 {self._llm_error_count} 次，"
                        f"{backoff}s 后重试"
                    )
                    if self._llm_error_count >= self.circuit_breaker_abort_at:
                        _abort = True
                        break
                    time.sleep(backoff)
                    continue
                except Exception as e:
                    logger.error(f"[{self.name}] LLM 调用未知异常: {e}")
                    self._llm_error_count += 1
                    if self._llm_error_count >= self.circuit_breaker_abort_at:
                        _abort = True
                        break
                    continue

                # LLM 成功：重置 LLM 错误计数（工具错误计数独立，不受影响）
                self._llm_error_count = 0
                content = response["content"]
                tool_calls = response["tool_calls"]
                reasoning_content = response.get("reasoning_content", "")

                if reasoning_content:
                    display_reasoning = reasoning_content[:500] + ("..." if len(reasoning_content) > 500 else "")
                    console.print(
                        Panel(
                            display_reasoning,
                            title=f"💭 {self.name} 思考中",
                            border_style="dim",
                            expand=False,
                        )
                    )
                    self._emit("thinking_content",
                               content=display_reasoning,
                               iteration=self._iteration_count)

                if content:
                    msg: dict[str, Any] = {"role": "assistant", "content": content}
                    if reasoning_content:
                        msg["reasoning_content"] = reasoning_content
                    self.conversation_history.append(msg)
                    final_output = content

                if not tool_calls:
                    # 记录本轮为独白轮次，仅检测 MONOLOGUE 模式（避免误判正常完成）
                    self._stuck_detector.record_no_tool()
                    monologue_signal = self._stuck_detector.check_monologue_only()
                    if monologue_signal:
                        severity = monologue_signal.severity
                        if severity >= 3:
                            logger.warning(
                                f"[{self.name}] StuckDetector L3（monologue，severity={severity}）: "
                                f"— 上报 Orchestrator"
                            )
                            raise AgentStuckError(signal=monologue_signal)
                        elif severity == 2:
                            logger.warning(
                                f"[{self.name}] StuckDetector L2（monologue）: 咨询 helper + 截断历史"
                            )
                            self._truncate_stuck_history(monologue_signal.window_size)
                            helper_advice = self._auto_consult_helper(monologue_signal)
                            self.conversation_history.append({"role": "user", "content": helper_advice})
                            continue
                        else:
                            logger.warning(f"[{self.name}] StuckDetector L1（monologue）")
                            stuck_msg = (
                                f"⚠️ 停滞检测: {monologue_signal.description}\n"
                                f"建议: {monologue_signal.suggestion}"
                            )
                            self.conversation_history.append({"role": "user", "content": stuck_msg})
                            continue
                    self._log(f"任务完成 (迭代 {self._iteration_count} 次)")
                    break

                assistant_msg: dict[str, Any] = {"role": "assistant", "content": content or ""}
                if reasoning_content:
                    assistant_msg["reasoning_content"] = reasoning_content
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["arguments"], ensure_ascii=False),
                        },
                    }
                    for tc in tool_calls
                ]

                if content and self.conversation_history[-1]["role"] == "assistant":
                    self.conversation_history[-1] = assistant_msg
                else:
                    self.conversation_history.append(assistant_msg)

                # 执行本轮所有工具调用，收集 (is_error, tool_name, tool_args, result) 供后续分析
                _batch_any_error = False
                for tc in tool_calls:
                    tool_name = tc["name"]
                    tool_args = tc["arguments"]
                    tool_id = tc["id"]

                    safe_args = rich_escape(self._format_args(tool_args))
                    console.print(
                        f"  🔧 [dim]{self.name}[/dim] 调用工具: "
                        f"[bold]{tool_name}[/bold]({safe_args})"
                    )
                    self._emit("tool_call", tool=tool_name, args=self._format_args(tool_args))

                    result = self._handle_tool_call(tool_name, tool_args)

                    # 当前迭代存完整结果（LLM 需要看完整内容做决策），
                    # 下一迭代开始前由 _truncate_prev_tool_results() 截断旧结果
                    self.conversation_history.append({
                        "role": "tool",
                        "tool_call_id": tool_id,
                        "content": result,
                    })

                    display_result = result[:300] + "..." if len(result) > 300 else result
                    console.print(f"  📋 结果: [dim]{rich_escape(display_result)}[/dim]")
                    self._emit("tool_result", tool=tool_name, result=display_result)

                    # --- SAIC Layer 1: 追踪工具调用阶段 ---
                    self._track_tool_call(tool_name, tool_args)

                    # --- Stuck Detector: 记录（检测在循环外统一做）---
                    is_error = result.startswith("[错误]") or result.startswith("[超时]") or result.startswith("[沙箱错误]")
                    self._stuck_detector.record(
                        tool_name, tool_args, result,
                        has_error=is_error,
                        error_message=result[:200] if is_error else "",
                    )
                    if is_error:
                        _batch_any_error = True

                    # --- 对话增量持久化 (debounced) ---
                    if self._conversation_store:
                        self._conversation_store.maybe_save(
                            self.name, self.conversation_history,
                            iteration=self._iteration_count,
                            metadata={"tool": tool_name},
                        )

                    # --- 熔断器：实时错误监测 ---
                    if is_error:
                        self._consecutive_errors += 1
                        is_fatal = any(kw in result for kw in self._FATAL_ERROR_KEYWORDS)

                        if is_fatal or self._consecutive_errors >= self.circuit_breaker_abort_at:
                            # 不可恢复错误 / 连续错误达到终止阈值 → 提前退出
                            reason = "致命错误（路径越界/权限/命令不存在）" if is_fatal else f"连续 {self._consecutive_errors} 次工具调用失败"
                            self._log(f"🔴 熔断器触发：{reason}，提前终止避免无效消耗")
                            self._emit("circuit_breaker_abort", reason=reason,
                                       consecutive_errors=self._consecutive_errors,
                                       last_error=result[:200])
                            _abort = True
                            break  # 跳出内层 for 循环；while 条件中的 not _abort 跳出外层

                    else:
                        self._consecutive_errors = 0  # 成功则重置计数

                # 熔断器警告：在 for 循环外注入，避免破坏 tool result 消息配对
                if not _abort and self._consecutive_errors >= self.circuit_breaker_warn_at and not self._circuit_breaker_warned:
                    self._circuit_breaker_warned = True
                    warn_msg = (
                        f"⚠️ 连续 {self._consecutive_errors} 次工具调用失败。"
                        "当前环境可能存在问题。请**立即停止重试**，"
                        "基于已有信息输出最终结果（即使不完整也要输出）。"
                    )
                    self.conversation_history.append({"role": "user", "content": warn_msg})
                    logger.warning(f"[{self.name}] 熔断器警告：连续 {self._consecutive_errors} 次错误，注入强制输出提示")

                # --- Stuck Detector: 本轮所有工具执行完毕后统一检测（避免破坏消息配对）---
                if not _abort:
                    is_stuck, stuck_signal = self._stuck_detector.check()
                    if is_stuck and stuck_signal:
                        severity = stuck_signal.severity
                        if severity >= 3:
                            logger.warning(
                                f"[{self.name}] StuckDetector L3（severity={severity}）: "
                                f"{stuck_signal.pattern.value} — 上报 Orchestrator"
                            )
                            raise AgentStuckError(signal=stuck_signal)
                        elif severity == 2:
                            logger.warning(
                                f"[{self.name}] StuckDetector L2（severity=2）: "
                                f"{stuck_signal.pattern.value} — 咨询 helper + 截断历史"
                            )
                            self._truncate_stuck_history(stuck_signal.window_size)
                            helper_advice = self._auto_consult_helper(stuck_signal)
                            self.conversation_history.append({"role": "user", "content": helper_advice})
                        else:
                            logger.warning(
                                f"[{self.name}] StuckDetector L1（severity=1）: "
                                f"{stuck_signal.pattern.value}"
                            )
                            stuck_msg = (
                                f"⚠️ 停滞检测: {stuck_signal.description}\n"
                                f"建议: {stuck_signal.suggestion}"
                            )
                            self.conversation_history.append({"role": "user", "content": stuck_msg})
                    elif not _batch_any_error:
                        # 本轮无 stuck 且全部工具成功 → 重置连续 stuck 计数
                        self._stuck_detector.reset_consecutive()

            # while-else 在 _abort=True 时同样触发（条件自然变 False），
            # 改为显式检查：仅当迭代耗尽（非熔断/正常完成）时才上报。
            if self._iteration_count >= self.max_iterations and not _abort:
                diagnosis = self._diagnose_exhaustion()
                self._log(f"⚠️ 达到最大迭代次数 ({self.max_iterations})\n\n{diagnosis}")
                self._emit("iteration_exhausted", diagnosis=diagnosis,
                           max_iterations=self.max_iterations)

        finally:
            # 恢复原始 max_iterations，防止 SAIC 自动延伸的计数跨调用累积通胀
            self.max_iterations = self._initial_max_iterations
            # 最终快照：无论正常结束/迭代耗尽/AgentStuckError 都需保存
            self._save_final_snapshot(final_output)
        return final_output

    def _save_final_snapshot(self, final_output: str) -> None:
        """保存最终对话快照（供正常结束和异常退出复用）"""
        if self._conversation_store:
            try:
                self._conversation_store.save_snapshot(
                    self.name, self.conversation_history,
                    iteration=self._iteration_count,
                    metadata={"final": True, "output_len": len(final_output)},
                )
            except Exception as e:
                logger.warning(f"[{self.name}] 最终快照保存失败: {e}")

    def _truncate_stuck_history(self, loop_length: int) -> None:
        """截断导致循环的对话历史，清除坏上下文。

        保留 system message + 循环前的历史，移除最近 loop_length * severity 条记录。
        最少保留 3 条（system + 1 user + 1 assistant），防止过度截断。
        参考 OpenHands _truncate_memory_to_point()。
        """
        min_keep = 3
        to_remove = max(1, loop_length)
        keep_until = max(min_keep, len(self.conversation_history) - to_remove)
        if keep_until < len(self.conversation_history):
            removed = len(self.conversation_history) - keep_until
            self.conversation_history = self.conversation_history[:keep_until]
            logger.info(
                f"[{self.name}] stuck 历史截断: 移除最近 {removed} 条消息，"
                f"剩余 {len(self.conversation_history)} 条"
            )

        # 截断后校验：确保最后一条 assistant(tool_calls) 和其 tool results 成对存在
        hist = self.conversation_history
        while len(hist) > min_keep:
            last_assistant_idx = None
            for i, msg in enumerate(hist):
                if msg.get("role") == "assistant" and msg.get("tool_calls"):
                    last_assistant_idx = i
            if last_assistant_idx is None:
                break
            tc_ids = {tc.get("id") for tc in hist[last_assistant_idx].get("tool_calls", [])}
            tool_ids_after = {
                msg.get("tool_call_id")
                for msg in hist[last_assistant_idx + 1:]
                if msg.get("role") == "tool"
            }
            if tc_ids <= tool_ids_after:
                break
            self.conversation_history = hist[:last_assistant_idx]
            hist = self.conversation_history
            if len(hist) <= min_keep:
                break

    def _auto_consult_helper(self, stuck_signal) -> str:
        """停滞时自动调用 helper LLM 获取针对性建议（L2 恢复使用）。

        若无 helper LLM，降级为返回增强提示文本。
        """
        if not self._helper_llm:
            return (
                f"⚠️ 再次检测到停滞（{stuck_signal.pattern.value}）：{stuck_signal.description}\n"
                f"**强制要求**：{stuck_signal.suggestion}\n"
                "请立即改变策略，不要再重复已失败的操作。"
            )
        try:
            question = (
                f"当前 Agent（{self.name}）检测到停滞模式「{stuck_signal.pattern.value}」：\n"
                f"- 现象：{stuck_signal.description}\n"
                f"- 已尝试但失败的操作：请根据上下文分析\n\n"
                f"请给出 2-3 个具体的、与当前方向不同的替代解决步骤。"
            )
            messages = [
                {"role": "system", "content": "你是辅助 AI，专门在代码 Agent 停滞时提供突破性建议。简洁直接，给出可立即执行的具体操作步骤。"},
                {"role": "user", "content": question},
            ]
            response = self._helper_llm.chat(messages=messages, tools=None)
            advice = response.get("content", "").strip()
            if advice:
                return (
                    f"⚠️ 停滞检测（{stuck_signal.pattern.value}）— 辅助 AI 建议：\n\n"
                    f"{advice}\n\n"
                    f"请按照上述建议立即调整策略。"
                )
        except Exception as e:
            logger.warning(f"[{self.name}] helper 咨询失败: {e}")
        return (
            f"⚠️ 停滞（{stuck_signal.pattern.value}）：{stuck_signal.description}\n"
            f"请立即：{stuck_signal.suggestion}"
        )

    def _diagnose_exhaustion(self) -> str:
        """分析迭代耗尽的原因，从 conversation_history 提取结构化诊断"""
        tool_calls_ok = 0
        tool_calls_err = 0
        errors = []
        has_file_write = False

        for msg in self.conversation_history:
            role = msg.get("role", "")
            content = str(msg.get("content", ""))

            if role == "assistant" and "tool_calls" in msg:
                for tc in msg.get("tool_calls", []):
                    fname = tc.get("function", {}).get("name", "")
                    if fname in ("write_file", "create_directory"):
                        has_file_write = True

            if role == "tool":
                if content.startswith("[错误]") or content.startswith("[超时]"):
                    tool_calls_err += 1
                    errors.append(content[:120])
                else:
                    tool_calls_ok += 1

        # 判断失败模式
        patterns = []
        if tool_calls_err > 0 and any("不在工作区" in e or "路径" in e for e in errors):
            patterns.append("路径错误（使用了绝对路径或越界路径）")
        if tool_calls_err > 0 and any("not found" in e.lower() or "not installed" in e.lower() for e in errors):
            patterns.append("环境依赖缺失")
        if not has_file_write:
            patterns.append("未执行任何文件写入（可能在探索/分析中耗尽迭代）")
        if tool_calls_ok == 0 and tool_calls_err == 0:
            patterns.append("LLM 未调用任何工具（可能理解偏差或 prompt 不清晰）")
        if not patterns:
            patterns.append("迭代预算不足以完成任务")

        phase_summary = ", ".join(f"{k}={v}" for k, v in self._phase_counts.items()) if self._phase_counts else "无"
        lines = [
            f"工具调用: {tool_calls_ok} 成功, {tool_calls_err} 失败",
            f"文件产出: {'有' if has_file_write else '无'}",
            f"阶段分布: {phase_summary}",
            f"失败模式: {'; '.join(patterns)}",
        ]
        if errors:
            lines.append(f"错误摘要: {errors[0]}")
            if len(errors) > 1:
                lines.append(f"  ...及另外 {len(errors)-1} 个错误")

        return "\n".join(lines)

    def _format_args(self, args: dict) -> str:
        parts = []
        for k, v in args.items():
            if isinstance(v, str) and len(v) > 50:
                v = v[:50] + "..."
            parts.append(f"{k}={repr(v)}")
        return ", ".join(parts)
