"""跨会话进度追踪系统（SQLite 版）

数据存储: workspace/{project}/.autoc.db
  - tasks 任务状态（含 passes 字段）

autoc-progress.txt 人类可读日志继续保留（append-only，无并发问题）。

"""

import logging
import os
from datetime import datetime
from typing import Optional

from autoc.core.infra.db import ProjectDB, jdump, jload

logger = logging.getLogger("autoc.progress")


class ProgressTracker:
    """跨会话进度追踪器（SQLite 后端）"""

    PROGRESS_FILE = "autoc-progress.txt"

    def __init__(self, workspace_dir: str):
        self.workspace_dir = os.path.abspath(workspace_dir)
        self.progress_path = os.path.join(self.workspace_dir, self.PROGRESS_FILE)
        self._db = ProjectDB(self.workspace_dir)
        self._session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    # ── Progress 日志（保留 txt，追加写入无并发问题）────────────────

    def read_progress(self) -> str:
        if not os.path.exists(self.progress_path):
            return ""
        try:
            with open(self.progress_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            logger.warning(f"读取进度文件失败: {e}")
            return ""

    def write_entry(self, title: str, content: str, notes: str = ""):
        """追加进度记录到 autoc-progress.txt"""
        os.makedirs(self.workspace_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = (
            f"\n## Session {self._session_id} - {title}\n"
            f"时间: {timestamp}\n\n"
            f"### 操作\n{content}\n"
        )
        if notes:
            entry += f"\n### 备注 (给未来 Agent)\n{notes}\n"
        entry += f"\n{'─' * 60}\n"
        try:
            with open(self.progress_path, "a", encoding="utf-8") as f:
                f.write(entry)
        except Exception as e:
            logger.warning(f"写入进度文件失败: {e}")

    def init_progress(self, project_name: str, requirement: str, task_count: int):
        """初始化 progress.txt（首次创建）"""
        if os.path.exists(self.progress_path):
            return
        os.makedirs(self.workspace_dir, exist_ok=True)
        header = (
            f"# AutoC 项目进度日志\n"
            f"# ==================\n"
            f"# 项目: {project_name}\n"
            f"# 需求: {requirement[:200]}\n"
            f"# 创建时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"# 任务总数: {task_count}\n"
            f"#\n"
            f"# 此文件由 AutoC 自动维护，用于跨会话的进度追踪。\n\n"
            f"{'═' * 60}\n\n"
        )
        try:
            with open(self.progress_path, "w", encoding="utf-8") as f:
                f.write(header)
        except Exception as e:
            logger.warning(f"初始化进度文件失败: {e}")

    # ── 工具函数：行转 dict ────────────────────────────────────────────

    @staticmethod
    def _task_row(row) -> dict:
        d = dict(row)
        d["dependencies"] = jload(d.get("dependencies"), [])
        d["files"] = jload(d.get("files"), [])
        d["verification_steps"] = jload(d.get("verification_steps"), [])
        d["passes"] = bool(d.get("passes", 0))
        d["feature_tag"] = d.get("requirement_id", "")
        return d

    # ── Tasks ─────────────────────────────────────────────────────────

    def delete_tasks_by_ids(self, task_ids: list[str]):
        """从数据库中删除指定 ID 的任务"""
        if not task_ids:
            return
        with self._db.write() as conn:
            placeholders = ",".join("?" for _ in task_ids)
            conn.execute(f"DELETE FROM tasks WHERE id IN ({placeholders})", task_ids)
        logger.info(f"已从 DB 删除 {len(task_ids)} 个任务: {task_ids}")

    def load_tasks(self) -> list[dict]:
        with self._db.read() as conn:
            rows = conn.execute(
                "SELECT * FROM tasks ORDER BY rowid ASC"
            ).fetchall()
            return [self._task_row(r) for r in rows]

    def save_tasks(self, tasks: list[dict]):
        """批量 upsert 任务。"""
        now = datetime.now().isoformat()
        with self._db.write() as conn:
            for t in tasks:
                conn.execute(
                    """INSERT INTO tasks
                       (id, title, description, status, assignee, priority,
                        dependencies, files, result, error, requirement_id,
                        verification_steps, passes, verified_at, verification_notes,
                        block_reason, block_attempts, block_context,
                        created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(id) DO UPDATE SET
                         title=excluded.title,
                         description=excluded.description,
                         status=excluded.status,
                         assignee=excluded.assignee,
                         priority=excluded.priority,
                         dependencies=excluded.dependencies,
                         files=excluded.files,
                         result=excluded.result,
                         error=excluded.error,
                         requirement_id=excluded.requirement_id,
                         verification_steps=excluded.verification_steps,
                         passes=excluded.passes,
                         verified_at=excluded.verified_at,
                         verification_notes=excluded.verification_notes,
                         block_reason=excluded.block_reason,
                         block_attempts=excluded.block_attempts,
                         block_context=excluded.block_context,
                         updated_at=excluded.updated_at""",
                    (
                        t.get("id", ""),
                        t.get("title", ""),
                        t.get("description", ""),
                        t.get("status", "pending"),
                        t.get("assignee", ""),
                        t.get("priority", 0),
                        jdump(t.get("dependencies", [])),
                        jdump(t.get("files", [])),
                        t.get("result", ""),
                        t.get("error", ""),
                        t.get("feature_tag", ""),
                        jdump(t.get("verification_steps", [])),
                        1 if t.get("passes", False) else 0,
                        t.get("verified_at", ""),
                        t.get("verification_notes", ""),
                        t.get("block_reason", ""),
                        t.get("block_attempts", 0),
                        t.get("block_context", ""),
                        t.get("created_at", now),
                        now,
                    ),
                )
        logger.info(f"任务已保存: {len(tasks)} 个")

    def update_task_status(self, task_id: str, status: str):
        now = datetime.now().isoformat()
        with self._db.write() as conn:
            conn.execute(
                "UPDATE tasks SET status=?, updated_at=? WHERE id=?",
                (status, now, task_id),
            )

    def update_task_passes(self, task_id: str, passes: bool, notes: str = ""):
        """更新单个任务的 passes 状态"""
        now = datetime.now().isoformat()
        with self._db.write() as conn:
            if passes:
                conn.execute(
                    """UPDATE tasks SET passes=1, verified_at=?, verification_notes=?, updated_at=?
                       WHERE id=? AND passes=0""",
                    (now, notes, now, task_id),
                )
            else:
                conn.execute(
                    """UPDATE tasks SET passes=0, verification_notes=?, updated_at=?
                       WHERE id=?""",
                    (notes, now, task_id),
                )

    def write_task_result(self, task_id: str, phase: str,
                          success: bool, files: list[str], summary: str = ""):
        """记录单个任务的开发/测试结果（用于 checkpoint 恢复和审计）"""
        status = "passed" if success else "failed"
        files_str = ", ".join(files[:10]) if files else "(无文件变更)"
        self.write_entry(
            title=f"[{phase.upper()}] {task_id} → {status}",
            content=f"变更文件: {files_str}\n{summary[:200]}",
        )

    # ── 概要摘要 ──────────────────────────────────────────────────────

    def get_tasks_summary(self) -> str:
        with self._db.read() as conn:
            tasks = conn.execute("SELECT * FROM tasks ORDER BY rowid").fetchall()

        if not tasks:
            return "暂无任务列表"

        total = len(tasks)
        passed = sum(1 for t in tasks if t["passes"])
        lines = [f"任务进度: {passed}/{total} 已验证通过, {total - passed} 待完成\n"]

        for t in tasks:
            s = "PASSES" if t["passes"] else "待验证"
            lines.append(f"  [{t['id']}] {s} - {t['title']}")

        return "\n".join(lines)

    def get_session_context(self) -> str:
        parts = []
        progress = self.read_progress()
        if progress:
            if len(progress) > 2000:
                progress = "...(更早的记录已省略)...\n\n" + progress[-2000:]
            parts.append(f"## 项目进度日志\n{progress}")
        summary = self.get_tasks_summary()
        if summary:
            parts.append(f"## 任务概要\n{summary}")
        return "\n\n".join(parts) if parts else ""
