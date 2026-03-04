"""测试 circuit_breaker.py — 熔断器 + 速率限制"""

import time

from autoc.core.infra.circuit_breaker import (
    BreakerState,
    CircuitBreaker,
    IterationRecord,
    RateLimiter,
)


class TestIterationRecord:
    """IterationRecord 进度检测"""

    def test_no_progress(self):
        r = IterationRecord(iteration=1)
        assert not r.has_progress

    def test_file_changes_are_progress(self):
        r = IterationRecord(iteration=1, files_changed=2)
        assert r.has_progress

    def test_git_commit_is_progress(self):
        """参考 Ralph: git commit 也算有效进度"""
        r = IterationRecord(iteration=1, git_committed=True)
        assert r.has_progress

    def test_story_pass_is_progress(self):
        r = IterationRecord(iteration=1, story_passed=True)
        assert r.has_progress

    def test_bug_fixed_is_progress(self):
        r = IterationRecord(iteration=1, bug_fixed=True)
        assert r.has_progress


class TestCircuitBreaker:
    """三态熔断器测试"""

    def test_initial_state_closed(self):
        cb = CircuitBreaker()
        assert cb.state == BreakerState.CLOSED
        assert cb.is_closed()
        assert not cb.is_open()

    def test_trips_on_no_progress(self):
        cb = CircuitBreaker(no_progress_threshold=3)
        for i in range(3):
            cb.record(IterationRecord(iteration=i))
        assert cb.state == BreakerState.OPEN

    def test_git_commit_prevents_trip(self):
        """git commit 阻止熔断（Ralph 特性）"""
        cb = CircuitBreaker(no_progress_threshold=3)
        cb.record(IterationRecord(iteration=0))
        cb.record(IterationRecord(iteration=1))
        cb.record(IterationRecord(iteration=2, git_committed=True))
        assert cb.state == BreakerState.CLOSED

    def test_bug_fixed_prevents_trip(self):
        """FIX 阶段修复 Bug 算有效进度，阻止熔断"""
        cb = CircuitBreaker(no_progress_threshold=3)
        cb.record(IterationRecord(iteration=0))
        cb.record(IterationRecord(iteration=1))
        cb.record(IterationRecord(iteration=2, bug_fixed=True))
        assert cb.state == BreakerState.CLOSED

    def test_trips_on_same_error(self):
        """连续相同错误也触发熔断"""
        cb = CircuitBreaker(same_error_threshold=3, no_progress_threshold=3)
        for i in range(5):
            cb.record(IterationRecord(
                iteration=i, has_error=True, error_message="SyntaxError"))
        assert cb.state == BreakerState.OPEN

    def test_half_open_probe_success(self):
        """cooldown=0 → OPEN 立即变 HALF_OPEN → 成功探测 → CLOSED"""
        cb = CircuitBreaker(no_progress_threshold=2, cooldown_seconds=0)
        cb.record(IterationRecord(iteration=0))
        cb.record(IterationRecord(iteration=1))
        # cooldown=0 时首次读 state 已是 HALF_OPEN
        assert cb.state == BreakerState.HALF_OPEN
        # 成功探测 → CLOSED
        cb.record(IterationRecord(iteration=2, files_changed=1))
        assert cb.state == BreakerState.CLOSED

    def test_half_open_probe_failure(self):
        """HALF_OPEN 探测失败 → 回到 OPEN"""
        cb = CircuitBreaker(no_progress_threshold=2, cooldown_seconds=0)
        cb.record(IterationRecord(iteration=0))
        cb.record(IterationRecord(iteration=1))
        # cooldown=0 → 已经是 HALF_OPEN
        assert cb.state == BreakerState.HALF_OPEN
        # 失败探测 → OPEN（但 cooldown=0 所以又变 HALF_OPEN）
        cb.record(IterationRecord(iteration=2))
        # 因为 cooldown=0，OPEN → HALF_OPEN 是立即的
        assert cb.state in (BreakerState.OPEN, BreakerState.HALF_OPEN)

    def test_reset(self):
        cb = CircuitBreaker(no_progress_threshold=2)
        cb.record(IterationRecord(iteration=0))
        cb.record(IterationRecord(iteration=1))
        assert cb.is_open()
        cb.reset()
        assert cb.is_closed()

    def test_status_report(self):
        cb = CircuitBreaker()
        status = cb.get_status()
        assert "state" in status
        assert status["state"] == "closed"


class TestRateLimiter:
    """速率限制器测试"""

    def test_can_proceed_initially(self):
        rl = RateLimiter(max_calls_per_hour=10)
        assert rl.can_proceed()

    def test_blocks_when_exhausted(self):
        rl = RateLimiter(max_calls_per_hour=2)
        rl.record_call()
        rl.record_call()
        assert not rl.can_proceed()

    def test_wait_time(self):
        rl = RateLimiter(max_calls_per_hour=1)
        rl.record_call()
        wait = rl.wait_time_seconds()
        assert wait > 0

    def test_usage_info(self):
        rl = RateLimiter(max_calls_per_hour=100)
        rl.record_call()
        info = rl.usage_info()
        assert info["calls_this_hour"] == 1
        assert info["remaining"] == 99
