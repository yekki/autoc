"""循环引擎数据模型 — Phase / IterationResult / LoopResult / TokenTracker"""

from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum

from autoc.core.analysis.exit_detector import ExitReason


class Phase(str, Enum):
    DEV = "dev"
    TEST = "test"
    FIX = "fix"
    CRITIQUE_REVIEW = "critique_review"

    PLAN = "plan"
    PLANNING_REVIEW = "planning_review"


@dataclass
class IterationResult:
    iteration: int
    phase: Phase
    story_id: str = ""
    story_title: str = ""
    success: bool = False
    agent_output: str = ""
    files_changed: list[str] = field(default_factory=list)
    error: str = ""
    elapsed_seconds: float = 0.0
    tokens_used: int = 0


@dataclass
class LoopResult:
    success: bool = False
    total_iterations: int = 0
    stories_passed: int = 0
    stories_total: int = 0
    exit_reason: ExitReason | None = None
    iterations: list[IterationResult] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    total_tokens: int = 0


class TokenTracker:
    """P-TK-01: 结构化 Token 追踪 — 只追踪，不干预执行决策"""

    def __init__(self):
        self.by_role: dict[str, int] = defaultdict(int)
        self.by_task: dict[str, int] = defaultdict(int)
        self.by_phase: dict[str, int] = defaultdict(int)

    def record(self, role: str, phase: str, task_id: str, tokens: int):
        if tokens <= 0:
            return
        self.by_role[role] += tokens
        self.by_phase[phase] += tokens
        if task_id:
            self.by_task[task_id] += tokens

    @property
    def total(self) -> int:
        return sum(self.by_role.values())

    def snapshot(self) -> dict:
        """供 SSE 事件和前端展示用"""
        return {
            "by_role": dict(self.by_role),
            "by_task": dict(self.by_task),
            "by_phase": dict(self.by_phase),
            "total": self.total,
        }
