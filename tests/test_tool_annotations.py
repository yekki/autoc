"""Tool Annotations 单元测试"""
import pytest
from autoc.tools.annotations import (
    ToolAnnotation, RiskLevel, ConfirmAction,
    get_annotation, register_annotation, is_readonly, is_high_risk,
    TOOL_ANNOTATIONS,
)


class TestToolAnnotation:
    """ToolAnnotation 数据结构"""

    def test_default_values(self):
        ann = ToolAnnotation()
        assert ann.risk_level == RiskLevel.NONE
        assert ann.readonly is False
        assert ann.confirmation == ConfirmAction.ALLOW
        assert ann.mutates_workspace is False

    def test_frozen(self):
        ann = ToolAnnotation()
        with pytest.raises(AttributeError):
            ann.risk_level = RiskLevel.HIGH

    def test_custom_values(self):
        ann = ToolAnnotation(
            risk_level=RiskLevel.HIGH,
            readonly=False,
            mutates_workspace=True,
            network_access=True,
            description="test",
        )
        assert ann.risk_level == RiskLevel.HIGH
        assert ann.network_access is True


class TestGetAnnotation:
    """get_annotation 查询逻辑"""

    def test_builtin_tool(self):
        ann = get_annotation("read_file")
        assert ann.risk_level == RiskLevel.NONE
        assert ann.readonly is True
        assert ann.category == "file"

    def test_shell_tool(self):
        ann = get_annotation("execute_command")
        assert ann.risk_level == RiskLevel.HIGH
        assert ann.mutates_workspace is True
        assert ann.network_access is True

    def test_unknown_slash_tool(self):
        ann = get_annotation("filesystem/read_file")
        assert ann.risk_level == RiskLevel.MEDIUM
        assert ann.confirmation == ConfirmAction.WARN

    def test_unknown_tool(self):
        ann = get_annotation("totally_unknown_tool")
        assert ann.risk_level == RiskLevel.MEDIUM
        assert ann.confirmation == ConfirmAction.WARN

    def test_write_file(self):
        ann = get_annotation("write_file")
        assert ann.risk_level == RiskLevel.LOW
        assert ann.mutates_workspace is True
        assert ann.readonly is False


class TestHelpers:
    """便捷函数"""

    def test_is_readonly(self):
        assert is_readonly("read_file") is True
        assert is_readonly("list_files") is True
        assert is_readonly("write_file") is False
        assert is_readonly("execute_command") is False

    def test_is_high_risk(self):
        assert is_high_risk("execute_command") is True
        assert is_high_risk("read_file") is False
        assert is_high_risk("write_file") is False

    def test_register_annotation(self):
        register_annotation("my_custom_tool", ToolAnnotation(
            risk_level=RiskLevel.LOW, readonly=True,
        ))
        ann = get_annotation("my_custom_tool")
        assert ann.risk_level == RiskLevel.LOW
        assert ann.readonly is True
        # 清理
        TOOL_ANNOTATIONS.pop("my_custom_tool", None)


class TestBuiltinAnnotationsCompleteness:
    """确保所有已知内置工具都有 annotation"""

    EXPECTED_TOOLS = [
        "read_file", "write_file", "create_directory", "list_files",
        "search_in_files", "execute_command", "git_diff", "git_log",
        "git_status", "format_code", "lint_code",
    ]

    def test_all_builtin_tools_annotated(self):
        for tool_name in self.EXPECTED_TOOLS:
            ann = get_annotation(tool_name)
            assert ann.risk_level is not None, f"{tool_name} 缺少 annotation"
            assert tool_name in TOOL_ANNOTATIONS, f"{tool_name} 未在 TOOL_ANNOTATIONS 中注册"
