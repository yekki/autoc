"""工具注册表 — 统一管理 Agent 可用工具

提供工具的注册、查询、描述生成和运行时分发。

核心能力:
- register_handler(): 注册工具名到可调用处理函数的映射
- dispatch(): 根据工具名分发调用（安全检查 → 内置 → 报错）
- format_for_prompt(): 生成工具描述文本，供 Agent prompt 构建
"""

import logging
import time
from typing import Any, Callable, Optional, TYPE_CHECKING

from autoc.exceptions import ToolError
from autoc.tools.protocol import ToolResponse, normalize_legacy_result
from autoc.tools.schemas import validate_tool_args

if TYPE_CHECKING:
    from autoc.core.security.analyzer import SecurityAnalyzer

logger = logging.getLogger("autoc.tools.registry")

ToolHandler = Callable[[dict[str, Any]], str]


class ToolRegistry:
    """统一工具注册表 — 注册 + 查询 + 运行时分发

    用法:
        registry = ToolRegistry()
        registry.register_handler("read_file", lambda args: file_ops.read_file(args["path"]))
        result = registry.dispatch("read_file", {"path": "main.py"})
    """

    def __init__(self, workspace_dir: str = ""):
        self._handlers: dict[str, ToolHandler] = {}
        self._descriptions: dict[str, str] = {}
        self._categories: dict[str, str] = {}
        self._workspace_dir: str = workspace_dir
        self._security: Optional["SecurityAnalyzer"] = None
        self.last_response: Optional[ToolResponse] = None

    def set_security_analyzer(self, analyzer: "SecurityAnalyzer"):
        """注入安全评估器，dispatch 前自动评估"""
        self._security = analyzer

    def register_handler(
        self,
        name: str,
        handler: ToolHandler,
        category: str = "",
        description: str = "",
    ):
        """注册工具处理函数

        Args:
            name: 工具名称（如 "read_file"）
            handler: 接受 dict 参数、返回 str 的可调用对象
            category: 工具分类（file / shell / git / quality / mcp）
            description: 工具描述（用于 prompt 注入）
        """
        self._handlers[name] = handler
        if category:
            self._categories[name] = category
        if description:
            self._descriptions[name] = description

    def unregister(self, name: str):
        """注销工具"""
        self._handlers.pop(name, None)
        self._descriptions.pop(name, None)
        self._categories.pop(name, None)

    def has(self, name: str) -> bool:
        return name in self._handlers

    def list_names(self, category: str | None = None) -> list[str]:
        if category:
            return [n for n, c in self._categories.items() if c == category]
        return list(self._handlers.keys())

    def dispatch(self, name: str, arguments: dict[str, Any]) -> str:
        """分发工具调用: 安全检查 → 内置 → ToolError

        内部使用 ToolResponse 协议做状态标注（success/partial/error），
        对外返回 str。最后一次调用的 ToolResponse 保存在 last_response 属性。
        """
        # 0) Pydantic 参数验证 — 类型安全 + 默认值填充
        arguments = validate_tool_args(name, arguments)

        # 1) 安全检查 — 零 LLM 开销，纯规则引擎
        if self._security:
            decision = self._security.evaluate(name, arguments)
            if not decision.allowed:
                logger.warning(f"安全拦截: {name} — {decision.reason}")
                return f"[安全] 拒绝执行: {decision.reason}"

        t0 = time.monotonic()

        if name not in self._handlers:
            registered = list(self._handlers.keys())
            logger.warning(f"工具分发失败: '{name}' 不在已注册列表中: {registered}")
            raise ToolError(f"未知工具: {name}")

        raw_result = self._handlers[name](arguments)

        elapsed_ms = int((time.monotonic() - t0) * 1000)
        self.last_response: ToolResponse = normalize_legacy_result(
            name, raw_result, params_input=arguments, elapsed_ms=elapsed_ms,
        )
        return raw_result

    def format_for_prompt(self, categories: list[str] | None = None) -> str:
        """生成工具描述文本，用于注入 Agent prompt"""
        lines = ["可用工具:"]
        names = self.list_names()
        if categories:
            names = [n for n in names if self._categories.get(n) in categories]
        for n in names:
            desc = self._descriptions.get(n, "")
            cat = self._categories.get(n, "")
            suffix = f" [{cat}]" if cat else ""
            lines.append(f"  - {n}: {desc}{suffix}")
        return "\n".join(lines)
