"""会话注册表（SQLite 版）

存储: {autoc_root}/.autoc.db → run_sessions 表

替代原 .autoc_sessions.json；公共 API 完全兼容，调用方无需修改。
"""

import logging
import os
import time
from pathlib import Path
from typing import Optional

from autoc.core.infra.db import GlobalDB

logger = logging.getLogger("autoc.session_registry")

_DEFAULT_ROOT = str(Path(__file__).parent.parent)


class SessionRegistry:
    """基于 SQLite 的轻量级会话注册表，支持跨进程并发读写

    参考 Ralph 的 Session Expiration 设计：
    - 会话超时自动标记为 expired（默认 24 小时）
    - list_all 时自动检测并重置过期会话
    """

    MAX_SESSIONS = 50
    DEFAULT_EXPIRY_HOURS = 24

    def __init__(self, path: str = _DEFAULT_ROOT, max_sessions: int = 50,
                 expiry_hours: float = DEFAULT_EXPIRY_HOURS):
        if path.endswith(".json"):
            root = str(Path(path).parent)
        else:
            root = path
        self._db = GlobalDB(root)
        self.max_sessions = max_sessions
        self.expiry_seconds = expiry_hours * 3600

    # ── 写操作 ────────────────────────────────────────────────────────

    def register(
        self,
        session_id: str,
        requirement: str,
        source: str = "cli",
        preset: str = "",
        workspace_dir: str = "",
        pid: Optional[int] = None,
        version: str = "",
        requirement_type: str = "",
    ) -> dict:
        """注册新会话"""
        now = time.time()
        entry = {
            "session_id": session_id,
            "requirement": requirement,
            "source": source,
            "preset": preset,
            "status": "running",
            "started_at": now,
            "ended_at": None,
            "workspace_dir": workspace_dir,
            "project_name": "",
            "has_events": 0,
            "pid": pid or os.getpid(),
            "version": version,
            "requirement_type": requirement_type,
        }
        with self._db.write() as conn:
            existing = conn.execute(
                "SELECT session_id FROM run_sessions WHERE session_id=?", (session_id,)
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE run_sessions SET status='running', workspace_dir=?, pid=? WHERE session_id=?",
                    (workspace_dir, os.getpid(), session_id),
                )
                return {}
            conn.execute(
                """INSERT INTO run_sessions
                   (session_id, requirement, source, preset, status,
                    started_at, ended_at, workspace_dir, project_name, has_events, pid,
                    version, requirement_type)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    session_id, requirement[:500], source, preset, "running",
                    now, None, workspace_dir, "", 0, entry["pid"],
                    version, requirement_type or "primary",
                ),
            )
            # 超出 max_sessions 时清理最旧的已结束会话
            self._prune(conn)
        logger.info(f"会话已注册: {session_id} (来源: {source})")
        return entry

    def update(self, session_id: str, **fields):
        """更新会话字段"""
        if not fields:
            return
        allowed = {
            "status", "ended_at", "workspace_dir", "project_name",
            "has_events", "pid", "preset", "version", "requirement_type",
        }
        cols = {k: v for k, v in fields.items() if k in allowed}
        if not cols:
            return
        set_clause = ", ".join(f"{k}=?" for k in cols)
        values = list(cols.values()) + [session_id]
        with self._db.write() as conn:
            conn.execute(
                f"UPDATE run_sessions SET {set_clause} WHERE session_id=?", values
            )

    def delete(self, session_id: str) -> bool:
        with self._db.write() as conn:
            cur = conn.execute(
                "DELETE FROM run_sessions WHERE session_id=?", (session_id,)
            )
            deleted = cur.rowcount > 0
        if deleted:
            logger.info(f"会话已删除: {session_id}")
            self._db.delete_events(session_id)
        return deleted

    def delete_by_workspace(self, workspace_dir: str) -> list[str]:
        norm = os.path.normpath(workspace_dir)
        with self._db.write() as conn:
            rows = conn.execute(
                "SELECT session_id, workspace_dir FROM run_sessions"
            ).fetchall()
            removed = [
                r["session_id"]
                for r in rows
                if os.path.normpath(r["workspace_dir"] or "") == norm
            ]
            if removed:
                placeholders = ",".join("?" * len(removed))
                conn.execute(
                    f"DELETE FROM run_sessions WHERE session_id IN ({placeholders})",
                    removed,
                )
                logger.info(f"已删除 {len(removed)} 条关联会话 (workspace={workspace_dir})")
        return removed

    def clear(self, only_finished: bool = False) -> int:
        sids_to_clean: list[str] = []
        with self._db.write() as conn:
            if not only_finished:
                rows = conn.execute("SELECT session_id FROM run_sessions").fetchall()
                sids_to_clean = [r["session_id"] for r in rows]
                conn.execute("DELETE FROM run_sessions")
                logger.info(f"已清除全部 {len(sids_to_clean)} 条会话记录")
            else:
                rows = conn.execute("SELECT session_id, status, pid FROM run_sessions").fetchall()
                for r in rows:
                    if r["status"] != "running" or not self._is_pid_alive(r["pid"] or 0):
                        sids_to_clean.append(r["session_id"])
                if sids_to_clean:
                    ph = ",".join("?" * len(sids_to_clean))
                    conn.execute(f"DELETE FROM run_sessions WHERE session_id IN ({ph})", sids_to_clean)
                logger.info(f"已清除 {len(sids_to_clean)} 条已结束会话")
        # 在写锁外清理关联事件，避免死锁（_db.write() 使用非可重入 Lock）
        for sid in sids_to_clean:
            self._db.delete_events(sid)
        return len(sids_to_clean)

    # ── 读操作 ────────────────────────────────────────────────────────

    def get(self, session_id: str) -> Optional[dict]:
        with self._db.read() as conn:
            row = conn.execute(
                "SELECT * FROM run_sessions WHERE session_id=?", (session_id,)
            ).fetchone()
            return dict(row) if row else None

    def is_expired(self, session: dict) -> bool:
        """检查会话是否已过期（参考 Ralph 的 session expiration 机制）"""
        if session.get("status") != "running":
            return False
        started = session.get("started_at", 0)
        if not started:
            return False
        return (time.time() - started) > self.expiry_seconds

    def list_all(self, check_alive: bool = True) -> list[dict]:
        """列出所有会话；check_alive=True 时检测并修正僵死/过期会话"""
        with self._db.read() as conn:
            rows = conn.execute(
                "SELECT * FROM run_sessions ORDER BY started_at DESC"
            ).fetchall()
        sessions = [dict(r) for r in rows]

        if not check_alive:
            return sessions

        now = time.time()
        dead: list[str] = []
        expired: list[str] = []

        for s in sessions:
            if s.get("status") != "running":
                continue
            if not self._is_pid_alive(s.get("pid") or 0):
                dead.append(s["session_id"])
            elif self.is_expired(s):
                expired.append(s["session_id"])

        # 批量更新僵死会话
        if dead:
            with self._db.write() as conn:
                ph = ",".join("?" * len(dead))
                conn.execute(
                    f"UPDATE run_sessions SET status='interrupted', ended_at=? "
                    f"WHERE session_id IN ({ph})",
                    [now] + dead,
                )
            for s in sessions:
                if s["session_id"] in dead:
                    s["status"] = "interrupted"
                    s["ended_at"] = s.get("ended_at") or now

        # 批量更新过期会话
        if expired:
            with self._db.write() as conn:
                ph = ",".join("?" * len(expired))
                conn.execute(
                    f"UPDATE run_sessions SET status='expired', ended_at=? "
                    f"WHERE session_id IN ({ph})",
                    [now] + expired,
                )
            for s in sessions:
                if s["session_id"] in expired:
                    s["status"] = "expired"
                    s["ended_at"] = s.get("ended_at") or now
            logger.info(f"已标记 {len(expired)} 个过期会话 (>{self.expiry_seconds/3600:.0f}h)")

        return sessions

    # ── 内部 ─────────────────────────────────────────────────────────

    def _prune(self, conn):
        """保留最近 max_sessions 条，超出时删除最旧的已结束会话"""
        total = conn.execute("SELECT COUNT(*) FROM run_sessions").fetchone()[0]
        if total <= self.max_sessions:
            return
        excess = total - self.max_sessions
        conn.execute(
            """DELETE FROM run_sessions WHERE session_id IN (
               SELECT session_id FROM run_sessions
               WHERE status != 'running'
               ORDER BY started_at ASC LIMIT ?)""",
            (excess,),
        )

    @staticmethod
    def _is_pid_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False
