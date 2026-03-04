"""统一工具响应协议 — 所有工具返回值的标准信封结构

注意：当前 base.py 的 _handle_tool_call() 返回 str 而非 ToolResponse，
本模块中的 ToolResponse 类及工厂函数暂未在主流程中使用。
保留供未来重构使用（计划将工具返回值从 str 迁移到 ToolResponse）。

借鉴 MyCodeAgent 的 Universal Tool Response Protocol：
- 三态状态机：success / partial / error
- 六字段信封：status / data / text / stats / context / error
- text 三段论：结论 + 状态说明 + 下一步指引
"""

import json
import time
from enum import Enum
from typing import Any, Optional


class ToolStatus(str, Enum):
    """工具执行结果三态"""
    SUCCESS = "success"     # 完全成功，无截断、无回退
    PARTIAL = "partial"     # 可用但有折扣（截断 / 降级 / dry-run / 部分失败）
    ERROR = "error"         # 无法提供有效结果


class ErrorCode(str, Enum):
    """标准错误码体系"""
    NOT_FOUND = "NOT_FOUND"
    ACCESS_DENIED = "ACCESS_DENIED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    INVALID_PARAM = "INVALID_PARAM"
    TIMEOUT = "TIMEOUT"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    EXECUTION_ERROR = "EXECUTION_ERROR"
    IS_DIRECTORY = "IS_DIRECTORY"
    BINARY_FILE = "BINARY_FILE"
    CONFLICT = "CONFLICT"
    CIRCUIT_OPEN = "CIRCUIT_OPEN"


class ToolResponse:
    """统一工具响应对象

    Attributes:
        status: 三态状态
        data: 核心载荷（永远是 dict，不允许 None）
        text: 给 LLM 阅读的自然语言摘要
        stats: 运行统计（至少含 time_ms）
        context: 上下文回传（cwd、params_input、path_resolved 等）
        error: 仅 status=error 时存在 {code, message}
    """
    __slots__ = ("status", "data", "text", "stats", "context", "error")

    def __init__(
        self,
        status: ToolStatus,
        text: str,
        data: Optional[dict] = None,
        stats: Optional[dict] = None,
        context: Optional[dict] = None,
        error: Optional[dict] = None,
    ):
        self.status = status
        self.data = data or {}
        self.text = text
        self.stats = stats or {}
        self.context = context or {}
        self.error = error

    @property
    def is_error(self) -> bool:
        return self.status == ToolStatus.ERROR

    @property
    def is_success(self) -> bool:
        return self.status == ToolStatus.SUCCESS

    def to_dict(self) -> dict:
        d = {
            "status": self.status.value,
            "data": self.data,
            "text": self.text,
            "stats": self.stats,
            "context": self.context,
        }
        if self.error:
            d["error"] = self.error
        return d

    def serialize(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


# ==================== 工厂函数 ====================

def build_success(
    text: str,
    data: Optional[dict] = None,
    params_input: Any = None,
    time_ms: int = 0,
    **extra_context,
) -> ToolResponse:
    return ToolResponse(
        status=ToolStatus.SUCCESS,
        text=text,
        data=data,
        stats={"time_ms": time_ms},
        context={"params_input": params_input, **extra_context},
    )


def build_partial(
    text: str,
    data: Optional[dict] = None,
    params_input: Any = None,
    time_ms: int = 0,
    reason: str = "",
    **extra_context,
) -> ToolResponse:
    stats: dict[str, Any] = {"time_ms": time_ms}
    if reason:
        stats["partial_reason"] = reason
    return ToolResponse(
        status=ToolStatus.PARTIAL,
        text=text,
        data=data,
        stats=stats,
        context={"params_input": params_input, **extra_context},
    )


def build_error(
    code: ErrorCode,
    message: str,
    params_input: Any = None,
    time_ms: int = 0,
) -> ToolResponse:
    return ToolResponse(
        status=ToolStatus.ERROR,
        text=message,
        data={},
        stats={"time_ms": time_ms},
        context={"params_input": params_input},
        error={"code": code.value, "message": message},
    )


# ==================== 字符串结果 → ToolResponse 转换 ====================

_ERROR_PREFIXES = ("[错误]", "[超时]", "[安全]")
_PARTIAL_PREFIXES = ("[跳过]",)
_TRUNCATION_MARKERS = ("已截断", "输出过长", "仅显示前")

# 旧前缀 → ErrorCode 映射
_PREFIX_TO_ERROR_CODE: dict[str, ErrorCode] = {
    "[错误] 文件不存在": ErrorCode.NOT_FOUND,
    "[错误] 不是目录": ErrorCode.IS_DIRECTORY,
    "[错误] 路径": ErrorCode.ACCESS_DENIED,
    "[超时]": ErrorCode.TIMEOUT,
    "[安全]": ErrorCode.ACCESS_DENIED,
}


def normalize_legacy_result(
    tool_name: str,
    raw_result: str,
    params_input: Any = None,
    elapsed_ms: int = 0,
) -> ToolResponse:
    """将字符串结果规范化为 ToolResponse

    检测规则：
    - [错误] / [超时] / [安全] 前缀 → ERROR
    - [跳过] 前缀 → PARTIAL
    - 含截断标记 → PARTIAL
    - 其他 → SUCCESS
    """
    # 错误检测
    for prefix in _ERROR_PREFIXES:
        if raw_result.startswith(prefix):
            code = ErrorCode.INTERNAL_ERROR
            for pattern, mapped_code in _PREFIX_TO_ERROR_CODE.items():
                if raw_result.startswith(pattern):
                    code = mapped_code
                    break
            return build_error(code, raw_result, params_input, elapsed_ms)

    # 部分成功检测
    is_partial = False
    partial_reason = ""

    for prefix in _PARTIAL_PREFIXES:
        if raw_result.startswith(prefix):
            is_partial = True
            partial_reason = "skipped"
            break

    if not is_partial:
        for marker in _TRUNCATION_MARKERS:
            if marker in raw_result:
                is_partial = True
                partial_reason = "truncated"
                break

    if is_partial:
        return build_partial(
            raw_result, params_input=params_input,
            time_ms=elapsed_ms, reason=partial_reason,
        )

    return build_success(raw_result, params_input=params_input, time_ms=elapsed_ms)
