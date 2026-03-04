"""智能模型路由 — 按任务复杂度自动选择模型

核心策略：根据需求复杂度和 Agent 角色，自动选择最合适的模型，
在保证生成质量的前提下降低 Token 成本。

simple 项目 Token 成本可降低 50%+，因为大部分 Dev 任务可以用便宜模型完成。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("autoc.model_router")

# 各提供商的模型分层（strongest → cheap）
PROVIDER_TIERS: dict[str, dict[str, str]] = {
    "glm": {
        "strongest": "glm-5",
        "strong": "glm-4.7",
        "medium": "glm-4.5-air",
        "cheap": "glm-4.7-flash",
    },
    "kimi": {
        "strongest": "kimi-for-coding",
        "strong": "kimi-for-coding",
        "medium": "kimi-for-coding",
        "cheap": "kimi-for-coding",
    },
    "qwen": {
        "strongest": "qwen3-coder-plus",
        "strong": "qwen3-coder-plus",
        "medium": "qwen3.5-plus",
        "cheap": "qwen-flash",
    },
    "deepseek": {
        "strongest": "deepseek-reasoner",
        "strong": "deepseek-chat",
        "medium": "deepseek-chat",
        "cheap": "deepseek-chat",
    },
    "openai": {
        "strongest": "gpt-4o",
        "strong": "gpt-4o",
        "medium": "gpt-4o-mini",
        "cheap": "gpt-4o-mini",
    },
    "anthropic": {
        "strongest": "claude-sonnet-4-5-20250514",
        "strong": "claude-sonnet-4-5-20250514",
        "medium": "claude-haiku-3-5-20241022",
        "cheap": "claude-haiku-3-5-20241022",
    },
}

# 各 Agent 在不同复杂度下的模型偏好层级
AGENT_ROUTING: dict[str, dict[str, str]] = {
    "coder": {
        "simple": "cheap",
        "medium": "strong",
        "complex": "strong",
    },
    "critique": {
        "simple": "medium",
        "medium": "strong",
        "complex": "strong",
    },
    "helper": {
        "simple": "medium",
        "medium": "strong",
        "complex": "strongest",
    },
}


class ModelRouter:
    """智能模型路由器

    根据任务复杂度自动选择模型，支持：
    1. 基于 provider 的 tier 映射
    2. 每个 Agent 角色的路由策略
    3. 手动覆盖（config 中显式指定的模型优先）
    4. 自动降级（推荐模型不可用时回退到默认模型）
    """

    def __init__(self, provider: str, config: dict | None = None):
        self.provider = provider
        self._config = config or {}
        self._enabled = self._config.get("enabled", True)
        self._overrides = self._config.get("override", {})
        self._tiers = PROVIDER_TIERS.get(provider, {})

    def route(self, agent: str, complexity: str) -> str:
        """根据 Agent 角色和复杂度返回推荐模型 ID

        Args:
            agent: "coder" | "critique" | "helper"
            complexity: "simple" | "medium" | "complex"

        Returns:
            推荐的模型 ID，如果路由不可用则返回空字符串（使用默认模型）
        """
        if not self._enabled:
            return ""

        # 手动覆盖优先
        agent_overrides = self._overrides.get(agent, {})
        if complexity in agent_overrides:
            model = agent_overrides[complexity]
            logger.info(f"模型路由 [覆盖]: {agent}/{complexity} → {model}")
            return model

        # 查路由表
        agent_routing = AGENT_ROUTING.get(agent, {})
        tier = agent_routing.get(complexity, "strong")

        # 查 provider 的对应 tier 模型
        model = self._tiers.get(tier, "")
        if model:
            logger.info(f"模型路由: {agent}/{complexity} → tier={tier} → {model}")
        return model

    def get_routing_table(self) -> dict[str, dict[str, str]]:
        """返回当前路由表（用于调试）"""
        table: dict[str, dict[str, str]] = {}
        for agent in ("coder", "critique", "helper"):
            table[agent] = {}
            for complexity in ("simple", "medium", "complex"):
                model = self.route(agent, complexity)
                table[agent][complexity] = model or "(默认)"
        return table

    @property
    def is_enabled(self) -> bool:
        return self._enabled and bool(self._tiers)
