"""ConversationStore 单元测试"""

import json
import os
import tempfile
import time

import pytest

from autoc.core.conversation.store import ConversationStore, ConversationSnapshot


class TestConversationStore:
    """基础功能测试"""

    def _make_store(self, tmpdir, **kwargs):
        return ConversationStore(
            str(tmpdir), session_id="test-session", **kwargs,
        )

    def test_save_and_load_snapshot(self, tmp_path):
        store = self._make_store(tmp_path)
        history = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        snap = store.save_snapshot("main", history, iteration=1)

        assert snap.agent == "main"
        assert snap.iteration == 1
        assert snap.message_count == 3
        assert snap.snapshot_id == "snap-0001"

        loaded = store.load_latest("main")
        assert loaded is not None
        assert loaded.snapshot_id == "snap-0001"
        assert len(loaded.messages) == 3

    def test_load_latest_empty(self, tmp_path):
        store = self._make_store(tmp_path)
        assert store.load_latest("main") is None

    def test_list_snapshots_filter_by_agent(self, tmp_path):
        store = self._make_store(tmp_path)
        store.save_snapshot("main", [{"role": "user", "content": "a"}])
        store.save_snapshot("helper", [{"role": "user", "content": "b"}])
        store.save_snapshot("main", [{"role": "user", "content": "c"}])

        main_snaps = store.list_snapshots("main")
        assert len(main_snaps) == 2

        planner_snaps = store.list_snapshots("helper")
        assert len(planner_snaps) == 1

        all_snaps = store.list_snapshots()
        assert len(all_snaps) == 3

    def test_load_by_iteration(self, tmp_path):
        store = self._make_store(tmp_path)
        store.save_snapshot("main", [{"role": "user", "content": "iter1"}], iteration=1)
        store.save_snapshot("main", [{"role": "user", "content": "iter2"}], iteration=2)
        store.save_snapshot("main", [{"role": "user", "content": "iter3"}], iteration=3)

        snap = store.load_by_iteration("main", 2)
        assert snap is not None
        assert snap.iteration == 2

        assert store.load_by_iteration("main", 99) is None


class TestDebounce:
    """Debounce 策略测试"""

    def test_debounce_by_message_count(self, tmp_path):
        store = ConversationStore(
            str(tmp_path), session_id="test",
            debounce_messages=3, debounce_seconds=9999,
        )
        msgs = [{"role": "user", "content": "a"}]

        # 首次保存（无 debounce 状态）：time_elapsed=True（last_ts=0 → now-0 >= 9999? False）
        # 但 msgs_changed = 1-0 >= 3? False → 不保存
        # 实际首次 last_ts=0, now-0 远大于 9999 → True → 保存
        saved = store.maybe_save("main", msgs)
        assert saved is True  # 首次保存（时间条件满足）

        msgs_2 = msgs + [{"role": "assistant", "content": "b"}]
        saved = store.maybe_save("main", msgs_2)
        assert saved is False  # 只增加了 1 条，不到 3 条

        msgs_5 = msgs_2 + [
            {"role": "user", "content": "c"},
            {"role": "assistant", "content": "d"},
            {"role": "user", "content": "e"},
        ]
        saved = store.maybe_save("main", msgs_5)
        assert saved is True  # 增加了 4 条 >= 3

    def test_debounce_by_time(self, tmp_path):
        store = ConversationStore(
            str(tmp_path), session_id="test",
            debounce_messages=9999, debounce_seconds=0.1,
        )
        msgs = [{"role": "user", "content": "a"}]

        # 首次：last_ts=0, time_elapsed=True
        store.maybe_save("main", msgs)

        # 立刻再存：时间不够
        saved = store.maybe_save("main", msgs + [{"role": "assistant", "content": "b"}])
        assert saved is False

        time.sleep(0.15)
        saved = store.maybe_save("main", msgs + [{"role": "assistant", "content": "b"}])
        assert saved is True


class TestSanitize:
    """消息清理测试"""

    def test_tool_result_truncation(self, tmp_path):
        store = ConversationStore(str(tmp_path), session_id="test")
        long_result = "x" * 5000
        msgs = [{"role": "tool", "content": long_result}]
        snap = store.save_snapshot("main", msgs)

        assert len(snap.messages[0]["content"]) < 2100

    def test_reasoning_content_truncation(self, tmp_path):
        store = ConversationStore(str(tmp_path), session_id="test")
        long_rc = "think " * 200
        msgs = [{"role": "assistant", "content": "ok", "reasoning_content": long_rc}]
        snap = store.save_snapshot("main", msgs)

        assert len(snap.messages[0]["reasoning_content"]) <= 500


class TestResumeContext:
    """断点续传上下文测试"""

    def test_get_resume_context(self, tmp_path):
        store = ConversationStore(str(tmp_path), session_id="test")
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "task"},
            {"role": "assistant", "content": "I will write the code."},
            {"role": "tool", "content": "file written ok"},
            {"role": "assistant", "content": "Done!"},
        ]
        store.save_snapshot("main", msgs, iteration=5, metadata={"task_id": "T1"})

        ctx = store.get_resume_context("main")
        assert ctx is not None
        assert ctx["iteration"] == 5
        assert ctx["message_count"] == 5
        assert "Done!" in ctx["recent_context"]
        assert ctx["metadata"]["task_id"] == "T1"

    def test_get_resume_context_empty(self, tmp_path):
        store = ConversationStore(str(tmp_path), session_id="test")
        assert store.get_resume_context("main") is None


class TestPersistence:
    """持久化 JSONL 格式测试"""

    def test_jsonl_format(self, tmp_path):
        store = ConversationStore(str(tmp_path), session_id="test")
        store.save_snapshot("main", [{"role": "user", "content": "hello"}])
        store.save_snapshot("main", [{"role": "user", "content": "world"}])

        log_file = tmp_path / "test.jsonl"
        assert log_file.exists()

        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 2

        data = json.loads(lines[0])
        assert data["agent"] == "main"
        assert data["snapshot_id"] == "snap-0001"

    def test_stats(self, tmp_path):
        store = ConversationStore(str(tmp_path), session_id="test")
        store.save_snapshot("main", [{"role": "user", "content": "a"}])
        store.save_snapshot("helper", [{"role": "user", "content": "b"}])
        store.save_snapshot("main", [{"role": "user", "content": "c"}])

        stats = store.stats
        assert stats["total_snapshots"] == 3
        assert stats["by_agent"]["main"] == 2
        assert stats["by_agent"]["helper"] == 1


class TestConcurrency:
    """线程安全测试"""

    def test_concurrent_saves(self, tmp_path):
        import threading

        store = ConversationStore(str(tmp_path), session_id="test")
        errors = []

        def save_many(agent_name, count):
            try:
                for i in range(count):
                    store.save_snapshot(
                        agent_name,
                        [{"role": "user", "content": f"msg-{i}"}],
                        iteration=i,
                    )
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=save_many, args=("main", 20)),
            threading.Thread(target=save_many, args=("helper", 20)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        all_snaps = store.list_snapshots()
        assert len(all_snaps) == 40
