"""EventLog 单元测试"""
import os
import time
import tempfile
import pytest
from autoc.core.event.event_log import EventLog, Event


@pytest.fixture
def tmp_log_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


class TestEventLogBasic:
    """基本读写"""

    def test_append_and_query(self, tmp_log_dir):
        log = EventLog(tmp_log_dir, session_id="test-1")
        log.append("tool_call", agent="main", data={"tool": "read_file"})
        log.append("tool_result", agent="main", data={"result": "ok"})

        events = log.query()
        assert len(events) == 2
        assert events[0].type == "tool_call"
        assert events[1].type == "tool_result"

    def test_session_id(self, tmp_log_dir):
        log = EventLog(tmp_log_dir, session_id="my-session")
        assert log.session_id == "my-session"


class TestEventLogQuery:
    """查询过滤"""

    def test_filter_by_type(self, tmp_log_dir):
        log = EventLog(tmp_log_dir, session_id="q-1")
        log.append("tool_call", agent="main")
        log.append("tool_result", agent="main")
        log.append("tool_call", agent="helper")

        events = log.query(event_type="tool_call")
        assert len(events) == 2
        assert all(e.type == "tool_call" for e in events)

    def test_filter_by_agent(self, tmp_log_dir):
        log = EventLog(tmp_log_dir, session_id="q-2")
        log.append("a", agent="main")
        log.append("b", agent="helper")
        log.append("c", agent="main")

        events = log.query(agent="main")
        assert len(events) == 2

    def test_filter_by_time(self, tmp_log_dir):
        log = EventLog(tmp_log_dir, session_id="q-3")
        log.append("old_event")
        since = time.time()
        log.append("new_event")

        events = log.query(since=since)
        assert len(events) == 1
        assert events[0].type == "new_event"

    def test_limit(self, tmp_log_dir):
        log = EventLog(tmp_log_dir, session_id="q-4")
        for i in range(20):
            log.append(f"event_{i}")
        events = log.query(limit=5)
        assert len(events) == 5


class TestEventLogPersistence:
    """持久化"""

    def test_flush_creates_file(self, tmp_log_dir):
        log = EventLog(tmp_log_dir, session_id="p-1")
        log.append("test")
        log.flush()
        files = os.listdir(tmp_log_dir)
        assert any(f.endswith(".jsonl") for f in files)

    def test_auto_flush_on_threshold(self, tmp_log_dir):
        log = EventLog(tmp_log_dir, session_id="p-2")
        log._flush_threshold = 3
        log.append("a")
        log.append("b")
        # 不应该触发 flush
        assert log._buffer  # 缓冲区还有数据
        log.append("c")
        # 触发 auto flush
        assert not log._buffer  # 缓冲区已清空


class TestEventLogExport:
    """导出功能"""

    def test_export_for_condenser(self, tmp_log_dir):
        log = EventLog(tmp_log_dir, session_id="e-1")
        log.append("tool_call", agent="main", data={"tool": "read_file"})
        log.append("tool_result", agent="main", data={"ok": True})

        export = log.export_for_condenser()
        assert "[EventLog]" in export
        assert "tool_call" in export
        assert "tool_result" in export

    def test_export_empty(self, tmp_log_dir):
        log = EventLog(tmp_log_dir, session_id="e-2")
        assert log.export_for_condenser() == ""


class TestEventLogStats:
    """统计"""

    def test_stats(self, tmp_log_dir):
        log = EventLog(tmp_log_dir, session_id="s-1")
        log.append("tool_call", agent="main")
        log.append("tool_call", agent="main")
        log.append("tool_result", agent="helper")

        stats = log.stats
        assert stats["total_events"] == 3
        assert stats["by_type"]["tool_call"] == 2
        assert stats["by_type"]["tool_result"] == 1
        assert stats["by_agent"]["main"] == 2
        assert stats["by_agent"]["helper"] == 1

class TestEvent:
    """Event 数据结构"""

    def test_to_dict(self):
        e = Event(ts=1.0, seq=1, type="test", agent="main", data={"key": "val"})
        d = e.to_dict()
        assert d["type"] == "test"
        assert d["data"]["key"] == "val"

    def test_to_json(self):
        e = Event(ts=1.0, seq=1, type="test")
        j = e.to_json()
        assert '"type": "test"' in j
