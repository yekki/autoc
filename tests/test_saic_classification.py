"""SAIC 阶段分类与进度检测测试

覆盖: base.py 中的 _classify_tool_phase() 全部分支、
      _check_progress() 四级提醒 + 降级逻辑。
"""

from tests.conftest import _build_minimal_agent


class TestClassifyToolPhase:
    """_classify_tool_phase() 工具阶段分类"""

    def _classify(self, tool_name, tmp_path):
        ws = str(tmp_path / "ws")
        import os
        os.makedirs(ws, exist_ok=True)
        from unittest.mock import MagicMock
        agent = _build_minimal_agent(ws, MagicMock())
        return agent._classify_tool_phase(tool_name)

    def test_builtin_read_file_is_explore(self, tmp_path):
        assert self._classify("read_file", tmp_path) == "explore"

    def test_builtin_write_file_is_produce(self, tmp_path):
        assert self._classify("write_file", tmp_path) == "produce"

    def test_builtin_execute_command_is_execute(self, tmp_path):
        assert self._classify("execute_command", tmp_path) == "execute"

    def test_slash_tool_defaults_to_execute(self, tmp_path):
        """slash 格式的未知工具统一归为 execute"""
        assert self._classify("context7/resolve-library-id", tmp_path) == "execute"
        assert self._classify("filesystem/read_file", tmp_path) == "execute"
        assert self._classify("filesystem/write_file", tmp_path) == "execute"
        assert self._classify("playwright/screenshot", tmp_path) == "execute"

    def test_ask_helper_is_explore(self, tmp_path):
        assert self._classify("ask_helper", tmp_path) == "explore"

    def test_unknown_tool_defaults_to_execute(self, tmp_path):
        assert self._classify("random_tool_xyz", tmp_path) == "execute"


class TestCheckProgress:
    """_check_progress() 四级提醒"""

    def _make_agent(self, tmp_path, max_iters=10):
        import os
        from unittest.mock import MagicMock
        ws = str(tmp_path / "ws")
        os.makedirs(ws, exist_ok=True)
        return _build_minimal_agent(ws, MagicMock(), max_iterations=max_iters)

    def test_budget_too_small_no_check(self, tmp_path):
        """max_iterations=2 时不触发任何检查"""
        agent = self._make_agent(tmp_path, max_iters=2)
        agent._iteration_count = 1
        agent._phase_counts = {"explore": 1}
        msg, degrade = agent._check_progress()
        assert msg is None
        assert degrade is False

    def test_level1_nudge_pure_explore(self, tmp_path):
        """预算过半 + 纯探索 → Level 1 温和提醒"""
        agent = self._make_agent(tmp_path, max_iters=10)
        agent._initial_max_iterations = 10
        agent._iteration_count = 6
        agent._phase_counts = {"explore": 6}
        agent._nudge_level = 0
        agent._recent_tools = []
        msg, degrade = agent._check_progress()
        assert msg is not None
        assert "进度提醒" in msg
        assert agent._nudge_level == 1

    def test_level2_warn_budget_exhausting(self, tmp_path):
        """预算 75%+ → Level 2 强烈警告"""
        agent = self._make_agent(tmp_path, max_iters=10)
        agent._initial_max_iterations = 10
        agent._iteration_count = 8
        agent._phase_counts = {"explore": 5, "produce": 3}
        agent._nudge_level = 0
        agent._recent_tools = []
        msg, degrade = agent._check_progress()
        assert msg is not None
        assert "耗尽" in msg
        assert agent._nudge_level == 2

    def test_degrade_at_70pct(self, tmp_path):
        """预算 70%+ → should_degrade=True"""
        agent = self._make_agent(tmp_path, max_iters=10)
        agent._initial_max_iterations = 10
        agent._iteration_count = 8
        agent._phase_counts = {"explore": 5, "produce": 3}
        agent._nudge_level = 0
        agent._recent_tools = []
        _, degrade = agent._check_progress()
        assert degrade is True

    def test_level3_repeat_detection(self, tmp_path):
        """连续 3 次相同工具 → 重复操作警告"""
        agent = self._make_agent(tmp_path, max_iters=10)
        agent._initial_max_iterations = 10
        agent._iteration_count = 3
        agent._phase_counts = {"explore": 3}
        agent._nudge_level = 0
        agent._recent_tools = [
            ("read_file", "main.py"),
            ("read_file", "main.py"),
            ("read_file", "main.py"),
        ]
        msg, _ = agent._check_progress()
        assert msg is not None
        assert "重复操作" in msg
