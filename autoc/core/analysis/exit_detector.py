"""Exit Detector — 智能退出检测

融合 frankbria/ralph-claude-code 的双条件门控设计:
- completion_indicators: 自然语言模式匹配 (启发式)
- EXIT_SIGNAL: Agent 显式声明 (确认式)

两者同时满足才允许退出, 防止 Agent 在生产性迭代中误退出。
"""

import logging
import re
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("autoc.exit_detector")


class ExitReason(str, Enum):
    """退出原因"""
    PROJECT_COMPLETE = "project_complete"
    ALL_STORIES_PASSED = "all_stories_passed"
    PLAN_COMPLETE = "plan_complete"
    MAX_ITERATIONS = "max_iterations"
    CIRCUIT_BREAKER = "circuit_breaker"
    NO_PROGRESS = "no_progress"
    USER_INTERRUPT = "user_interrupt"
    CONSECUTIVE_DONE = "consecutive_done"
    RATE_LIMITED = "rate_limited"


@dataclass
class ExitAnalysis:
    """退出分析结果"""
    should_exit: bool = False
    reason: ExitReason | None = None
    completion_indicators: int = 0
    exit_signal: bool = False
    confidence: float = 0.0
    message: str = ""


COMPLETION_PATTERNS = [
    r"(?i)all\s+(tasks?|stories?|items?)\s+(are\s+)?complete",
    r"(?i)project\s+(is\s+)?(complete|done|finished|ready)",
    r"(?i)everything\s+(is\s+)?(complete|done|implemented|working)",
    r"(?i)no\s+more\s+(tasks?|stories?|work|items?)",
    r"(?i)all\s+(tests?\s+)?pass(ing|ed)?",
    r"所有.*(任务|故事|测试).*(完成|通过|成功)",
    r"项目.*已?(完成|就绪|结束)",
    r"全部.*(通过|完成|验证)",
    r"\bCOMPLETE\b",
]

EXIT_SIGNAL_PATTERN = re.compile(
    r"EXIT_SIGNAL\s*[:=]\s*(true|yes|1)",
    re.IGNORECASE,
)

RALPH_STATUS_PATTERN = re.compile(
    r"RALPH_STATUS.*?EXIT_SIGNAL\s*[:=]\s*(true|false)",
    re.IGNORECASE | re.DOTALL,
)


class ExitDetector:
    """智能退出检测器

    双条件门控:
    1. completion_indicators >= threshold (自然语言启发式)
    2. EXIT_SIGNAL: true (Agent 显式确认)

    参考: frankbria/ralph-claude-code v0.11.5
    """

    def __init__(
        self,
        completion_threshold: int = 2,
        require_exit_signal: bool = True,
        max_consecutive_done: int = 2,
    ):
        self.completion_threshold = completion_threshold
        self.require_exit_signal = require_exit_signal
        self.max_consecutive_done = max_consecutive_done

        self._accumulated_indicators: int = 0
        self._consecutive_done_count: int = 0

    def reset(self):
        self._accumulated_indicators = 0
        self._consecutive_done_count = 0

    def analyze(
        self,
        agent_output: str,
        all_stories_passed: bool = False,
        iteration: int = 0,
        max_iterations: int = 0,
        has_progress: bool = True,
        plan_complete: bool = False,
        phase: str = "",
        has_untested_stories: bool = False,
    ) -> ExitAnalysis:
        """分析 Agent 输出, 决定是否应该退出循环

        Args:
            agent_output: Agent 本轮输出文本
            all_stories_passed: prd.json 中是否所有 story 都 passes=true
            iteration: 当前迭代次数
            max_iterations: 最大迭代次数
            has_progress: 本轮是否有进度 (文件变更/Git 提交)
            plan_complete: PM 增量规划是否已全部完成
            phase: 当前阶段 (dev/test/fix/plan)，用于区分完成信号来源
            has_untested_stories: 是否有已实现但未经 Tester 验证的 story
        """
        if max_iterations > 0 and iteration >= max_iterations:
            return ExitAnalysis(
                should_exit=True,
                reason=ExitReason.MAX_ITERATIONS,
                message=f"达到最大迭代次数 ({max_iterations})",
            )

        if all_stories_passed and plan_complete:
            return ExitAnalysis(
                should_exit=True,
                reason=ExitReason.PLAN_COMPLETE,
                confidence=1.0,
                message="所有需求已规划完成且全部 stories 通过验证",
            )

        if all_stories_passed:
            return ExitAnalysis(
                should_exit=True,
                reason=ExitReason.ALL_STORIES_PASSED,
                confidence=1.0,
                message="所有 user stories 已通过验证",
            )

        indicators = self._count_completion_indicators(agent_output)
        exit_signal = self._detect_exit_signal(agent_output)

        if exit_signal:
            self._accumulated_indicators += indicators
        else:
            self._accumulated_indicators = 0

        # 双条件门控: 完成指标 + EXIT_SIGNAL
        # 但如果还有未经 Tester 验证的 story，不允许退出
        if (self._accumulated_indicators >= self.completion_threshold
                and exit_signal and not has_untested_stories):
            return ExitAnalysis(
                should_exit=True,
                reason=ExitReason.PROJECT_COMPLETE,
                completion_indicators=self._accumulated_indicators,
                exit_signal=True,
                confidence=0.9,
                message="双条件退出: 完成指标达标 + EXIT_SIGNAL 确认",
            )

        if (not self.require_exit_signal
                and self._accumulated_indicators >= self.completion_threshold
                and not has_untested_stories):
            return ExitAnalysis(
                should_exit=True,
                reason=ExitReason.PROJECT_COMPLETE,
                completion_indicators=self._accumulated_indicators,
                confidence=0.7,
                message="完成指标达标 (未要求 EXIT_SIGNAL)",
            )

        # 连续完成信号：仅 TEST/FIX 阶段计入，DEV 阶段的自验证输出不算
        if phase in ("test", "fix") and indicators > 0:
            self._consecutive_done_count += 1
        elif phase == "dev":
            self._consecutive_done_count = 0  # dev 阶段重置连续完成计数，避免跨阶段误累加
        else:
            if indicators > 0:
                self._consecutive_done_count += 1
            else:
                self._consecutive_done_count = 0

        if (self._consecutive_done_count >= self.max_consecutive_done
                and not has_untested_stories):
            return ExitAnalysis(
                should_exit=True,
                reason=ExitReason.CONSECUTIVE_DONE,
                completion_indicators=indicators,
                confidence=0.6,
                message=f"连续 {self._consecutive_done_count} 轮输出完成信号",
            )

        return ExitAnalysis(
            should_exit=False,
            completion_indicators=indicators,
            exit_signal=exit_signal,
        )

    def _count_completion_indicators(self, text: str) -> int:
        count = 0
        for pattern in COMPLETION_PATTERNS:
            matches = re.findall(pattern, text)
            count += len(matches)
        return count

    def _detect_exit_signal(self, text: str) -> bool:
        """检测 Agent 是否输出了明确的 EXIT_SIGNAL

        支持两种格式:
        1. EXIT_SIGNAL: true (独立行)
        2. RALPH_STATUS 块中的 EXIT_SIGNAL (frankbria 格式)
        """
        if EXIT_SIGNAL_PATTERN.search(text):
            return True

        match = RALPH_STATUS_PATTERN.search(text)
        if match:
            signal_value = match.group(1).lower()
            return signal_value == "true"

        return False
