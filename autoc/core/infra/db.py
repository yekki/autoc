"""SQLite 数据库基础设施

两类数据库:
  ProjectDB  — 每个项目目录下的 .autoc.db
               存储: project, requirements, tasks, dev_sessions, milestones
  GlobalDB   — autoc 根目录下的 .autoc.db
               存储: run_sessions, session_events, experiences, experience_patterns

设计原则:
  - WAL 模式支持多进程并发读写
  - 进程内写操作通过 threading.Lock 串行化
  - 每次操作创建独立连接（轻量，SQLite 连接开销极小）
  - 对外暴露 write() / read() context manager，隐藏连接细节
"""

import json
import logging
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Iterator

logger = logging.getLogger("autoc.db")

# ── 进程内按 db 路径共享锁，防止同进程多线程并发写入 ─────────────────
_locks: dict[str, threading.Lock] = {}
_locks_mu = threading.Lock()


def _get_lock(path: str) -> threading.Lock:
    with _locks_mu:
        if path not in _locks:
            if len(_locks) > 500:
                # 锁字典过大，可能有路径泄漏。这是已知的内存增长问题，
                # 完美修复需要 weakref 或引用计数，此处仅打警告供排查。
                logger.warning(
                    "db._locks 已累积 %d 个锁，建议排查项目路径是否正确释放",
                    len(_locks),
                )
            _locks[path] = threading.Lock()
        return _locks[path]


# ── 工具函数 ─────────────────────────────────────────────────────────
def jdump(v) -> str:
    """Python 对象 → JSON 字符串（存入 TEXT 列）"""
    return json.dumps(v, ensure_ascii=False)


def jload(s: str, default=None):
    """JSON 字符串 → Python 对象"""
    if not s:
        return default
    try:
        return json.loads(s)
    except Exception:
        return default


# ── 基类 ─────────────────────────────────────────────────────────────
class _DBBase:
    """SQLite 连接管理基类"""

    def __init__(self, db_path: str):
        self.db_path = os.path.abspath(db_path)
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        self._lock = _get_lock(self.db_path)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.isdir(db_dir):
            raise sqlite3.OperationalError(
                f"数据库目录不存在（工作区可能已被删除）: {db_dir}"
            )
        conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA cache_size=-8000")   # 8 MB 页缓存
        return conn

    def _init_schema(self):
        """子类实现 DDL 建表"""
        raise NotImplementedError

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        """线程安全写事务；失败自动回滚"""
        with self._lock:
            conn = self._connect()
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        """只读连接（WAL 模式下无需锁）"""
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()


# ── ProjectDB ─────────────────────────────────────────────────────────
class ProjectDB(_DBBase):
    """
    每个项目目录下的 .autoc.db（隐藏文件，对用户项目代码不可见）

    替代:
      autoc-project.json  → project + dev_sessions + milestones 表
      autoc-tasks.json    → requirements + tasks 表
    """

    DB_FILE = ".autoc.db"

    def __init__(self, project_path: str):
        super().__init__(os.path.join(project_path, self.DB_FILE))

    def _init_schema(self):
        with self.write() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS project (
                id          TEXT PRIMARY KEY DEFAULT 'main',
                name        TEXT NOT NULL DEFAULT '',
                description TEXT DEFAULT '',
                project_path TEXT NOT NULL DEFAULT '',
                status      TEXT DEFAULT 'planning',
                version     TEXT DEFAULT '0.1.0',
                tech_stack  TEXT DEFAULT '[]',
                architecture TEXT DEFAULT '',
                total_tokens INTEGER DEFAULT 0,
                git_enabled INTEGER DEFAULT 1,
                use_project_venv INTEGER DEFAULT 0,
                single_task INTEGER DEFAULT 0,
                autoc_version TEXT DEFAULT '0.1.0',
                created_at  TEXT NOT NULL DEFAULT '',
                updated_at  TEXT NOT NULL DEFAULT ''
            );
            

            CREATE TABLE IF NOT EXISTS requirements (
                id          TEXT PRIMARY KEY,
                title       TEXT NOT NULL DEFAULT '',
                description TEXT DEFAULT '',
                status      TEXT DEFAULT 'pending',
                priority    INTEGER DEFAULT 0,
                acceptance_criteria TEXT DEFAULT '[]',
                pre_pause_status TEXT DEFAULT '',
                pause_reason TEXT DEFAULT '',
                status_notes TEXT DEFAULT '',
                tokens_used INTEGER DEFAULT 0,
                created_at  TEXT NOT NULL DEFAULT '',
                updated_at  TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id          TEXT PRIMARY KEY,
                title       TEXT NOT NULL DEFAULT '',
                description TEXT DEFAULT '',
                status      TEXT DEFAULT 'pending',
                assignee    TEXT DEFAULT '',
                priority    INTEGER DEFAULT 0,
                dependencies TEXT DEFAULT '[]',
                files       TEXT DEFAULT '[]',
                result      TEXT DEFAULT '',
                error       TEXT DEFAULT '',
                requirement_id TEXT NOT NULL DEFAULT '',
                verification_steps TEXT DEFAULT '[]',
                passes      INTEGER DEFAULT 0,
                verified_at TEXT DEFAULT '',
                verification_notes TEXT DEFAULT '',
                block_reason TEXT DEFAULT '',
                block_attempts INTEGER DEFAULT 0,
                block_context TEXT DEFAULT '',
                created_at  TEXT NOT NULL DEFAULT '',
                updated_at  TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_tasks_passes ON tasks(passes);

            CREATE TABLE IF NOT EXISTS dev_sessions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  TEXT DEFAULT '',
                requirement_id TEXT DEFAULT '',
                requirement TEXT DEFAULT '',
                success     INTEGER DEFAULT 0,
                tasks_completed INTEGER DEFAULT 0,
                tasks_total INTEGER DEFAULT 0,
                requirements_completed INTEGER DEFAULT 0,
                requirements_total INTEGER DEFAULT 0,
                elapsed_seconds REAL DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                agent_tokens TEXT DEFAULT '',
                notes       TEXT DEFAULT '',
                failure_reason TEXT DEFAULT '',
                timestamp   TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS milestones (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                title       TEXT NOT NULL DEFAULT '',
                description TEXT DEFAULT '',
                version     TEXT DEFAULT '',
                timestamp   TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS version_snapshots (
                version         TEXT PRIMARY KEY,
                requirement_type TEXT DEFAULT 'primary',
                requirement     TEXT DEFAULT '',
                tech_stack      TEXT DEFAULT '[]',
                tasks           TEXT DEFAULT '[]',
                bugs_fixed      TEXT DEFAULT '[]',
                success         INTEGER DEFAULT 0,
                total_tokens    INTEGER DEFAULT 0,
                elapsed_seconds REAL DEFAULT 0,
                started_at      REAL DEFAULT 0,
                ended_at        REAL DEFAULT 0,
                session_count   INTEGER DEFAULT 1,
                created_at      TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS ai_assist_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                action          TEXT DEFAULT '',
                project_name    TEXT DEFAULT '',
                total_tokens    INTEGER DEFAULT 0,
                prompt_tokens   INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                timestamp       TEXT NOT NULL DEFAULT ''
            );
            """)
            # 逐调用日志表（Token 追踪 v3）
            conn.execute("""
            CREATE TABLE IF NOT EXISTS llm_call_log (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id          TEXT DEFAULT '',
                agent               TEXT DEFAULT '',
                model               TEXT DEFAULT '',
                prompt_tokens       INTEGER DEFAULT 0,
                completion_tokens   INTEGER DEFAULT 0,
                cached_tokens       INTEGER DEFAULT 0,
                total_tokens        INTEGER DEFAULT 0,
                latency_ms          INTEGER DEFAULT 0,
                is_error            INTEGER DEFAULT 0,
                error_msg           TEXT DEFAULT '',
                timestamp           TEXT NOT NULL DEFAULT ''
            )""")

            # 增量迁移：为已有数据库补充新列
            for col_sql in (
                "ALTER TABLE project ADD COLUMN use_project_venv INTEGER DEFAULT 0",
                "ALTER TABLE project ADD COLUMN single_task INTEGER DEFAULT 0",
                "ALTER TABLE project ADD COLUMN ai_assist_tokens INTEGER DEFAULT 0",
                "ALTER TABLE requirements ADD COLUMN base_commit TEXT DEFAULT ''",
                "ALTER TABLE requirements ADD COLUMN revision INTEGER DEFAULT 0",
                "ALTER TABLE dev_sessions ADD COLUMN agent_tokens TEXT DEFAULT ''",
                "ALTER TABLE dev_sessions ADD COLUMN failure_reason TEXT DEFAULT ''",
                "ALTER TABLE dev_sessions ADD COLUMN session_id TEXT DEFAULT ''",
                "ALTER TABLE dev_sessions ADD COLUMN tech_stack TEXT DEFAULT '[]'",
                "ALTER TABLE dev_sessions ADD COLUMN prompt_tokens INTEGER DEFAULT 0",
                "ALTER TABLE dev_sessions ADD COLUMN completion_tokens INTEGER DEFAULT 0",
                "ALTER TABLE dev_sessions ADD COLUMN cached_tokens INTEGER DEFAULT 0",
                "ALTER TABLE dev_sessions ADD COLUMN call_count INTEGER DEFAULT 0",
                "ALTER TABLE dev_sessions ADD COLUMN error_calls INTEGER DEFAULT 0",
                # v4.3: 需求类型 + 版本语义
                "ALTER TABLE requirements ADD COLUMN type TEXT DEFAULT 'primary'",
                "ALTER TABLE requirements ADD COLUMN version TEXT DEFAULT ''",
                "ALTER TABLE requirements ADD COLUMN parent_version TEXT DEFAULT ''",
            ):
                try:
                    conn.execute(col_sql)
                except sqlite3.OperationalError as e:
                    if "duplicate column" not in str(e).lower():
                        logger.warning(f"Schema 迁移失败: {e}")
                except Exception as e:
                    logger.error(f"Schema 迁移严重错误: {e}")
                    raise


# ── GlobalDB ─────────────────────────────────────────────────────────
class GlobalDB(_DBBase):
    """
    autoc 根目录下的 .autoc.db

    替代:
      .autoc_sessions.json   → run_sessions 表
      .autoc_experience/     → experiences + experience_patterns 表
    """

    DB_FILE = ".autoc.db"

    def __init__(self, root_path: str):
        super().__init__(os.path.join(root_path, self.DB_FILE))

    def _init_schema(self):
        with self.write() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS run_sessions (
                session_id  TEXT PRIMARY KEY,
                requirement TEXT DEFAULT '',
                source      TEXT DEFAULT 'cli',
                preset      TEXT DEFAULT '',
                status      TEXT DEFAULT 'running',
                started_at  REAL NOT NULL DEFAULT 0,
                ended_at    REAL,
                workspace_dir TEXT DEFAULT '',
                project_name TEXT DEFAULT '',
                has_events  INTEGER DEFAULT 0,
                pid         INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_rs_project ON run_sessions(project_name);
            CREATE INDEX IF NOT EXISTS idx_rs_status  ON run_sessions(status);

            CREATE TABLE IF NOT EXISTS experiences (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                exp_id      TEXT NOT NULL DEFAULT '',
                requirement_summary TEXT DEFAULT '',
                project_name TEXT DEFAULT '',
                tech_stack  TEXT DEFAULT '[]',
                architecture TEXT DEFAULT '',
                directory_structure TEXT DEFAULT '',
                file_count  INTEGER DEFAULT 0,
                files_sample TEXT DEFAULT '[]',
                bugs_found_count INTEGER DEFAULT 0,
                bugs_fixed_count INTEGER DEFAULT 0,
                common_issues TEXT DEFAULT '[]',
                quality_score INTEGER DEFAULT 0,
                success     INTEGER DEFAULT 1,
                elapsed_seconds REAL DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                failure_reason TEXT DEFAULT '',
                rounds_attempted INTEGER DEFAULT 0,
                unresolved_bugs TEXT DEFAULT '[]',
                timestamp   TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS experience_patterns (
                keyword     TEXT NOT NULL,
                tech_stack  TEXT NOT NULL,
                count       INTEGER DEFAULT 1,
                PRIMARY KEY (keyword, tech_stack)
            );

            CREATE TABLE IF NOT EXISTS session_events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  TEXT NOT NULL,
                seq         INTEGER DEFAULT 0,
                type        TEXT NOT NULL DEFAULT '',
                agent       TEXT DEFAULT '',
                data_json   TEXT DEFAULT '{}',
                created_at  REAL NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_se_session ON session_events(session_id);

            CREATE TABLE IF NOT EXISTS fix_trajectories (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id      TEXT DEFAULT '',
                round_num       INTEGER DEFAULT 0,
                bug_id          TEXT NOT NULL DEFAULT '',
                bug_title       TEXT DEFAULT '',
                bug_severity    TEXT DEFAULT 'medium',
                bug_description TEXT DEFAULT '',
                fix_attempt     INTEGER DEFAULT 1,
                strategy        TEXT DEFAULT '',
                fix_result      TEXT DEFAULT '',
                code_changes    TEXT DEFAULT '[]',
                test_passed     INTEGER DEFAULT 0,
                reflection      TEXT DEFAULT '',
                failure_patterns TEXT DEFAULT '[]',
                timestamp       TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_ft_bug ON fix_trajectories(bug_id);
            """)

            for col_sql in (
                "ALTER TABLE run_sessions ADD COLUMN version TEXT DEFAULT ''",
                "ALTER TABLE run_sessions ADD COLUMN requirement_type TEXT DEFAULT 'primary'",
            ):
                try:
                    conn.execute(col_sql)
                except sqlite3.OperationalError as e:
                    if "duplicate column" not in str(e).lower():
                        logger.warning(f"Schema 迁移失败: {e}")

            # 为 session_events(session_id, seq) 添加唯一索引，支持 INSERT OR IGNORE 去重
            # 先去重再建索引，避免已有重复数据时 IntegrityError 导致服务器启动崩溃
            try:
                conn.execute("""
                    DELETE FROM session_events WHERE id NOT IN (
                        SELECT MIN(id) FROM session_events GROUP BY session_id, seq
                    )
                """)
                conn.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_se_session_seq "
                    "ON session_events(session_id, seq)"
                )
            except sqlite3.OperationalError as e:
                if "already exists" not in str(e).lower():
                    logger.warning(f"session_events 索引迁移: {e}")
            except Exception as e:
                logger.warning(f"session_events 索引迁移失败（忽略）: {e}")
                # 不 raise，索引是优化项，失败不影响核心功能

    def save_event(self, session_id: str, seq: int, event: dict):
        """持久化单条事件（跳过 heartbeat）"""
        etype = event.get("type", "")
        if etype == "heartbeat":
            return
        with self.write() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO session_events
                   (session_id, seq, type, agent, data_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    session_id,
                    seq,
                    etype,
                    event.get("agent", ""),
                    jdump(event.get("data") or {}),
                    time.time(),
                ),
            )

    def get_events(self, session_id: str) -> list[dict]:
        """读取会话所有持久化事件，按 seq 升序返回"""
        with self.read() as conn:
            rows = conn.execute(
                "SELECT type, agent, data_json, created_at FROM session_events"
                " WHERE session_id=? ORDER BY seq ASC",
                (session_id,),
            ).fetchall()
        return [
            {
                "type": r["type"],
                "agent": r["agent"],
                "data": jload(r["data_json"], {}),
                "started_at": r["created_at"],
            }
            for r in rows
        ]

    def delete_events(self, session_id: str):
        """删除会话所有持久化事件（清理用）"""
        with self.write() as conn:
            conn.execute(
                "DELETE FROM session_events WHERE session_id=?", (session_id,)
            )
