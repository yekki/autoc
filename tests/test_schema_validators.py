"""SubmitReportParams Pydantic validator 测试

覆盖: _coerce_pass / _coerce_quality_score / _coerce_json_string_to_list
以及 validate_tool_args 对 submit_test_report 的端到端容错。
"""

import pytest

from autoc.tools.schemas import SubmitReportParams, validate_tool_args


class TestCoercePass:
    """pass_ 字段的 bool coercion"""

    @pytest.mark.parametrize("input_val, expected", [
        (True, True),
        (False, False),
        (1, True),
        (0, False),
        ("true", True),
        ("True", True),
        ("TRUE", True),
        ("false", False),
        ("False", False),
        ("yes", True),
        ("no", False),
        ("pass", True),
        ("1", True),
        ("0", False),
        ("", False),
    ])
    def test_coerce_pass(self, input_val, expected):
        result = SubmitReportParams.model_validate({
            "pass": input_val, "summary": "test",
        })
        assert result.pass_ is expected


class TestCoerceQualityScore:
    """quality_score 字段的 int coercion"""

    @pytest.mark.parametrize("input_val, expected", [
        (8, 8),
        (8.5, 8),
        ("8", 8),
        (" 7 ", 7),
        ("high", 5),
        (None, 5),
        ([], 5),
        ({}, 5),
        ("", 5),
        (100, 10),
        (-5, 1),
        (0, 1),
        (11, 10),
        ("0", 1),
        ("15", 10),
    ])
    def test_coerce_quality_score(self, input_val, expected):
        result = SubmitReportParams.model_validate({
            "pass": True, "summary": "test", "quality_score": input_val,
        })
        assert result.quality_score == expected

    def test_default_when_omitted(self):
        result = SubmitReportParams.model_validate({
            "pass": True, "summary": "test",
        })
        assert result.quality_score == 5


class TestCoerceJsonStringToList:
    """list 字段的 JSON string coercion"""

    def test_json_string_to_list(self):
        result = SubmitReportParams.model_validate({
            "pass": True, "summary": "test",
            "test_files_created": '["a.py", "b.py"]',
        })
        assert result.test_files_created == ["a.py", "b.py"]

    def test_actual_list_passes_through(self):
        result = SubmitReportParams.model_validate({
            "pass": True, "summary": "test",
            "test_files_created": ["a.py"],
        })
        assert result.test_files_created == ["a.py"]

    def test_none_stays_none(self):
        result = SubmitReportParams.model_validate({
            "pass": True, "summary": "test",
        })
        assert result.test_files_created is None

    @pytest.mark.parametrize("null_val", ["null", "None", "N/A", "", "  ", "[]"])
    def test_null_string_coerced_to_empty_list(self, null_val):
        result = SubmitReportParams.model_validate({
            "pass": True, "summary": "test",
            "test_files_created": null_val,
        })
        assert result.test_files_created == []

    def test_invalid_json_string_passes_through(self):
        """非 JSON 字符串不崩溃（Pydantic 自己会报 validation error，被 validate_tool_args 兜底）"""
        cleaned = validate_tool_args("submit_test_report", {
            "pass": True, "summary": "test",
            "test_files_created": "not a json list",
        })
        assert isinstance(cleaned.get("test_files_created", ""), (list, str))

    def test_task_verification_json_string(self):
        result = SubmitReportParams.model_validate({
            "pass": True, "summary": "test",
            "task_verification": '[{"task_id": "T1", "passes": true}]',
        })
        assert len(result.task_verification) == 1
        assert result.task_verification[0].task_id == "T1"


class TestTaskVerificationOptional:
    """task_verification 改为 Optional 后的行为"""

    def test_omitted_is_none(self):
        result = SubmitReportParams.model_validate({
            "pass": True, "summary": "test",
        })
        assert result.task_verification is None

    def test_explicit_empty_list(self):
        result = SubmitReportParams.model_validate({
            "pass": True, "summary": "test", "task_verification": [],
        })
        assert result.task_verification == []


class TestValidateToolArgsE2E:
    """validate_tool_args 端到端容错"""

    def test_minimal_report(self):
        """仅必填字段（exclude_unset=True 不输出未传的默认值）"""
        cleaned = validate_tool_args("submit_test_report", {
            "pass": True, "summary": "done",
        })
        assert cleaned["pass"] is True
        assert cleaned["summary"] == "done"
        assert cleaned.get("quality_score", 5) == 5

    def test_all_fields_string_coerced(self):
        """所有字段以 LLM 常见的字符串形式传入"""
        cleaned = validate_tool_args("submit_test_report", {
            "pass": "true",
            "summary": "完成",
            "quality_score": "8",
            "task_verification": '[{"task_id": "T1", "passes": true}]',
            "test_files_created": '["test.py"]',
        })
        assert cleaned["pass"] is True
        assert cleaned["quality_score"] == 8
        assert isinstance(cleaned.get("task_verification"), list)
        assert isinstance(cleaned.get("test_files_created"), list)

    def test_completely_broken_args_fallback(self):
        """完全无法解析的参数不崩溃"""
        cleaned = validate_tool_args("submit_test_report", {
            "pass": [1, 2, 3],
            "summary": 12345,
        })
        assert isinstance(cleaned, dict)
