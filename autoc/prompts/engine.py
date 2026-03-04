"""PromptEngine — Jinja2 模板化 Prompt 管理

功能：
1. 从 templates/ 目录加载 .j2 模板
2. 支持模板继承、条件渲染、变量注入
3. 内置 few-shot 示例 include
4. 支持自定义模板目录覆盖（项目级定制）

使用：
    engine = PromptEngine()
    prompt = engine.render("code_act_agent", mirror_section="...", tools_hint="...")
    prompt = engine.render("planner")
    prompt = engine.render("critique", pass_threshold=85)
"""

import logging
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, TemplateNotFound

logger = logging.getLogger("autoc.prompts")

_BUILTIN_TEMPLATES_DIR = Path(__file__).parent / "templates"


class PromptEngine:
    """Jinja2 模板引擎，管理所有 Agent System Prompt"""

    def __init__(
        self,
        custom_dirs: list[str | Path] | None = None,
        enable_few_shot: bool = True,
    ):
        """
        Args:
            custom_dirs: 额外模板目录（优先级高于内置目录，用于项目级覆盖）
            enable_few_shot: 是否启用 few-shot 示例注入
        """
        search_paths: list[str | Path] = []
        if custom_dirs:
            search_paths.extend(custom_dirs)
        search_paths.append(str(_BUILTIN_TEMPLATES_DIR))

        self._env = Environment(
            loader=FileSystemLoader([str(p) for p in search_paths]),
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=False,
        )

        self._enable_few_shot = enable_few_shot
        self._env.globals["few_shot_enabled"] = enable_few_shot

        self._cache: dict[str, str] = {}
        logger.debug(f"PromptEngine 初始化: 模板路径 {search_paths}")

    def render(self, template_name: str, **context: Any) -> str:
        """渲染模板

        Args:
            template_name: 模板名（不含 .j2 后缀）
            **context: 模板变量

        Returns:
            渲染后的 prompt 文本
        """
        full_name = f"{template_name}.j2"
        try:
            template = self._env.get_template(full_name)
            return template.render(**context).strip()
        except TemplateNotFound:
            logger.warning(f"模板 '{full_name}' 未找到，返回空字符串")
            return ""

    def has_template(self, template_name: str) -> bool:
        """检查模板是否存在"""
        try:
            self._env.get_template(f"{template_name}.j2")
            return True
        except TemplateNotFound:
            return False

    def list_templates(self) -> list[str]:
        """列出所有可用模板（去掉 .j2 后缀）"""
        all_templates = self._env.loader.list_templates()
        return [t.removesuffix(".j2") for t in all_templates if t.endswith(".j2")]

    @property
    def templates_dir(self) -> Path:
        return _BUILTIN_TEMPLATES_DIR
