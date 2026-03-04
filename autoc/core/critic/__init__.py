"""Critic 可插拔框架 — 代码/功能评审的抽象接口

参考 OpenHands Critic Framework：
- BaseCritic.evaluate(events, git_patch) → CriticResult
- 多 Critic 可组合（CodeQuality + Security + Performance）
- CritiqueAgent 作为 Critic 编排器
"""

from autoc.core.critic.base import BaseCritic, CriticResult, CompositeCritic

__all__ = ["BaseCritic", "CriticResult", "CompositeCritic"]
