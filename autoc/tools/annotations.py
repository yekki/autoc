"""Tool Annotations — 工具元数据协议

参考 OpenHands ToolAnnotations 设计：
- 每个工具携带安全元数据（risk_level, readonly, confirmation）
- Security Analyzer 基于 annotations 做零开销安全评估
- Agent 不感知 annotations，只有 Orchestrator/SecurityAnalyzer 消费

risk_level 分级：
- none: 无风险（read_file, list_files 等只读操作）
- low: 低风险（write_file, create_directory 等受限写操作）
- medium: 中风险（git_commit, format_code 等可恢复操作）
- high: 高风险（execute_command 等不可预知行为）
- critical: 极高风险（预留，当前系统不应出现）
"""

from dataclasses import dataclass
from enum import Enum


class RiskLevel(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ConfirmAction(str, Enum):
    """Security Analyzer 对工具调用的处置策略"""
    ALLOW = "allow"
    WARN = "warn"
    CONFIRM = "confirm"
    DENY = "deny"


@dataclass(frozen=True)
class ToolAnnotation:
    """单个工具的安全元数据"""
    risk_level: RiskLevel = RiskLevel.NONE
    readonly: bool = False
    confirmation: ConfirmAction = ConfirmAction.ALLOW
    category: str = ""
    mutates_workspace: bool = False
    network_access: bool = False
    description: str = ""


# 内置工具的 annotations 注册表
TOOL_ANNOTATIONS: dict[str, ToolAnnotation] = {
    # ---- 文件操作 ----
    "read_file": ToolAnnotation(
        risk_level=RiskLevel.NONE, readonly=True,
        category="file", description="读取文件内容",
    ),
    "write_file": ToolAnnotation(
        risk_level=RiskLevel.LOW, mutates_workspace=True,
        category="file", description="写入文件（全量覆盖）",
    ),
    "edit_file": ToolAnnotation(
        risk_level=RiskLevel.LOW, mutates_workspace=True,
        category="file", description="精确编辑文件（old_str → new_str 替换）",
    ),
    "create_directory": ToolAnnotation(
        risk_level=RiskLevel.LOW, mutates_workspace=True,
        category="file", description="创建目录",
    ),
    "list_files": ToolAnnotation(
        risk_level=RiskLevel.NONE, readonly=True,
        category="file", description="列出目录内容",
    ),
    "glob_files": ToolAnnotation(
        risk_level=RiskLevel.NONE, readonly=True,
        category="file", description="按 glob 模式匹配文件路径",
    ),
    "search_in_files": ToolAnnotation(
        risk_level=RiskLevel.NONE, readonly=True,
        category="file", description="搜索文件内容",
    ),

    # ---- Shell ----
    "execute_command": ToolAnnotation(
        risk_level=RiskLevel.HIGH, mutates_workspace=True,
        network_access=True, confirmation=ConfirmAction.WARN,
        category="shell", description="执行 Shell 命令（Docker 沙箱内）",
    ),
    "send_input": ToolAnnotation(
        risk_level=RiskLevel.MEDIUM, mutates_workspace=True,
        category="shell", description="向交互式进程发送输入",
    ),

    # ---- Git ----
    "git_diff": ToolAnnotation(
        risk_level=RiskLevel.NONE, readonly=True,
        category="git", description="查看 Git 变更",
    ),
    "git_log": ToolAnnotation(
        risk_level=RiskLevel.NONE, readonly=True,
        category="git", description="查看提交历史",
    ),
    "git_status": ToolAnnotation(
        risk_level=RiskLevel.NONE, readonly=True,
        category="git", description="查看 Git 状态",
    ),

    # ---- 代码质量 ----
    "format_code": ToolAnnotation(
        risk_level=RiskLevel.MEDIUM, mutates_workspace=True,
        category="quality", description="格式化代码",
    ),
    "lint_code": ToolAnnotation(
        risk_level=RiskLevel.NONE, readonly=True,
        category="quality", description="代码静态检查",
    ),

    # ---- 报告 ----
    "submit_test_report": ToolAnnotation(
        risk_level=RiskLevel.NONE,
        category="report", description="提交验收报告",
    ),
    "submit_critique": ToolAnnotation(
        risk_level=RiskLevel.NONE,
        category="report", description="提交评审报告",
    ),

    "ask_helper": ToolAnnotation(
        risk_level=RiskLevel.NONE, readonly=True,
        network_access=True,
        category="consult", description="向辅助 AI 咨询",
    ),

    # ---- 思考工具 ----
    "think": ToolAnnotation(
        risk_level=RiskLevel.NONE, readonly=True,
        category="reasoning", description="结构化思考，不执行任何操作",
    ),

    # ---- Git 扩展 ----
    "git_commit": ToolAnnotation(
        risk_level=RiskLevel.MEDIUM, mutates_workspace=True,
        category="git", description="提交 Git 变更",
    ),
    "git_rollback": ToolAnnotation(
        risk_level=RiskLevel.HIGH, mutates_workspace=True,
        confirmation=ConfirmAction.WARN,
        category="git", description="回滚 Git 到指定 commit",
    ),
}

def get_annotation(tool_name: str) -> ToolAnnotation:
    """获取工具的 annotation，未注册则返回保守默认值"""
    if tool_name in TOOL_ANNOTATIONS:
        return TOOL_ANNOTATIONS[tool_name]
    return ToolAnnotation(
        risk_level=RiskLevel.MEDIUM,
        confirmation=ConfirmAction.WARN,
        description=f"未注册工具: {tool_name}",
    )


def register_annotation(tool_name: str, annotation: ToolAnnotation) -> None:
    """运行时注册工具 annotation"""
    TOOL_ANNOTATIONS[tool_name] = annotation


def is_readonly(tool_name: str) -> bool:
    """快速判断工具是否只读"""
    return get_annotation(tool_name).readonly


def is_high_risk(tool_name: str) -> bool:
    """快速判断工具是否高风险"""
    return get_annotation(tool_name).risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)
