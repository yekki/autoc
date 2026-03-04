"""后端 SSE 事件分发测试

覆盖：_dispatch_event 核心逻辑 / 事件富化 / 订阅者推送 / done 事件处理
"""

import time
import asyncio
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# helpers: 隔离 sessions 全局状态
# ---------------------------------------------------------------------------

@pytest.fixture
def clean_sessions():
    """每次测试隔离 sessions 字典"""
    import autoc.server as server_mod
    original = server_mod.sessions.copy()
    server_mod.sessions.clear()
    yield server_mod.sessions
    server_mod.sessions.clear()
    server_mod.sessions.update(original)


def _make_session(sid, sessions_dict):
    """在 sessions 字典中注册一个最小化会话"""
    sessions_dict[sid] = {
        "events": [],
        "subscribers": [],
        "status": "running",
        "started_at": time.time(),
    }
    return sessions_dict[sid]


# ======================= _dispatch_event =======================


class TestDispatchEvent:

    @patch("autoc.server._enqueue_db_write")
    @patch("autoc.server.enrich_event")
    def test_event_appended_to_session(self, _enrich, _db, clean_sessions):
        from autoc.server import _dispatch_event

        session = _make_session("s1", clean_sessions)
        _dispatch_event("s1", {"type": "test_event", "data": {"msg": "hello"}})

        assert len(session["events"]) == 1
        assert session["events"][0]["type"] == "test_event"
        assert session["events"][0]["_seq"] == 0

    @patch("autoc.server._enqueue_db_write")
    @patch("autoc.server.enrich_event")
    def test_seq_increments(self, _enrich, _db, clean_sessions):
        from autoc.server import _dispatch_event

        _make_session("s1", clean_sessions)
        _dispatch_event("s1", {"type": "e1"})
        _dispatch_event("s1", {"type": "e2"})
        _dispatch_event("s1", {"type": "e3"})

        events = clean_sessions["s1"]["events"]
        assert [e["_seq"] for e in events] == [0, 1, 2]

    @patch("autoc.server._enqueue_db_write")
    @patch("autoc.server.enrich_event")
    def test_subscribers_receive_events(self, _enrich, _db, clean_sessions):
        from autoc.server import _dispatch_event

        session = _make_session("s1", clean_sessions)
        q = MagicMock()
        session["subscribers"].append(q)

        _dispatch_event("s1", {"type": "test"})

        q.put_nowait.assert_called_once()
        event = q.put_nowait.call_args[0][0]
        assert event["type"] == "test"

    @patch("autoc.server._enqueue_db_write")
    @patch("autoc.server.enrich_event")
    def test_multiple_subscribers(self, _enrich, _db, clean_sessions):
        from autoc.server import _dispatch_event

        session = _make_session("s1", clean_sessions)
        q1, q2 = MagicMock(), MagicMock()
        session["subscribers"].extend([q1, q2])

        _dispatch_event("s1", {"type": "broadcast"})

        q1.put_nowait.assert_called_once()
        q2.put_nowait.assert_called_once()

    @patch("autoc.server._enqueue_db_write")
    @patch("autoc.server.enrich_event")
    def test_subscriber_error_does_not_crash(self, _enrich, _db, clean_sessions):
        from autoc.server import _dispatch_event

        session = _make_session("s1", clean_sessions)
        bad_q = MagicMock()
        bad_q.put_nowait.side_effect = Exception("queue full")
        good_q = MagicMock()
        session["subscribers"].extend([bad_q, good_q])

        _dispatch_event("s1", {"type": "test"})

        good_q.put_nowait.assert_called_once()

    @patch("autoc.server._enqueue_db_write")
    @patch("autoc.server.enrich_event")
    def test_nonexistent_session_noop(self, _enrich, _db, clean_sessions):
        from autoc.server import _dispatch_event
        _dispatch_event("nonexistent", {"type": "test"})
        _db.assert_not_called()

    @patch("autoc.server._enqueue_db_write")
    @patch("autoc.server.enrich_event")
    def test_enrich_event_called(self, mock_enrich, _db, clean_sessions):
        from autoc.server import _dispatch_event
        _make_session("s1", clean_sessions)
        _dispatch_event("s1", {"type": "test"})
        mock_enrich.assert_called_once()

    @patch("autoc.server._enqueue_db_write")
    @patch("autoc.server.enrich_event", side_effect=Exception("enrich error"))
    def test_enrich_failure_does_not_block(self, _enrich, _db, clean_sessions):
        """enrich_event 异常不阻塞事件分发"""
        from autoc.server import _dispatch_event
        session = _make_session("s1", clean_sessions)
        _dispatch_event("s1", {"type": "test"})
        assert len(session["events"]) == 1


# ======================= done 事件特殊处理 =======================


class TestDoneEvent:

    @patch("autoc.server._enqueue_db_write")
    @patch("autoc.server.enrich_event")
    def test_done_success_updates_status(self, _enrich, _db, clean_sessions):
        from autoc.server import _dispatch_event
        session = _make_session("s1", clean_sessions)
        _dispatch_event("s1", {"type": "done", "data": {"success": True}})
        assert session["status"] == "completed"

    @patch("autoc.server._enqueue_db_write")
    @patch("autoc.server.enrich_event")
    def test_done_failure_updates_status(self, _enrich, _db, clean_sessions):
        from autoc.server import _dispatch_event
        session = _make_session("s1", clean_sessions)
        _dispatch_event("s1", {"type": "done", "data": {"success": False}})
        assert session["status"] == "failed"

    @patch("autoc.server._enqueue_db_write")
    @patch("autoc.server.enrich_event")
    def test_done_sets_ended_at(self, _enrich, _db, clean_sessions):
        from autoc.server import _dispatch_event
        session = _make_session("s1", clean_sessions)
        before = time.time()
        _dispatch_event("s1", {"type": "done", "data": {"success": True}})
        assert session["ended_at"] >= before

    @patch("autoc.server._enqueue_db_write")
    @patch("autoc.server.enrich_event")
    def test_has_events_flag_set_once(self, _enrich, _db, clean_sessions):
        """_has_events_set 只在第一次非 heartbeat 事件时设置"""
        from autoc.server import _dispatch_event
        session = _make_session("s1", clean_sessions)
        _dispatch_event("s1", {"type": "heartbeat"})
        assert not session.get("_has_events_set")

        _dispatch_event("s1", {"type": "plan_ready"})
        assert session.get("_has_events_set") is True
