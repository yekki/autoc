"""Skill Registry — 可复用知识注入系统

两种 Skill 类型：
1. Inline Skill: 短提示片段，直接嵌入 system prompt（如"始终使用 type hints"）
2. Knowledge Skill: 领域知识，从文件加载按需注入（如"Flask 最佳实践"）

Skill 匹配策略：
- 基于 tags（技术栈标签）匹配
- 基于 agent_roles（角色过滤）匹配
- 按 priority 排序，token 预算内贪心选取

Skill 来源：
- 内置 Skills（autoc/skills/）
- 项目自定义 Skills（workspace/.autoc-skills/）
- Profile 关联 Skills（TechProfile.conventions → Inline Skill）
"""

import logging
import os
import yaml
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger("autoc.skill")


class SkillType(str, Enum):
    INLINE = "inline"
    KNOWLEDGE = "knowledge"
    TASK = "task"


@dataclass
class Skill:
    """单个 Skill"""
    name: str
    type: SkillType
    content: str
    tags: list[str] = field(default_factory=list)
    agent_roles: list[str] = field(default_factory=lambda: ["all"])
    priority: int = 50
    source: str = "builtin"
    max_tokens: int = 0

    def matches(self, tech_stack: list[str], agent_role: str) -> bool:
        """检查 Skill 是否匹配给定的技术栈和角色"""
        if self.agent_roles and "all" not in self.agent_roles:
            if agent_role not in self.agent_roles:
                return False
        if not self.tags:
            return True
        normalized_tags = {t.lower() for t in self.tags}
        normalized_stack = {t.lower() for t in tech_stack}
        return bool(normalized_tags & normalized_stack)

    @property
    def estimated_tokens(self) -> int:
        if self.max_tokens > 0:
            return self.max_tokens
        return len(self.content) // 4


class SkillRegistry:
    """Skill 注册表 — 加载、匹配、注入

    用法：
        registry = SkillRegistry()
        registry.load_builtin()
        registry.load_project("/path/to/workspace")
        skills = registry.match(tech_stack=["python", "flask"], agent_role="main")
        prompt = registry.format_for_prompt(skills, max_tokens=2000)
    """

    def __init__(self):
        self._skills: list[Skill] = []
        self._loaded_dirs: set[str] = set()

    def register(self, skill: Skill) -> None:
        """注册一个 Skill"""
        self._skills.append(skill)

    def load_builtin(self) -> int:
        """加载内置 Skills"""
        builtin_dir = Path(__file__).parent.parent.parent / "skills"
        return self._load_from_dir(builtin_dir, source="builtin")

    def load_project(self, workspace_dir: str) -> int:
        """加载项目自定义 Skills"""
        project_skills_dir = Path(workspace_dir) / ".autoc-skills"
        return self._load_from_dir(project_skills_dir, source="project")

    def match(
        self,
        tech_stack: list[str] | None = None,
        agent_role: str = "all",
    ) -> list[Skill]:
        """匹配 Skills，按 priority 降序排列"""
        tech_stack = tech_stack or []
        matched = [
            s for s in self._skills
            if s.matches(tech_stack, agent_role)
        ]
        matched.sort(key=lambda s: (-s.priority, s.name))
        return matched

    def format_for_prompt(
        self,
        skills: list[Skill],
        max_tokens: int = 2000,
    ) -> str:
        """将匹配的 Skills 格式化为 prompt 文本，在 token 预算内贪心选取"""
        if not skills:
            return ""

        selected: list[Skill] = []
        budget = max_tokens
        for skill in skills:
            cost = skill.estimated_tokens
            if cost <= budget:
                selected.append(skill)
                budget -= cost

        if not selected:
            return ""

        parts: list[str] = []
        inline_skills = [s for s in selected if s.type == SkillType.INLINE]
        knowledge_skills = [s for s in selected if s.type == SkillType.KNOWLEDGE]

        if inline_skills:
            rules = "\n".join(f"- {s.content}" for s in inline_skills)
            parts.append(f"## 编码规范\n{rules}")

        if knowledge_skills:
            for s in knowledge_skills:
                parts.append(f"## {s.name}\n{s.content}")

        return "\n\n".join(parts)

    @property
    def stats(self) -> dict[str, Any]:
        by_type = {}
        for s in self._skills:
            by_type[s.type.value] = by_type.get(s.type.value, 0) + 1
        return {
            "total": len(self._skills),
            "by_type": by_type,
            "loaded_dirs": list(self._loaded_dirs),
        }

    def _load_from_dir(self, skills_dir: Path, source: str) -> int:
        """从目录加载 Skills（YAML 格式）"""
        dir_key = str(skills_dir)
        if dir_key in self._loaded_dirs:
            return 0
        self._loaded_dirs.add(dir_key)

        if not skills_dir.exists():
            return 0

        loaded = 0
        for fp in sorted(skills_dir.glob("*.yaml")) + sorted(skills_dir.glob("*.yml")):
            try:
                skill = self._parse_skill_file(fp, source)
                if skill:
                    self._skills.append(skill)
                    loaded += 1
            except Exception as e:
                logger.warning(f"加载 Skill 失败: {fp} — {e}")

        for fp in sorted(skills_dir.glob("*.md")):
            try:
                skill = self._parse_markdown_skill(fp, source)
                if skill:
                    self._skills.append(skill)
                    loaded += 1
            except Exception as e:
                logger.warning(f"加载 Skill 失败: {fp} — {e}")

        if loaded:
            logger.info(f"从 {skills_dir} 加载了 {loaded} 个 Skills ({source})")
        return loaded

    @staticmethod
    def _parse_skill_file(fp: Path, source: str) -> Skill | None:
        """解析 YAML 格式的 Skill 文件"""
        with open(fp, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not data or not isinstance(data, dict):
            return None

        skill_type = SkillType(data.get("type", "inline"))
        return Skill(
            name=data.get("name", fp.stem),
            type=skill_type,
            content=data.get("content", ""),
            tags=data.get("tags", []),
            agent_roles=data.get("agent_roles", ["all"]),
            priority=data.get("priority", 50),
            source=source,
        )

    @staticmethod
    def _parse_markdown_skill(fp: Path, source: str) -> Skill | None:
        """解析 Markdown 格式的 Knowledge Skill"""
        content = fp.read_text(encoding="utf-8").strip()
        if not content:
            return None

        # 从 frontmatter 提取元数据（可选）
        tags: list[str] = []
        name = fp.stem

        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                try:
                    meta = yaml.safe_load(parts[1])
                    if isinstance(meta, dict):
                        tags = meta.get("tags", [])
                        name = meta.get("name", name)
                    content = parts[2].strip()
                except yaml.YAMLError:
                    pass

        return Skill(
            name=name,
            type=SkillType.KNOWLEDGE,
            content=content,
            tags=tags,
            source=source,
        )
