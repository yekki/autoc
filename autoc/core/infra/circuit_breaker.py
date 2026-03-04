"""Circuit Breaker — 熔断器 + 速率限制

融合 frankbria/ralph-claude-code 的熔断器设计:
- 三态状态机: CLOSED → OPEN → HALF_OPEN → CLOSED
- 多维度触发: 无进度 / 重复错误 / 产出下降
- 自动恢复: 冷却后探测性重试
- 速率限制: 可配置的小时级 API 调用上限
"""

import logging
import time
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("autoc.circuit_breaker")


class BreakerState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class IterationRecord:
    """单次迭代的记录 (供熔断器分析)

    参考 Ralph v0.11.4：git commit 也算作有效进度信号。
    """
    iteration: int
    timestamp: float = field(default_factory=time.time)
    files_changed: int = 0
    git_committed: bool = False
    has_error: bool = False
    error_message: str = ""
    agent_output_length: int = 0
    story_id: str = ""
    story_passed: bool = False
    phase: str = ""
    bug_fixed: bool = False

    @property
    def has_progress(self) -> bool:
        """判断本轮是否有实质进度（文件变更 / git 提交 / Bug 修复均算）"""
        return (self.files_changed > 0 or self.git_committed
                or self.story_passed or self.bug_fixed)


class CircuitBreaker:
    """熔断器 — 防止 Ralph Loop 无限循环

    三态状态机:
      CLOSED → 正常执行
      OPEN → 熔断, 拒绝执行 (等待冷却)
      HALF_OPEN → 探测性执行一轮, 成功则 CLOSED, 失败则 OPEN

    触发条件 (from frankbria/ralph-claude-code):
      - 连续 N 轮无进度 (无文件变更)
      - 连续 N 轮相同错误
      - 产出量下降超过阈值
    """

    def __init__(
        self,
        no_progress_threshold: int = 5,
        same_error_threshold: int = 5,
        output_decline_threshold: float = 0.7,
        cooldown_seconds: int = 300,
        auto_reset: bool = False,
    ):
        self.no_progress_threshold = no_progress_threshold
        self.same_error_threshold = same_error_threshold
        self.output_decline_threshold = output_decline_threshold
        self.cooldown_seconds = cooldown_seconds

        self._state = BreakerState.CLOSED
        self._opened_at: float = 0
        self._records: list[IterationRecord] = []
        self._state_history: list[tuple[float, BreakerState, str]] = []

        if auto_reset:
            self._transition(BreakerState.CLOSED, "auto_reset on startup")

    @property
    def state(self) -> BreakerState:
        """惰性状态访问器：读取时顺带检查 cooldown。
        这是熔断器的标准模式（lazy transition）：OPEN 状态到期自动转 HALF_OPEN，
        避免外部调用方需要知道 cooldown 细节。
        """
        if self._state == BreakerState.OPEN:
            elapsed = time.time() - self._opened_at
            if elapsed >= self.cooldown_seconds:
                self._transition(BreakerState.HALF_OPEN, "cooldown expired")
        return self._state

    def is_open(self) -> bool:
        return self.state == BreakerState.OPEN

    def is_closed(self) -> bool:
        """允许继续执行（CLOSED 或 HALF_OPEN 探测状态）"""
        return self.state in (BreakerState.CLOSED, BreakerState.HALF_OPEN)

    def can_proceed(self) -> bool:
        """允许继续执行（is_closed 的语义更清晰的别名）"""
        return self.is_closed()

    def record(self, record: IterationRecord):
        """记录一次迭代结果, 并评估是否需要熔断"""
        self._records.append(record)

        if self._state == BreakerState.HALF_OPEN:
            if record.has_progress:
                self._transition(BreakerState.CLOSED, "half_open probe succeeded")
            else:
                self._transition(BreakerState.OPEN, "half_open probe failed")
            return

        if self._state == BreakerState.CLOSED:
            reason = self._evaluate_breaker()
            if reason:
                self._transition(BreakerState.OPEN, reason)

    def reset(self, reason: str = "manual_reset"):
        self._transition(BreakerState.CLOSED, reason)
        self._records.clear()

    def get_status(self) -> dict:
        return {
            "state": self._state.value,
            "records_count": len(self._records),
            "recent_errors": self._count_recent_errors(),
            "recent_no_progress": self._count_recent_no_progress(),
            "history": [
                {"time": t, "state": s.value, "reason": r}
                for t, s, r in self._state_history[-10:]
            ],
        }

    # ==================== 内部逻辑 ====================

    def _transition(self, new_state: BreakerState, reason: str):
        old = self._state
        self._state = new_state
        self._state_history.append((time.time(), new_state, reason))
        if new_state == BreakerState.OPEN:
            self._opened_at = time.time()
        logger.info(f"熔断器状态变更: {old.value} → {new_state.value} ({reason})")

    def _evaluate_breaker(self) -> str:
        """评估是否应触发熔断, 返回原因或空字符串"""
        if len(self._records) < self.no_progress_threshold:
            return ""

        # 检查连续无进度
        no_progress_count = self._count_recent_no_progress()
        if no_progress_count >= self.no_progress_threshold:
            return f"连续 {no_progress_count} 轮无进度"

        # 检查连续相同错误
        same_error_count = self._count_recent_same_errors()
        if same_error_count >= self.same_error_threshold:
            return f"连续 {same_error_count} 轮相同错误"

        # 检查产出量下降
        if len(self._records) >= 4:
            decline = self._compute_output_decline()
            if decline > self.output_decline_threshold:
                return f"产出量下降 {decline:.0%}"

        return ""

    def _count_recent_no_progress(self) -> int:
        """连续无进度计数（参考 Ralph：git commit 也算进度）"""
        count = 0
        for record in reversed(self._records):
            if not record.has_progress:
                count += 1
            else:
                break
        return count

    def _count_recent_errors(self) -> int:
        count = 0
        for record in reversed(self._records):
            if record.has_error:
                count += 1
            else:
                break
        return count

    def _count_recent_same_errors(self) -> int:
        if not self._records:
            return 0
        recent_errors = []
        for record in reversed(self._records):
            if record.has_error and record.error_message:
                recent_errors.append(record.error_message)
            else:
                break
        if len(recent_errors) < 2:
            return 0
        first = recent_errors[0]
        return sum(1 for e in recent_errors if e == first)

    def _compute_output_decline(self) -> float:
        """比较同 phase 的前后两半产出量，跨 phase 不比较（TEST 天然比 DEV 短）

        仅统计有实际文件产出的迭代（空产出的 "虚假完成" 不纳入基准计算），
        避免 smoke check → 重做场景误判为产出骤降。
        """
        if len(self._records) < 6:
            return 0.0
        latest_phase = self._records[-1].phase
        same_phase = [
            r for r in self._records
            if r.phase == latest_phase and r.files_changed > 0
        ]
        if len(same_phase) < 4:
            return 0.0
        first_half = same_phase[:len(same_phase) // 2]
        second_half = same_phase[len(same_phase) // 2:]
        avg_first = sum(r.agent_output_length for r in first_half) / len(first_half) if first_half else 1
        avg_second = sum(r.agent_output_length for r in second_half) / len(second_half) if second_half else 0
        if avg_first <= 0:
            return 0.0
        return max(0.0, 1.0 - avg_second / avg_first)


class RateLimiter:
    """速率限制器 — 控制 API 调用频率

    参考 frankbria/ralph-claude-code 的 rate limiting 设计:
    - 基于时间窗口的调用计数
    - 可配置的每小时上限
    - 超限时自动等待
    """

    def __init__(self, max_calls_per_hour: int = 100):
        self.max_calls_per_hour = max_calls_per_hour
        self._call_timestamps: list[float] = []

    def can_proceed(self) -> bool:
        self._prune_old_calls()
        return len(self._call_timestamps) < self.max_calls_per_hour

    def record_call(self):
        self._call_timestamps.append(time.time())
        # 定期裁剪，防止短时间大量调用导致列表无限增长
        if len(self._call_timestamps) > self.max_calls_per_hour * 2:
            self._prune_old_calls()

    def wait_time_seconds(self) -> float:
        """如果超限, 返回需要等待的秒数"""
        self._prune_old_calls()
        if len(self._call_timestamps) < self.max_calls_per_hour:
            return 0.0
        oldest = self._call_timestamps[0]
        return max(0.0, 3600.0 - (time.time() - oldest))

    def usage_info(self) -> dict:
        self._prune_old_calls()
        return {
            "calls_this_hour": len(self._call_timestamps),
            "max_per_hour": self.max_calls_per_hour,
            "remaining": max(0, self.max_calls_per_hour - len(self._call_timestamps)),
        }

    def _prune_old_calls(self):
        cutoff = time.time() - 3600.0
        self._call_timestamps = [t for t in self._call_timestamps if t > cutoff]
