"""测试 exit_detector.py — 退出检测"""

from autoc.core.analysis.exit_detector import ExitDetector, ExitReason


class TestExitDetector:
    """双条件退出门控测试"""

    def test_no_exit_by_default(self):
        ed = ExitDetector()
        result = ed.analyze("working on it...")
        assert not result.should_exit

    def test_all_stories_passed_exits(self):
        ed = ExitDetector()
        result = ed.analyze("done", all_stories_passed=True)
        assert result.should_exit
        assert result.reason == ExitReason.ALL_STORIES_PASSED

    def test_plan_complete_exit(self):
        """增量规划完成: 所有通过 + 规划完成 → PLAN_COMPLETE"""
        ed = ExitDetector()
        result = ed.analyze("done", all_stories_passed=True, plan_complete=True)
        assert result.should_exit
        assert result.reason == ExitReason.PLAN_COMPLETE

    def test_plan_not_complete_no_early_exit(self):
        """如果 plan 未完成但 stories 全通过 → ALL_STORIES_PASSED"""
        ed = ExitDetector()
        result = ed.analyze("done", all_stories_passed=True, plan_complete=False)
        assert result.should_exit
        assert result.reason == ExitReason.ALL_STORIES_PASSED

    def test_max_iterations_triggers_exit(self):
        """iteration >= max_iterations → 退出"""
        ed = ExitDetector()
        result = ed.analyze("", iteration=20, max_iterations=20)
        assert result.should_exit
        assert result.reason == ExitReason.MAX_ITERATIONS

    def test_max_iterations_not_reached(self):
        """iteration < max_iterations → 不退出"""
        ed = ExitDetector()
        result = ed.analyze("", iteration=10, max_iterations=20)
        assert not result.should_exit

    def test_exit_signal_with_indicators(self):
        """双条件门控: completion_indicators + EXIT_SIGNAL: true"""
        ed = ExitDetector(completion_threshold=1)
        result = ed.analyze("all tasks complete EXIT_SIGNAL: true")
        assert result.should_exit
        assert result.reason == ExitReason.PROJECT_COMPLETE

    def test_exit_signal_alone_not_enough(self):
        """只有 EXIT_SIGNAL 无 completion indicators → 不退出"""
        ed = ExitDetector()
        result = ed.analyze("still working EXIT_SIGNAL: true")
        assert not result.should_exit

    def test_consecutive_done_patterns(self):
        """连续 N 轮有完成指标 → CONSECUTIVE_DONE"""
        ed = ExitDetector(max_consecutive_done=2)
        ed.analyze("all tasks complete, project is done")
        result = ed.analyze("project is complete, all tests passed")
        assert result.should_exit
        assert result.reason == ExitReason.CONSECUTIVE_DONE

    def test_reset_clears_state(self):
        ed = ExitDetector()
        ed.analyze("all tasks complete")
        ed.reset()
        result = ed.analyze("working...")
        assert not result.should_exit
