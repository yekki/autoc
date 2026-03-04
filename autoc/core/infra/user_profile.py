"""User Profile — 用户偏好管理

- 持久化到 YAML 文件，跨会话累积
- 按 Agent 角色裁剪后注入 prompt
- 仅通过显式 API 更新（set_preference / record_tech_stack / record_project_result）

偏好维度：
1. code_style: 代码风格偏好（命名、注释语言、缩进等）
2. tech_preferences: 技术栈偏好（框架、测试工具等）
3. work_patterns: 工作模式偏好（评审深度、文档格式等）
4. project_history: 历史项目统计（技术栈频率、成功率等）
"""

import logging
import os
import time
import yaml
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

logger = logging.getLogger("autoc.user_profile")


@dataclass
class UserPreference:
    """用户偏好数据"""
    code_style: dict = field(default_factory=lambda: {
        "naming_convention": "",
        "comment_language": "",
        "type_hints": True,
        "docstring_style": "",
    })
    tech_preferences: dict = field(default_factory=lambda: {
        "preferred_frameworks": [],
        "preferred_test_tools": [],
        "preferred_languages": [],
        "last_stack": "",
    })
    work_patterns: dict = field(default_factory=lambda: {
        "planning_style": "structured",
        "review_depth": "standard",
        "doc_format": "markdown",
        "iteration_patience": "normal",
    })
    project_history: dict = field(default_factory=lambda: {
        "total_projects": 0,
        "tasks_completed": 0,
        "tech_stack_frequency": {},
        "success_rate": 0.0,
    })
    updated_at: float = 0.0


class UserProfileManager:
    """用户画像管理器

    用法：
        manager = UserProfileManager("~/.autoc/user_profile.yaml")
        prompt = manager.for_agent_prompt("main")
    """

    def __init__(self, profile_path: str = ""):
        if not profile_path:
            home = os.path.expanduser("~")
            profile_path = os.path.join(home, ".autoc", "user_profile.yaml")
        self._path = Path(profile_path)
        self._preferences = self._load()

    def record_tech_stack(self, tech_stack: list[str]) -> None:
        """记录使用的技术栈（频率统计）"""
        freq = self._preferences.project_history.get("tech_stack_frequency", {})
        for tech in tech_stack:
            tech_lower = tech.lower()
            freq[tech_lower] = freq.get(tech_lower, 0) + 1
        self._preferences.project_history["tech_stack_frequency"] = freq

        # 更新 preferred 列表（top 5 最常用）
        sorted_tech = sorted(freq.items(), key=lambda x: -x[1])
        self._preferences.tech_preferences["preferred_languages"] = [
            t for t, _ in sorted_tech[:5]
        ]
        self._preferences.updated_at = time.time()
        self._save()

    def record_project_result(self, success: bool) -> None:
        """记录项目执行结果（成功率统计）"""
        history = self._preferences.project_history
        history["total_projects"] = history.get("total_projects", 0) + 1
        total = history["total_projects"]
        prev_rate = history.get("success_rate", 0.0)
        if success:
            history["success_rate"] = prev_rate + (1.0 - prev_rate) / total
        else:
            history["success_rate"] = prev_rate * (total - 1) / total
        self._preferences.updated_at = time.time()
        self._save()

    def set_preference(self, key: str, value: Any) -> None:
        """显式设置用户偏好"""
        if self._update_pref(key, value):
            self._preferences.updated_at = time.time()
            self._save()

    def get_preferences(self) -> UserPreference:
        return self._preferences

    def for_agent_prompt(self, agent_role: str = "all") -> str:
        """生成注入 Agent prompt 的用户偏好文本"""
        pref = self._preferences
        parts: list[str] = []

        # 代码风格偏好
        style_parts = []
        if pref.code_style.get("naming_convention"):
            style_parts.append(f"命名: {pref.code_style['naming_convention']}")
        if pref.code_style.get("comment_language"):
            style_parts.append(f"注释语言: {pref.code_style['comment_language']}")
        if pref.code_style.get("docstring_style"):
            style_parts.append(f"文档风格: {pref.code_style['docstring_style']}")
        if style_parts:
            parts.append("代码风格: " + ", ".join(style_parts))

        # 技术栈偏好
        preferred = pref.tech_preferences.get("preferred_languages", [])
        if preferred and agent_role in ("coder", "helper", "all"):
            parts.append(f"常用技术: {', '.join(preferred[:5])}")

        # 工作模式
        if agent_role in ("helper", "all"):
            planning = pref.work_patterns.get("planning_style", "")
            if planning:
                parts.append(f"规划偏好: {planning}")

        if not parts:
            return ""

        return "## 用户偏好\n" + "\n".join(f"- {p}" for p in parts)

    @property
    def stats(self) -> dict:
        return {
            "profile_path": str(self._path),
            "exists": self._path.exists(),
            "updated_at": self._preferences.updated_at,
            "total_projects": self._preferences.project_history.get("total_projects", 0),
            "tech_stack_count": len(
                self._preferences.project_history.get("tech_stack_frequency", {}),
            ),
        }

    def _update_pref(self, dotted_key: str, value: Any) -> bool:
        """更新嵌套偏好字段，返回是否有变更"""
        parts = dotted_key.split(".")
        if len(parts) != 2:
            return False

        section, key = parts
        target = getattr(self._preferences, section, None)
        if not isinstance(target, dict):
            return False

        if value == "+1":
            target[key] = target.get(key, 0) + 1
            return True

        if target.get(key) != value:
            target[key] = value
            return True

        return False

    def _load(self) -> UserPreference:
        """从 YAML 文件加载偏好"""
        if not self._path.exists():
            return UserPreference()
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if not isinstance(data, dict):
                return UserPreference()
            pref = UserPreference()
            for section in ("code_style", "tech_preferences", "work_patterns", "project_history"):
                if section in data and isinstance(data[section], dict):
                    getattr(pref, section).update(data[section])
            pref.updated_at = data.get("updated_at", 0.0)
            return pref
        except Exception as e:
            logger.warning(f"加载用户画像失败: {e}")
            return UserPreference()

    def _save(self) -> None:
        """持久化偏好到 YAML（原子写入）"""
        import tempfile
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # 原子写入：先写临时文件，再 rename，防止进程崩溃损坏数据
            fd, tmp_path = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    yaml.dump(
                        asdict(self._preferences), f,
                        default_flow_style=False, allow_unicode=True,
                    )
                os.replace(tmp_path, self._path)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
                raise
        except Exception as e:
            logger.warning(f"保存用户画像失败: {e}")
