"""PromptEngine 测试"""

import pytest
from pathlib import Path


class TestPromptEngine:
    def test_render_code_act_agent(self):
        from autoc.prompts import PromptEngine
        engine = PromptEngine()
        result = engine.render("code_act_agent", mirror_section="", missing_tools_hint="")
        assert "CodeActAgent" in result
        assert "编码→验证→修复" in result

    def test_render_critique(self):
        from autoc.prompts import PromptEngine
        engine = PromptEngine()
        result = engine.render("critique", pass_threshold=85)
        assert "85" in result
        assert "评审维度" in result

    def test_render_planner(self):
        from autoc.prompts import PromptEngine
        engine = PromptEngine()
        result = engine.render("planner")
        assert "项目规划者" in result
        assert "json" in result.lower()

    def test_render_with_variables(self):
        from autoc.prompts import PromptEngine
        engine = PromptEngine()
        result = engine.render("code_act_agent", mirror_section="MIRROR_TEST_TOKEN", missing_tools_hint="")
        assert "MIRROR_TEST_TOKEN" in result

    def test_missing_template_returns_empty(self):
        from autoc.prompts import PromptEngine
        engine = PromptEngine()
        assert engine.render("nonexistent_template") == ""

    def test_has_template(self):
        from autoc.prompts import PromptEngine
        engine = PromptEngine()
        assert engine.has_template("code_act_agent")
        assert engine.has_template("critique")
        assert engine.has_template("planner")
        assert not engine.has_template("nonexistent")

    def test_list_templates(self):
        from autoc.prompts import PromptEngine
        engine = PromptEngine()
        templates = engine.list_templates()
        assert "code_act_agent" in templates
        assert "critique" in templates
        assert "planner" in templates

    def test_custom_template_dir(self, tmp_path):
        from autoc.prompts import PromptEngine
        custom = tmp_path / "custom_test.j2"
        custom.write_text("Hello {{ name }}")
        engine = PromptEngine(custom_dirs=[str(tmp_path)])
        result = engine.render("custom_test", name="World")
        assert result == "Hello World"

    def test_custom_overrides_builtin(self, tmp_path):
        """自定义目录优先级高于内置目录"""
        from autoc.prompts import PromptEngine
        override = tmp_path / "code_act_agent.j2"
        override.write_text("CUSTOM_OVERRIDE")
        engine = PromptEngine(custom_dirs=[str(tmp_path)])
        result = engine.render("code_act_agent")
        assert result == "CUSTOM_OVERRIDE"

    def test_few_shot_include(self):
        from autoc.prompts import PromptEngine
        engine = PromptEngine(enable_few_shot=True)
        result = engine.render("code_act_agent", mirror_section="", missing_tools_hint="")
        assert "Few-Shot" in result or "工具使用示例" in result

    def test_few_shot_disabled(self):
        from autoc.prompts import PromptEngine
        engine = PromptEngine(enable_few_shot=False)
        result = engine.render("code_act_agent", mirror_section="", missing_tools_hint="")
        assert "Few-Shot" not in result
