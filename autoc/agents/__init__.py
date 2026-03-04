"""AutoC Agents

Agent 角色 (OpenHands V1.1 架构):
- PlanningAgent (Planner): 项目规划师 (ReAct + 只读工具 → PLAN.md)
- CodeActAgent (Coder): 全栈实现者 (编码/验证/修复)，支持 clone() 并行
- CritiqueAgent: 代码评审专家 (4 维评分/代码级 issues)，可选
"""

from autoc.agents.base import BaseAgent
from autoc.agents.planner import PlanningAgent
from autoc.agents.code_act_agent import CodeActAgent
from autoc.agents.critique import CritiqueAgent

__all__ = [
    "BaseAgent", "PlanningAgent", "CodeActAgent", "CritiqueAgent",
]
