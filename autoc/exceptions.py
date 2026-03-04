"""AutoC 自定义异常体系

层级:
    AutoCError
    ├── ConfigError          — 配置加载/解析错误
    ├── LLMError             — LLM 调用相关错误
    │   ├── LLMAuthError     — API Key 无效或缺失
    │   ├── LLMRateLimitError— 速率限制
    │   └── LLMTimeoutError  — 调用超时
    ├── ToolError            — 工具执行错误
    │   ├── FileToolError    — 文件操作错误
    │   └── ShellToolError   — Shell 命令执行错误
    ├── SandboxError         — Docker 沙箱错误
    ├── PreviewError         — 预览启动/管理错误
    ├── AgentError           — Agent 执行错误
    └── OrchestrationError   — 编排流程错误
"""


class AutoCError(Exception):
    """AutoC 基础异常"""

    def __init__(self, message: str = "", detail: str = ""):
        self.detail = detail
        super().__init__(message)


# ==================== 配置 ====================

class ConfigError(AutoCError):
    """配置加载/解析错误"""
    pass


# ==================== LLM ====================

class LLMError(AutoCError):
    """LLM 调用相关错误"""
    pass


class LLMAuthError(LLMError):
    """API Key 无效或缺失"""
    pass


class LLMRateLimitError(LLMError):
    """速率限制"""
    pass


class LLMTimeoutError(LLMError):
    """LLM 调用超时"""
    pass


# ==================== 工具 ====================

class ToolError(AutoCError):
    """工具执行错误"""
    pass


class FileToolError(ToolError):
    """文件操作错误"""
    pass


class ShellToolError(ToolError):
    """Shell 命令执行错误"""
    pass


# ==================== 沙箱 ====================

class SandboxError(AutoCError):
    """Docker 沙箱错误"""
    pass


# ==================== 预览 ====================

class PreviewError(AutoCError):
    """预览启动/管理错误"""
    pass


# ==================== Agent ====================

class AgentError(AutoCError):
    """Agent 执行错误"""
    pass


class AgentStuckError(AgentError):
    """Agent 持续停滞，需要 Orchestrator 介入。

    当 StuckDetector 连续检测到 severity >= 3 的停滞信号时抛出，
    由 IterativeLoop 捕获并触发任务级决策（retry / simplify / skip）。
    """

    def __init__(self, signal=None, message: str = ""):
        self.signal = signal  # StuckSignal 实例
        desc = message or (signal.description if signal else "Agent stuck in loop")
        super().__init__(desc)


# ==================== 编排 ====================

class OrchestrationError(AutoCError):
    """编排流程错误"""
    pass
