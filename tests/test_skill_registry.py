"""Skill Registry 单元测试"""
import os
import tempfile
import pytest
from autoc.core.skill.registry import SkillRegistry, Skill, SkillType


class TestSkill:
    """Skill 数据结构"""

    def test_matches_by_role_and_tags(self):
        """角色 + 技术栈标签匹配"""
        s = Skill(
            name="test", type=SkillType.INLINE, content="x",
            tags=["python", "flask"], agent_roles=["main"],
        )
        assert s.matches(["python"], "main") is True
        assert s.matches(["python"], "helper") is False
        assert s.matches(["java"], "main") is False

    def test_matches_no_tags(self):
        """无 tags 的 Skill 匹配所有技术栈"""
        s = Skill(name="test", type=SkillType.INLINE, content="x")
        assert s.matches(["anything"], "main") is True


class TestSkillRegistry:
    """SkillRegistry 注册和匹配"""

    def test_register_and_match(self):
        reg = SkillRegistry()
        reg.register(Skill(
            name="py-hints", type=SkillType.INLINE,
            content="Use type hints", tags=["python"],
        ))
        reg.register(Skill(
            name="js-lint", type=SkillType.INLINE,
            content="Use ESLint", tags=["javascript"],
        ))

        matched = reg.match(tech_stack=["python"], agent_role="main")
        assert len(matched) == 1
        assert matched[0].name == "py-hints"

    def test_match_multiple(self):
        reg = SkillRegistry()
        reg.register(Skill(
            name="s1", type=SkillType.INLINE, content="x",
            tags=["python"], priority=90,
        ))
        reg.register(Skill(
            name="s2", type=SkillType.INLINE, content="y",
            tags=["python"], priority=50,
        ))

        matched = reg.match(tech_stack=["python"])
        assert len(matched) == 2
        assert matched[0].name == "s1"  # higher priority first

    def test_match_empty_stack(self):
        reg = SkillRegistry()
        reg.register(Skill(name="generic", type=SkillType.INLINE, content="x"))
        matched = reg.match(tech_stack=[])
        assert len(matched) == 1

    def test_format_for_prompt(self):
        reg = SkillRegistry()
        reg.register(Skill(
            name="s1", type=SkillType.INLINE,
            content="Use type hints", tags=["python"],
        ))
        reg.register(Skill(
            name="Flask Guide", type=SkillType.KNOWLEDGE,
            content="Flask is a micro framework...", tags=["python"],
        ))

        matched = reg.match(tech_stack=["python"])
        prompt = reg.format_for_prompt(matched)
        assert "编码规范" in prompt
        assert "Use type hints" in prompt
        assert "Flask Guide" in prompt

    def test_format_respects_token_budget(self):
        reg = SkillRegistry()
        reg.register(Skill(
            name="big", type=SkillType.KNOWLEDGE,
            content="x" * 40000, tags=["python"], priority=50,
        ))
        reg.register(Skill(
            name="small", type=SkillType.INLINE,
            content="Be concise", tags=["python"], priority=90,
        ))

        matched = reg.match(tech_stack=["python"])
        prompt = reg.format_for_prompt(matched, max_tokens=100)
        assert "Be concise" in prompt
        assert "x" * 1000 not in prompt

    def test_stats(self):
        reg = SkillRegistry()
        reg.register(Skill(name="a", type=SkillType.INLINE, content="x"))
        reg.register(Skill(name="b", type=SkillType.KNOWLEDGE, content="y"))

        stats = reg.stats
        assert stats["total"] == 2
        assert stats["by_type"]["inline"] == 1
        assert stats["by_type"]["knowledge"] == 1


class TestSkillLoading:
    """Skill 文件加载"""

    def test_load_yaml_skill(self):
        with tempfile.TemporaryDirectory() as d:
            skill_file = os.path.join(d, "test.yaml")
            with open(skill_file, "w") as f:
                f.write("""
name: Test Skill
type: inline
tags: [python]
content: Always use type hints
priority: 80
""")
            from pathlib import Path
            reg = SkillRegistry()
            loaded = reg._load_from_dir(Path(d), "test")
            assert loaded == 1
            assert reg._skills[0].name == "Test Skill"

    def test_load_markdown_skill(self):
        with tempfile.TemporaryDirectory() as d:
            md_file = os.path.join(d, "guide.md")
            with open(md_file, "w") as f:
                f.write("""---
tags: [python, flask]
name: Flask Guide
---

# Flask Best Practices

Use blueprints for large apps.
""")
            reg = SkillRegistry()
            from pathlib import Path
            loaded = reg._load_from_dir(Path(d), "test")
            assert loaded == 1
            assert reg._skills[0].type == SkillType.KNOWLEDGE
            assert "blueprints" in reg._skills[0].content

    def test_load_builtin_skills(self):
        reg = SkillRegistry()
        loaded = reg.load_builtin()
        assert loaded >= 3  # 至少有我们创建的 3 个内置 skills

    def test_load_nonexistent_dir(self):
        reg = SkillRegistry()
        from pathlib import Path
        loaded = reg._load_from_dir(Path("/nonexistent/dir"), "test")
        assert loaded == 0

    def test_no_duplicate_loading(self):
        reg = SkillRegistry()
        loaded1 = reg.load_builtin()
        loaded2 = reg.load_builtin()
        assert loaded2 == 0  # 不重复加载
