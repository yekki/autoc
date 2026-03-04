"""测试 prd_import.py — PRD 文档导入"""

import json
import os
import pytest

from autoc.core.project.prd_import import (
    detect_format,
    build_import_prompt,
    read_prd_file,
    SUPPORTED_EXTENSIONS,
)


class TestReadPRDFile:
    def test_read_markdown(self, tmp_path):
        md = tmp_path / "req.md"
        md.write_text("# 需求\n- 功能A", encoding="utf-8")
        content = read_prd_file(str(md))
        assert "功能A" in content

    def test_read_json(self, tmp_path):
        jf = tmp_path / "plan.json"
        jf.write_text('{"tasks": []}', encoding="utf-8")
        content = read_prd_file(str(jf))
        assert "tasks" in content

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            read_prd_file("/nonexistent/file.md")

    def test_empty_file(self, tmp_path):
        empty = tmp_path / "empty.md"
        empty.write_text("", encoding="utf-8")
        with pytest.raises(ValueError, match="文件为空"):
            read_prd_file(str(empty))


class TestDetectFormat:
    def test_json_format(self):
        assert detect_format('{"key": "val"}', ".json") == "json"

    def test_markdown_format(self):
        assert detect_format("# Title\ncontent", ".md") == "markdown"

    def test_text_format(self):
        assert detect_format("plain text", ".txt") == "text"

    def test_yaml_format(self):
        assert detect_format("key: value", ".yaml") == "yaml"


class TestBuildImportPrompt:
    def test_contains_content(self):
        prompt = build_import_prompt("需求内容", "markdown", "my-project")
        assert "需求内容" in prompt
        assert "my-project" in prompt

    def test_no_project_name(self):
        prompt = build_import_prompt("内容", "text")
        assert "自动生成" in prompt
