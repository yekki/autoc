"""测试 session_registry.py — 会话注册 + 过期检测"""

import time

from autoc.core.runtime.session_registry import SessionRegistry


class TestSessionExpiry:
    """24h 会话过期测试（Ralph 特性）"""

    def test_not_expired_fresh(self, tmp_workspace):
        reg = SessionRegistry(tmp_workspace, expiry_hours=24)
        session = {"status": "running", "started_at": time.time()}
        assert not reg.is_expired(session)

    def test_expired_old(self, tmp_workspace):
        reg = SessionRegistry(tmp_workspace, expiry_hours=0.001)
        session = {"status": "running", "started_at": time.time() - 100}
        assert reg.is_expired(session)

    def test_finished_never_expired(self, tmp_workspace):
        reg = SessionRegistry(tmp_workspace, expiry_hours=0.001)
        session = {"status": "completed", "started_at": time.time() - 100}
        assert not reg.is_expired(session)


class TestSessionRegistry:
    """会话注册表基本功能"""

    def test_register_and_get(self, tmp_workspace):
        reg = SessionRegistry(tmp_workspace)
        reg.register("s1", "test requirement", workspace_dir=tmp_workspace)
        session = reg.get("s1")
        assert session is not None
        assert session["requirement"] == "test requirement"

    def test_update(self, tmp_workspace):
        reg = SessionRegistry(tmp_workspace)
        reg.register("s2", "req")
        reg.update("s2", status="completed")
        session = reg.get("s2")
        assert session["status"] == "completed"

    def test_delete(self, tmp_workspace):
        reg = SessionRegistry(tmp_workspace)
        reg.register("s3", "req")
        assert reg.delete("s3")
        assert reg.get("s3") is None

    def test_list_all(self, tmp_workspace):
        reg = SessionRegistry(tmp_workspace)
        reg.register("s4", "r1")
        reg.register("s5", "r2")
        sessions = reg.list_all(check_alive=False)
        assert len(sessions) >= 2

    def test_clear(self, tmp_workspace):
        reg = SessionRegistry(tmp_workspace)
        reg.register("s6", "r")
        reg.update("s6", status="completed")
        count = reg.clear(only_finished=True)
        assert count >= 1
