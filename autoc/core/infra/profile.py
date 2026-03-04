"""技术栈 Profile 管理器 — 加载、匹配、合并技术栈最佳实践

为 Agent 提供技术栈特定的规范指导:
- Helper: 项目结构 (structure) + 开发规范 (conventions)
- Main: 开发规范 (conventions) + 推荐依赖 (dependencies) + 测试规范 (testing)

Profile 来源 (优先级从高到低):
1. 项目自定义: workspace/.autoc-profile.yaml
2. 内置模板: autoc/profiles/*.yaml
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger("autoc.profile")

_PROFILES_DIR = Path(__file__).parent.parent / "profiles"

CUSTOM_PROFILE_NAME = ".autoc-profile.yaml"


@dataclass
class TechProfile:
    """技术栈 Profile 数据对象"""
    name: str = ""
    tags: list[str] = field(default_factory=list)
    structure: str = ""
    conventions: str = ""
    testing: str = ""
    dependencies: dict[str, str] = field(default_factory=dict)
    source: str = ""  # 来源标记: "builtin" | "custom" | "merged"

    def is_empty(self) -> bool:
        return not (self.structure or self.conventions or self.testing)

    def for_agent(self, agent_role: str) -> str:
        """按 Agent 角色裁剪输出，减少无关 token"""
        parts = [f"## 技术栈规范 — {self.name}"]

        if agent_role in ("helper", "all"):
            if self.structure:
                parts.append(f"### 推荐项目结构\n{self.structure.rstrip()}")
            if self.conventions:
                parts.append(f"### 开发规范\n{self.conventions.rstrip()}")

        if agent_role in ("coder", "all"):
            if self.conventions:
                parts.append(f"### 开发规范\n{self.conventions.rstrip()}")
            if self.dependencies:
                deps = "\n".join(f"  {k}: {v}" for k, v in self.dependencies.items())
                parts.append(f"### 推荐依赖版本\n{deps}")
            if self.testing:
                parts.append(f"### 测试规范\n{self.testing.rstrip()}")

        if len(parts) <= 1:
            return ""
        return "\n\n".join(parts)


class ProfileManager:
    """技术栈 Profile 管理器"""

    def __init__(self, profiles_dir: str | Path | None = None):
        self._profiles_dir = Path(profiles_dir) if profiles_dir else _PROFILES_DIR
        self._cache: dict[str, TechProfile] = {}
        self._all_profiles: list[TechProfile] | None = None

    def _load_all(self) -> list[TechProfile]:
        """延迟加载所有内置 Profile"""
        if self._all_profiles is not None:
            return self._all_profiles

        self._all_profiles = []
        if not self._profiles_dir.exists():
            logger.warning(f"Profile 目录不存在: {self._profiles_dir}")
            return self._all_profiles

        for yaml_file in sorted(self._profiles_dir.glob("*.yaml")):
            try:
                with open(yaml_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                profile = TechProfile(
                    name=data.get("name", yaml_file.stem),
                    tags=[t.lower() for t in data.get("tags", [])],
                    structure=data.get("structure", ""),
                    conventions=data.get("conventions", ""),
                    testing=data.get("testing", ""),
                    dependencies=data.get("dependencies", {}),
                    source="builtin",
                )
                self._all_profiles.append(profile)
                logger.debug(f"已加载 Profile: {profile.name} (tags={profile.tags})")
            except Exception as e:
                logger.warning(f"加载 Profile 失败 [{yaml_file.name}]: {e}")

        logger.info(f"已加载 {len(self._all_profiles)} 个内置 Profile")
        return self._all_profiles

    def _load_custom(self, workspace_dir: str) -> TechProfile | None:
        """加载项目自定义 Profile"""
        custom_path = os.path.join(workspace_dir, CUSTOM_PROFILE_NAME)
        if not os.path.exists(custom_path):
            return None

        try:
            with open(custom_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            profile = TechProfile(
                name=data.get("name", "自定义规范"),
                tags=[t.lower() for t in data.get("tags", [])],
                structure=data.get("structure", ""),
                conventions=data.get("conventions", ""),
                testing=data.get("testing", ""),
                dependencies=data.get("dependencies", {}),
                source="custom",
            )
            logger.info(f"已加载自定义 Profile: {profile.name}")
            return profile
        except Exception as e:
            logger.warning(f"加载自定义 Profile 失败: {e}")
            return None

    def match(self, tech_stack: list[str], workspace_dir: str = "") -> TechProfile | None:
        """根据技术栈标签匹配最佳 Profile

        匹配逻辑:
        1. 优先使用项目自定义 .autoc-profile.yaml
        2. 计算每个内置 Profile 与 tech_stack 的标签交集
        3. 交集最大的获胜；平局时取第一个匹配
        4. 至少需要 1 个标签匹配

        Args:
            tech_stack: 规划阶段分析得出的技术栈列表 (如 ["Python", "Flask", "SQLAlchemy"])
            workspace_dir: 项目工作区路径 (用于加载自定义 Profile)

        Returns:
            匹配到的 TechProfile，或 None
        """
        if not tech_stack:
            return None

        # 自定义 Profile 优先
        if workspace_dir:
            custom = self._load_custom(workspace_dir)
            if custom and not custom.is_empty():
                return custom

        # 标签归一化
        normalized = {t.lower().strip() for t in tech_stack}

        cache_key = "|".join(sorted(normalized))
        if cache_key in self._cache:
            return self._cache[cache_key]

        profiles = self._load_all()
        if not profiles:
            return None

        best: TechProfile | None = None
        best_score = 0

        for profile in profiles:
            score = len(normalized & set(profile.tags))
            if score > best_score:
                best_score = score
                best = profile

        if best and best_score >= 1:
            logger.info(f"匹配到 Profile: {best.name} (score={best_score}, tags={sorted(normalized & set(best.tags))})")
            self._cache[cache_key] = best
            return best

        logger.debug(f"未匹配到 Profile (tech_stack={tech_stack})")
        return None

    def list_profiles(self) -> list[dict]:
        """列出所有可用的内置 Profile"""
        return [
            {"name": p.name, "tags": p.tags, "source": p.source}
            for p in self._load_all()
        ]
