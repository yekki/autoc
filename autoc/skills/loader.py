"""Skill 加载器 — 扫描、解析、缓存 SKILL.md 文件

借鉴 MyCodeAgent 的 SkillLoader 设计：
- 扫描 project_root/skills/ 下的所有 SKILL.md
- 解析 YAML frontmatter（name + description）
- 支持 $ARGUMENTS 模板替换
- mtime 缓存，增量刷新
- Prompt 预算控制（默认 12000 字符）
"""

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("autoc.skills")


@dataclass
class SkillInfo:
    """单个 Skill 的元信息"""
    name: str
    description: str
    base_dir: str
    file_path: str
    mtime: float = 0.0


class SkillLoader:
    """Skill 目录扫描器 + 缓存管理器"""

    def __init__(self, skills_dir: str, char_budget: int = 12000):
        self.skills_dir = skills_dir
        self.char_budget = char_budget
        self._skills: dict[str, SkillInfo] = {}
        self._dir_mtime: float = 0.0
        self._scan()

    def _scan(self):
        """全量扫描 skills/ 目录"""
        if not os.path.isdir(self.skills_dir):
            return

        try:
            self._dir_mtime = os.path.getmtime(self.skills_dir)
        except OSError:
            return

        self._skills.clear()
        for entry in os.scandir(self.skills_dir):
            if not entry.is_dir():
                continue
            skill_file = os.path.join(entry.path, "SKILL.md")
            if not os.path.isfile(skill_file):
                continue
            info = self._parse_skill(entry.name, entry.path, skill_file)
            if info:
                self._skills[info.name] = info

        logger.info(f"扫描到 {len(self._skills)} 个 Skill: {list(self._skills.keys())}")

    def refresh_if_stale(self):
        """检查目录 mtime 是否变化，变化则重新扫描"""
        if not os.path.isdir(self.skills_dir):
            return
        try:
            current_mtime = os.path.getmtime(self.skills_dir)
        except OSError:
            return
        if current_mtime != self._dir_mtime:
            self._scan()

    def get_skill(self, name: str, refresh: bool = True) -> Optional[SkillInfo]:
        """获取指定 Skill"""
        if refresh:
            self.refresh_if_stale()
        return self._skills.get(name)

    def list_skills(self) -> list[SkillInfo]:
        return list(self._skills.values())

    def load_skill_content(self, name: str, arguments: str = "") -> Optional[str]:
        """加载 Skill 内容并应用 $ARGUMENTS 替换"""
        info = self.get_skill(name)
        if not info:
            return None

        try:
            with open(info.file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            logger.warning(f"读取 Skill {name} 失败: {e}")
            return None

        # 去除 frontmatter
        content = _strip_frontmatter(content)

        # 应用 $ARGUMENTS 替换
        if arguments:
            if "$ARGUMENTS" in content:
                content = content.replace("$ARGUMENTS", arguments)
            else:
                content += f"\n\nARGUMENTS: {arguments}"

        return content

    def format_for_prompt(self) -> str:
        """生成 Skills 列表提示词（受 char_budget 限制）"""
        self.refresh_if_stale()
        if not self._skills:
            return ""

        lines = ["## 可用技能 (Skills)"]
        total_chars = len(lines[0])

        for info in self._skills.values():
            line = f"- **{info.name}**: {info.description}"
            if total_chars + len(line) > self.char_budget:
                lines.append(f"- ...及 {len(self._skills) - len(lines) + 1} 个更多技能")
                break
            lines.append(line)
            total_chars += len(line)

        return "\n".join(lines)

    # ==================== 内部方法 ====================

    @staticmethod
    def _parse_skill(dir_name: str, base_dir: str, file_path: str) -> Optional[SkillInfo]:
        """解析 SKILL.md 的 YAML frontmatter"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read(2000)
        except Exception:
            return None

        name = dir_name
        description = ""

        # 解析简单 frontmatter（不依赖 pyyaml）
        if content.startswith("---"):
            end = content.find("---", 3)
            if end > 0:
                fm = content[3:end]
                for line in fm.strip().split("\n"):
                    if ":" in line:
                        key, _, val = line.partition(":")
                        key = key.strip()
                        val = val.strip().strip('"').strip("'")
                        if key == "name" and val:
                            name = val
                        elif key == "description" and val:
                            description = val

        return SkillInfo(
            name=name,
            description=description or f"Skill: {name}",
            base_dir=base_dir,
            file_path=file_path,
            mtime=os.path.getmtime(file_path),
        )


def _strip_frontmatter(content: str) -> str:
    """去除 YAML frontmatter"""
    if not content.startswith("---"):
        return content
    end = content.find("---", 3)
    if end < 0:
        return content
    return content[end + 3:].lstrip("\n")
