"""Pydantic 工具参数模型 — 所有工具 schema 的唯一权威来源

工具定义流程：
1. 用 Pydantic 模型定义参数（类型、验证、描述）
2. `tool_schema()` 自动生成 OpenAI Function Calling 格式的 dict
3. FILE_TOOLS / SHELL_TOOLS 等全局列表由模型自动构建

好处：
- 类型安全：参数在 dispatch 前已通过 Pydantic 验证
- DRY：schema 定义一次，JSON 自动生成
- IDE 友好：补全、重构、跳转
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Optional

import json

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger("autoc.tools.schemas")

# 与 autoc/core/runtime/action_server.py 的 ACTION_SERVER_DEFAULT_PORT 保持同步
# action_server.py 在容器内独立运行，不能 import 此模块，必须各自定义
ACTION_SERVER_DEFAULT_PORT = 23456


# ==================== 基础设施 ====================

def _resolve_refs(schema: dict, defs: dict) -> dict:
    """递归展开 Pydantic v2 生成的 $ref 引用，确保 LLM Provider 兼容"""
    if isinstance(schema, dict):
        if "$ref" in schema:
            ref_name = schema["$ref"].split("/")[-1]
            resolved = defs.get(ref_name, {})
            return _resolve_refs(resolved, defs)
        return {k: _resolve_refs(v, defs) for k, v in schema.items()}
    if isinstance(schema, list):
        return [_resolve_refs(item, defs) for item in schema]
    return schema


def _clean_schema(schema: Any) -> Any:
    """递归清理 Pydantic 生成的 title 元数据，保留实际字段名和 LLM 需要的描述

    区分逻辑：
    - schema 描述节点（含 type/anyOf/allOf/oneOf/enum）中的 "title" 是 Pydantic 元数据 → 删除
    - "properties" 容器中的 "title" key 是模型字段名（如 BugReport.title）→ 保留
    """
    if isinstance(schema, dict):
        _SCHEMA_INDICATORS = {"type", "anyOf", "allOf", "oneOf", "enum", "$ref"}
        is_schema_node = bool(schema.keys() & _SCHEMA_INDICATORS)
        cleaned = {}
        for k, v in schema.items():
            if k == "title" and is_schema_node and isinstance(v, str):
                continue
            cleaned[k] = _clean_schema(v)
        return cleaned
    if isinstance(schema, list):
        return [_clean_schema(item) for item in schema]
    return schema


def tool_schema(
    name: str,
    description: str,
    params_model: type[BaseModel],
) -> dict:
    """从 Pydantic 模型生成 OpenAI Function Calling 格式的工具定义

    自动展开 $defs/$ref 引用（嵌套模型），确保 OpenAI/Anthropic 等 Provider 兼容。
    """
    json_schema = params_model.model_json_schema()
    defs = json_schema.pop("$defs", {})

    resolved = _resolve_refs(json_schema, defs)
    cleaned = _clean_schema(resolved)
    properties = cleaned.get("properties", {})
    required = cleaned.get("required", [])

    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


# ==================== 文件工具参数模型 ====================

class ReadFileParams(BaseModel):
    path: str = Field(description="文件路径（相对于工作区）")
    start_line: Optional[int] = Field(None, description="起始行号（1-based，可选）")
    end_line: Optional[int] = Field(None, description="结束行号（1-based，闭区间，可选）")


class WriteFileParams(BaseModel):
    path: str = Field(description="文件路径（相对于工作区）")
    content: str = Field(description="要写入的完整文件内容")


class EditFileParams(BaseModel):
    path: str = Field(description="文件路径（相对于工作区）")
    old_str: str = Field(description="要替换的原始文本（必须与文件内容完全一致，包括缩进）")
    new_str: str = Field(description="替换后的新文本")


class CreateDirectoryParams(BaseModel):
    path: str = Field(description="目录路径（相对于工作区）")


class ListFilesParams(BaseModel):
    path: str = Field(".", description="目录路径（相对于工作区），默认为工作区根目录")
    recursive: bool = Field(False, description="是否递归列出子目录中的文件")


class GlobFilesParams(BaseModel):
    pattern: str = Field(description="glob 模式，如 **/*.py, src/**/*.ts, *.md")


class SearchInFilesParams(BaseModel):
    keyword: str = Field(description="要搜索的关键词")
    file_pattern: str = Field("*.*", description="文件匹配模式，如 *.py, *.js")


# ==================== Shell 工具参数模型 ====================

class ExecuteCommandParams(BaseModel):
    command: str = Field(description="要执行的 Shell 命令（使用相对路径，不要 cd 到绝对路径）")
    timeout: int = Field(120, description="命令超时时间（秒），默认120秒。长时间构建可设更大值。")


class SendInputParams(BaseModel):
    text: str = Field(description="要发送的输入文本（如 'y\\n' 表示输入 y 并回车）")


# ==================== Meta 工具参数模型 ====================

class ThinkParams(BaseModel):
    thought: str = Field(description="你的思考内容（分析、推理、计划等）")


# ==================== 验收报告参数模型 ====================

class BugSeverity(str, Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"


class BugReport(BaseModel):
    title: str
    severity: BugSeverity
    description: Optional[str] = None
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    root_cause: Optional[str] = None
    suggested_fix: Optional[str] = None


class TaskVerification(BaseModel):
    task_id: str
    passes: bool
    verification_details: Optional[str] = None


class TestResult(BaseModel):
    test_name: Optional[str] = None
    passed: Optional[bool] = None
    output: Optional[str] = None
    error: Optional[str] = None


class SubmitReportParams(BaseModel):
    """验收报告参数。

    设计原则：对 LLM 输出宽容（coerce string→bool/int/list），
    对消费端严格（validated dict）。参考 OpenHands finish() 的简洁性，
    仅 pass/summary/quality_score 三个标量为必填，其余结构化字段均可选。
    """
    pass_: bool = Field(alias="pass", description="整体是否通过（只有 critical/high bug 才为 false）")
    summary: str = Field(description="实现与验证总结（中文）")
    quality_score: int = Field(5, description="质量评分 1-10")
    task_verification: Optional[list[TaskVerification]] = None
    bugs: Optional[list[BugReport]] = None
    test_results: Optional[list[TestResult]] = None
    test_files_created: Optional[list[str]] = None

    model_config = {"populate_by_name": True}

    @field_validator("pass_", mode="before")
    @classmethod
    def _coerce_pass(cls, v: Any) -> bool:
        if isinstance(v, str):
            return v.strip().lower() in ("true", "1", "yes", "pass")
        return bool(v)

    @field_validator("quality_score", mode="before")
    @classmethod
    def _coerce_quality_score(cls, v: Any) -> int:
        if isinstance(v, (int, float)):
            val = int(v)
        elif isinstance(v, str):
            try:
                val = int(v.strip())
            except (ValueError, TypeError):
                return 5
        else:
            return 5
        return max(1, min(val, 10))

    @field_validator("task_verification", "bugs", "test_results", "test_files_created", mode="before")
    @classmethod
    def _coerce_json_string_to_list(cls, v: Any) -> Any:
        """LLM 有时将 list 参数序列化为 JSON 字符串或空值表示，自动解析。"""
        if isinstance(v, str):
            v = v.strip()
            if not v or v.lower() in ("null", "none", "n/a", "[]"):
                return []
            if v.startswith("["):
                try:
                    return json.loads(v)
                except json.JSONDecodeError:
                    pass
        return v


# ==================== Helper 工具参数模型 ====================

class AskHelperParams(BaseModel):
    question: str = Field(description="你的具体问题")
    task_id: str = Field("", description="相关的任务 ID（可选）")


# ==================== 自动构建工具列表 ====================

FILE_TOOLS = [
    tool_schema("read_file", "读取指定文件的内容。支持可选的行号范围，避免读取整个大文件。", ReadFileParams),
    tool_schema("write_file", "创建或覆盖写入文件。需要提供完整的文件内容。", WriteFileParams),
    tool_schema("edit_file", "精确编辑文件：查找 old_str 并替换为 new_str。只需传递变更片段，比 write_file 全量覆盖大幅节省 Token。old_str 必须在文件中唯一匹配。", EditFileParams),
    tool_schema("create_directory", "创建目录（包括所有父目录）", CreateDirectoryParams),
    tool_schema("list_files", "列出目录中的文件和子目录", ListFilesParams),
    tool_schema("glob_files", "按 glob 模式匹配文件路径。支持 ** 递归匹配，例如 **/*.py 查找所有 Python 文件。", GlobFilesParams),
    tool_schema("search_in_files", "在项目文件中搜索关键词", SearchInFilesParams),
]

SHELL_TOOLS = [
    tool_schema("execute_command", "在项目工作区中执行 Shell 命令。用于运行测试、安装依赖、构建项目等。遇到 command not found 可自行 apt-get install。", ExecuteCommandParams),
]

SEND_INPUT_TOOL = tool_schema("send_input", "向容器内运行中的交互式进程发送输入。需要 Action Server 支持（持久 bash 通道）。", SendInputParams)

THINK_TOOL = tool_schema("think", "结构化思考工具。用于在执行操作前梳理思路、分析问题、制定策略。不会执行任何实际操作，不消耗资源。", ThinkParams)

SUBMIT_REPORT_TOOL = tool_schema("submit_test_report", "提交结构化验收报告。完成所有实现和验证后，必须调用此工具提交最终报告。", SubmitReportParams)

ASK_HELPER_TOOL = tool_schema("ask_helper", "向辅助 AI 请教技术问题", AskHelperParams)


# ==================== 参数验证辅助 ====================

TOOL_PARAM_MODELS: dict[str, type[BaseModel]] = {
    "read_file": ReadFileParams,
    "write_file": WriteFileParams,
    "edit_file": EditFileParams,
    "create_directory": CreateDirectoryParams,
    "list_files": ListFilesParams,
    "glob_files": GlobFilesParams,
    "search_in_files": SearchInFilesParams,
    "execute_command": ExecuteCommandParams,
    "send_input": SendInputParams,
    "think": ThinkParams,
    "submit_test_report": SubmitReportParams,
    "ask_helper": AskHelperParams,
}


def validate_tool_args(tool_name: str, args: dict) -> dict:
    """用 Pydantic 模型验证工具参数，返回清洗后的 dict。

    未注册的工具名直接放行。
    验证失败时记录警告并放行原始参数（容错优先）。
    """
    model_cls = TOOL_PARAM_MODELS.get(tool_name)
    if model_cls is None:
        return args
    try:
        instance = model_cls.model_validate(args)
        # by_alias: SubmitReportParams 的 pass_ → pass
        # exclude_none: 排除值为 None 的字段，但保留有默认值的字段（避免 exclude_unset 丢失默认值）
        return instance.model_dump(by_alias=True, exclude_none=True)
    except Exception as e:
        logger.warning(f"工具参数验证失败 [{tool_name}]: {e}，使用原始参数")
        return args  # 降级：验证失败时使用原始参数，handler 层负责最终检验
