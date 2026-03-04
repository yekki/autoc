"""Stuck Detector 单元测试"""
import pytest
from autoc.core.infra.stuck_detector import StuckDetector, StuckPattern


class TestRepeatCallDetection:
    """连续相同工具+参数调用检测"""

    def test_no_stuck_below_threshold(self):
        d = StuckDetector(repeat_threshold=3)
        d.record("read_file", {"path": "a.py"}, "content")
        d.record("read_file", {"path": "a.py"}, "content")
        stuck, signal = d.check()
        assert stuck is False

    def test_stuck_at_threshold(self):
        d = StuckDetector(repeat_threshold=3)
        for _ in range(3):
            d.record("read_file", {"path": "a.py"}, "content")
        stuck, signal = d.check()
        assert stuck is True
        assert signal.pattern == StuckPattern.REPEAT_CALL
        assert "read_file" in signal.description

    def test_different_args_not_stuck(self):
        d = StuckDetector(repeat_threshold=3)
        d.record("read_file", {"path": "a.py"}, "content a")
        d.record("read_file", {"path": "b.py"}, "content b")
        d.record("read_file", {"path": "c.py"}, "content c")
        stuck, _ = d.check()
        assert stuck is False

    def test_different_tools_not_stuck(self):
        d = StuckDetector(repeat_threshold=3)
        d.record("read_file", {"path": "a.py"}, "ok")
        d.record("write_file", {"path": "a.py", "content": "x"}, "ok")
        d.record("read_file", {"path": "a.py"}, "ok")
        stuck, _ = d.check()
        assert stuck is False


class TestCyclicPatternDetection:
    """循环模式检测 A→B→A→B"""

    def test_simple_cycle(self):
        d = StuckDetector(cycle_threshold=2)
        for _ in range(3):
            d.record("read_file", {"path": "a.py"}, "ok")
            d.record("write_file", {"path": "a.py", "content": "x"}, "ok")
        stuck, signal = d.check()
        assert stuck is True
        assert signal.pattern == StuckPattern.CYCLIC_PATTERN

    def test_three_step_cycle(self):
        d = StuckDetector(cycle_threshold=2)
        for _ in range(3):
            d.record("read_file", {"path": "a.py"}, "ok")
            d.record("execute_command", {"command": "pytest"}, "ok")
            d.record("write_file", {"path": "a.py", "content": "x"}, "ok")
        stuck, signal = d.check()
        assert stuck is True
        assert signal.pattern == StuckPattern.CYCLIC_PATTERN

    def test_no_cycle_with_variation(self):
        d = StuckDetector(cycle_threshold=2)
        d.record("read_file", {"path": "a.py"}, "ok")
        d.record("write_file", {"path": "a.py", "content": "x"}, "ok")
        d.record("execute_command", {"command": "pytest"}, "ok")
        d.record("read_file", {"path": "b.py"}, "ok")
        stuck, _ = d.check()
        assert stuck is False


class TestErrorRepeatDetection:
    """相同错误重复检测"""

    def test_same_error_repeated(self):
        d = StuckDetector(error_repeat_threshold=3)
        error = "[错误] ModuleNotFoundError: No module named 'flask'"
        for i in range(3):
            d.record("execute_command", {"command": f"python app{i}.py"},
                     error, has_error=True, error_message=error)
        stuck, signal = d.check()
        assert stuck is True
        assert signal.pattern == StuckPattern.ERROR_REPEAT

    def test_different_errors_not_stuck(self):
        d = StuckDetector(error_repeat_threshold=3)
        for i in range(3):
            error = f"[错误] Error type {i}"
            d.record("execute_command", {"command": f"cmd_{i}"},
                     error, has_error=True, error_message=error)
        stuck, signal = d.check()
        if stuck:
            assert signal.pattern != StuckPattern.ERROR_REPEAT

    def test_errors_mixed_with_success(self):
        d = StuckDetector(error_repeat_threshold=3)
        error = "[错误] SomeError"
        d.record("execute_command", {"command": "x"}, error,
                 has_error=True, error_message=error)
        d.record("read_file", {"path": "a.py"}, "ok")
        d.record("execute_command", {"command": "x"}, error,
                 has_error=True, error_message=error)
        stuck, _ = d.check()
        assert stuck is False


class TestEmptyOutputDetection:
    """连续无写操作检测"""

    def test_all_reads_detected(self):
        d = StuckDetector(empty_output_threshold=5)
        for i in range(5):
            d.record("read_file", {"path": f"file{i}.py"}, "content")
        stuck, signal = d.check()
        assert stuck is True
        assert signal.pattern == StuckPattern.EMPTY_OUTPUT

    def test_write_resets_counter(self):
        d = StuckDetector(empty_output_threshold=5)
        for i in range(4):
            d.record("read_file", {"path": f"file{i}.py"}, "content")
        d.record("write_file", {"path": "out.py", "content": "x"}, "ok")
        stuck, _ = d.check()
        assert stuck is False

    def test_submit_critique_counts_as_write(self):
        """submit_critique 是评审产出，应视为写操作"""
        d = StuckDetector(empty_output_threshold=5)
        for i in range(4):
            d.record("read_file", {"path": f"file{i}.py"}, "content")
        d.record("submit_critique", {"scores": {}, "summary": "ok"}, "ok")
        stuck, _ = d.check()
        assert stuck is False

    def test_submit_test_report_counts_as_write(self):
        d = StuckDetector(empty_output_threshold=5)
        for i in range(4):
            d.record("read_file", {"path": f"file{i}.py"}, "content")
        d.record("submit_test_report", {"passed": True}, "ok")
        stuck, _ = d.check()
        assert stuck is False


class TestResetAndStats:
    """重置和统计"""

    def test_reset_clears_records(self):
        d = StuckDetector(repeat_threshold=3)
        for _ in range(3):
            d.record("read_file", {"path": "a.py"}, "ok")
        d.reset()
        stuck, _ = d.check()
        assert stuck is False

    def test_stats(self):
        d = StuckDetector(repeat_threshold=3)
        for _ in range(3):
            d.record("read_file", {"path": "a.py"}, "ok")
        d.check()
        stats = d.stats
        assert stats["total_records"] == 3
        assert stats["total_checks"] == 1
        assert stats["total_stuck"] == 1

    def test_window_size_pruning(self):
        d = StuckDetector(window_size=5)
        for i in range(15):
            d.record("read_file", {"path": f"file{i}.py"}, "content")
        assert len(d._records) <= 10


class TestDetectionPriority:
    """多种模式同时满足时的优先级：repeat > cycle > error > empty"""

    def test_repeat_takes_priority(self):
        d = StuckDetector(repeat_threshold=3, empty_output_threshold=3)
        for _ in range(5):
            d.record("read_file", {"path": "a.py"}, "ok")
        stuck, signal = d.check()
        assert stuck is True
        assert signal.pattern == StuckPattern.REPEAT_CALL
