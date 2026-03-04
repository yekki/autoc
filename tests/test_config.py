"""测试 config.py — 配置加载 + 项目级配置合并"""

import os
import yaml

from autoc.config import _deep_merge, load_project_config


class TestDeepMerge:
    def test_simple_merge(self):
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        assert _deep_merge(base, override) == {"a": 1, "b": 3, "c": 4}

    def test_nested_merge(self):
        base = {"llm": {"model": "old", "timeout": 30}}
        override = {"llm": {"model": "new"}}
        result = _deep_merge(base, override)
        assert result["llm"]["model"] == "new"
        assert result["llm"]["timeout"] == 30

    def test_override_non_dict(self):
        base = {"a": {"b": 1}}
        override = {"a": "flat"}
        result = _deep_merge(base, override)
        assert result["a"] == "flat"


class TestProjectConfig:
    def test_no_config_file(self, tmp_path):
        result = load_project_config(str(tmp_path))
        assert result == {}

    def test_loads_project_yaml(self, tmp_path):
        cfg_file = tmp_path / ".autoc-project.yaml"
        cfg_file.write_text(yaml.dump({"llm": {"preset": "kimi"}}))
        result = load_project_config(str(tmp_path))
        assert result["llm"]["preset"] == "kimi"

    def test_invalid_yaml(self, tmp_path):
        cfg_file = tmp_path / ".autoc-project.yaml"
        cfg_file.write_text("}{invalid")
        result = load_project_config(str(tmp_path))
        assert result == {}
