"""项目管理模块（SQLite 版）

数据存储: workspace/{project}/.autoc.db
  - project       单行元数据
  - tasks         任务列表
  - dev_sessions  开发会话历史
  - milestones    里程碑

"""

import json
import logging
import os
from datetime import datetime
from typing import Optional

from autoc.core.infra.db import ProjectDB, jdump, jload
from .models import (
    ProjectMetadata, ProjectStatus, VALID_STATUS_TRANSITIONS,
    RequirementType, bump_major, bump_minor, bump_patch,
    parse_version, format_version,
)

logger = logging.getLogger("autoc.project")


class ProjectManager:
    """项目管理器（SQLite 后端）"""

    PROJECT_FILE = ".autoc.db"
    PROGRESS_FILE = "autoc-progress.txt"

    def __init__(self, project_path: str):
        self.project_path = os.path.abspath(project_path)
        self._db = ProjectDB(self.project_path)
        self.project_file = os.path.join(self.project_path, self.PROJECT_FILE)
        self.progress_file = os.path.join(self.project_path, self.PROGRESS_FILE)

    # ── 内部转换 ──────────────────────────────────────────────────────

    def _row_to_metadata(self, row) -> ProjectMetadata:
        keys = row.keys()
        return ProjectMetadata(
            name=row["name"],
            description=row["description"],
            project_path=row["project_path"] or self.project_path,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            status=row["status"],
            version=row["version"],
            tech_stack=jload(row["tech_stack"], []),
            architecture=row["architecture"],
            total_tokens=row["total_tokens"],
            ai_assist_tokens=row["ai_assist_tokens"] if "ai_assist_tokens" in keys else 0,
            git_enabled=bool(row["git_enabled"]),
            use_project_venv=bool(row["use_project_venv"]) if "use_project_venv" in keys else False,
            single_task=bool(row["single_task"]) if "single_task" in keys else False,
            autoc_version=row["autoc_version"],
            total_tasks=self._count_tasks(),
            completed_tasks=max(
                self._count_tasks(status="completed"),
                self._count_tasks(passes=True),
            ),
            verified_tasks=self._count_tasks(passes=True),
            sessions=self._load_sessions_raw(),
            milestones=self._load_milestones_raw(),
        )

    def _count_tasks(self, status: str = "", passes: bool = False) -> int:
        with self._db.read() as conn:
            if passes:
                row = conn.execute(
                    "SELECT COUNT(*) FROM tasks WHERE passes=1"
                ).fetchone()
            elif status:
                row = conn.execute(
                    "SELECT COUNT(*) FROM tasks WHERE status=?", (status,)
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()
            return row[0] if row else 0

    def _load_sessions_raw(self) -> list[dict]:
        with self._db.read() as conn:
            rows = conn.execute(
                "SELECT * FROM dev_sessions ORDER BY timestamp ASC"
            ).fetchall()
            sessions = []
            for r in rows:
                s = dict(r)
                raw = s.get("agent_tokens", "")
                if raw:
                    try:
                        s["agent_tokens"] = json.loads(raw)
                    except Exception:
                        s["agent_tokens"] = None
                else:
                    s["agent_tokens"] = None
                raw_ts = s.get("tech_stack", "[]")
                try:
                    s["tech_stack"] = json.loads(raw_ts) if raw_ts else []
                except Exception:
                    s["tech_stack"] = []
                sessions.append(s)
            return sessions

    def _load_milestones_raw(self) -> list[dict]:
        with self._db.read() as conn:
            rows = conn.execute(
                "SELECT * FROM milestones ORDER BY timestamp ASC"
            ).fetchall()
            return [dict(r) for r in rows]

    # ── 静态方法：跨项目操作 ──────────────────────────────────────────

    @staticmethod
    def list_all_projects(workspace_root: str = "./workspace") -> list[dict]:
        """列出工作区中所有项目，按更新时间倒序"""
        workspace_root = os.path.abspath(workspace_root)
        if not os.path.exists(workspace_root):
            return []

        projects = []
        for item in os.listdir(workspace_root):
            project_dir = os.path.join(workspace_root, item)
            if not os.path.isdir(project_dir):
                continue
            db_file = os.path.join(project_dir, ProjectDB.DB_FILE)
            if not os.path.exists(db_file):
                continue
            try:
                pm = ProjectManager(project_dir)
                proj = pm._project_dict(item)
                if proj:
                    projects.append(proj)
            except Exception as e:
                logger.debug(f"跳过损坏项目 {project_dir}: {e}")

        return sorted(projects, key=lambda x: x.get("updated_at", ""), reverse=True)

    def _project_dict(self, folder: str) -> Optional[dict]:
        """将当前项目数据组装为列表项 dict"""
        with self._db.read() as conn:
            row = conn.execute("SELECT * FROM project WHERE id='main'").fetchone()
            if not row:
                return None
            tasks = conn.execute("SELECT passes FROM tasks").fetchall()

        sessions_raw = self._load_sessions_raw()

        def _safe_bool(col_name: str) -> bool:
            return bool(row[col_name]) if col_name in row.keys() else False

        return {
            "name": row["name"] or folder,
            "path": self.project_path,
            "folder": folder,
            "description": (row["description"] or "")[:100],
            "status": row["status"],
            "version": row["version"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "total_tasks": len(tasks),
            "verified_tasks": sum(1 for t in tasks if t["passes"]),
            "tech_stack": jload(row["tech_stack"], []),
            "sessions_count": len(sessions_raw),
            "total_tokens": row["total_tokens"],
            "git_enabled": bool(row["git_enabled"]),
            "use_project_venv": _safe_bool("use_project_venv"),
            "single_task": _safe_bool("single_task"),
        }

    @staticmethod
    def find_project_by_name(name: str, workspace_root: str = "./workspace") -> Optional[str]:
        """按项目名（或文件夹名）查找项目路径"""
        projects = ProjectManager.list_all_projects(workspace_root)
        for project in projects:
            if project["name"] == name or project["folder"] == name:
                return project["path"]
        return None

    # ── 生命周期 ──────────────────────────────────────────────────────

    def exists(self) -> bool:
        """项目是否已初始化"""
        db_file = os.path.join(self.project_path, ProjectDB.DB_FILE)
        if not os.path.exists(db_file):
            return False
        with self._db.read() as conn:
            row = conn.execute("SELECT id FROM project WHERE id='main'").fetchone()
            return row is not None

    def init(
        self,
        name: str,
        description: str,
        tech_stack: list[str] | None = None,
        git_enabled: bool = True,
        use_project_venv: bool = False,
        single_task: bool = False,
    ) -> ProjectMetadata:
        """初始化新项目"""
        if self.exists():
            raise ValueError(f"项目已存在: {self.project_path}")

        os.makedirs(self.project_path, exist_ok=True)
        now = datetime.now().isoformat()

        with self._db.write() as conn:
            conn.execute(
                """INSERT INTO project
                   (id, name, description, project_path, status, version,
                    tech_stack, architecture, total_tokens, git_enabled,
                    use_project_venv, single_task,
                    autoc_version, created_at, updated_at)
                   VALUES ('main',?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    name, description, self.project_path,
                    ProjectStatus.IDLE.value, "1.0.0",
                    jdump(tech_stack or []), "", 0,
                    1 if git_enabled else 0,
                    1 if use_project_venv else 0,
                    1 if single_task else 0,
                    "0.1.0", now, now,
                ),
            )

        meta = self.load()
        logger.info(f"项目已初始化: {name} → {self.project_path}")
        return meta

    def load(self) -> Optional[ProjectMetadata]:
        """加载项目元数据"""
        with self._db.read() as conn:
            row = conn.execute("SELECT * FROM project WHERE id='main'").fetchone()
            if not row:
                return None
            return self._row_to_metadata(row)

    def save(self, metadata: ProjectMetadata):
        """保存项目元数据（只更新 project 表，不涉及 requirements/tasks）"""
        metadata.updated_at = datetime.now().isoformat()
        with self._db.write() as conn:
            conn.execute(
                """UPDATE project SET
                   name=?, description=?, project_path=?, status=?, version=?,
                   tech_stack=?, architecture=?, total_tokens=?,
                   git_enabled=?, use_project_venv=?, single_task=?,
                   autoc_version=?, updated_at=?
                   WHERE id='main'""",
                (
                    metadata.name, metadata.description, metadata.project_path,
                    metadata.status, metadata.version,
                    jdump(metadata.tech_stack), metadata.architecture,
                    metadata.total_tokens,
                    1 if metadata.git_enabled else 0,
                    1 if metadata.use_project_venv else 0,
                    1 if metadata.single_task else 0,
                    metadata.autoc_version, metadata.updated_at,
                ),
            )

    # ── 元数据更新 ────────────────────────────────────────────────────

    def update_metadata(self, **fields):
        """更新项目元数据的指定字段（如 tech_stack）"""
        meta = self.load()
        if not meta:
            return
        for k, v in fields.items():
            if v is not None and hasattr(meta, k):
                setattr(meta, k, v)
        self.save(meta)

    # ── 状态更新 ──────────────────────────────────────────────────────

    def update_status(self, status: ProjectStatus, *, force: bool = False):
        """更新项目状态，默认校验转换合法性。

        读取当前状态 + 校验 + 写入在同一个 write() 事务内完成，
        避免并发场景下的 TOCTOU 竞态。

        Args:
            force: 跳过合法性校验（仅限 stale 检测等兜底场景使用）
        """
        now = datetime.now().isoformat()
        with self._db.write() as conn:
            if not force:
                row = conn.execute("SELECT status FROM project WHERE id='main'").fetchone()
                if row:
                    try:
                        current = ProjectStatus(row["status"])
                    except ValueError:
                        current = None
                    if current is not None:
                        if current == status:
                            return
                        allowed = VALID_STATUS_TRANSITIONS.get(current, set())
                        if status not in allowed:
                            msg = (
                                f"非法状态转换 {current.value} → {status.value}，"
                                f"允许的目标: {[s.value for s in allowed]}。"
                                f"如需强制转换请使用 force=True"
                            )
                            logger.error(msg)
                            raise ValueError(msg)
            conn.execute(
                "UPDATE project SET status=?, updated_at=? WHERE id='main'",
                (status.value, now),
            )

    _ACTIVE_STATUSES = {
        ProjectStatus.PLANNING.value,
        ProjectStatus.DEVELOPING.value,
        ProjectStatus.TESTING.value,
    }

    def update_progress(
        self,
        total_tasks: int,
        completed_tasks: int,
        verified_tasks: int,
        **_kwargs,
    ):
        """更新项目进度（根据任务完成度自动调整状态）

        - 全部验证通过 → 通过 update_status 走状态机校验设置 COMPLETED
        - 其余情况保留当前状态不变
        """
        if verified_tasks == total_tasks and total_tasks > 0:
            try:
                self.update_status(ProjectStatus.COMPLETED)
            except ValueError:
                self.update_status(ProjectStatus.COMPLETED, force=True)

    def record_session(
        self,
        requirement: str,
        success: bool,
        tasks_completed: int,
        tasks_total: int,
        elapsed_seconds: float,
        notes: str = "",
        total_tokens: int = 0,
        agent_tokens: dict | None = None,
        failure_reason: str = "",
        session_id: str = "",
        tech_stack: list[str] | None = None,
        **_kwargs,
    ):
        """记录开发会话，并累加 total_tokens"""
        now = datetime.now().isoformat()
        at = agent_tokens or {}
        agent_tokens_json = json.dumps(at) if at else ""
        tech_stack_json = json.dumps(tech_stack or [], ensure_ascii=False)
        with self._db.write() as conn:
            conn.execute(
                """INSERT INTO dev_sessions
                   (session_id, requirement, success, tasks_completed, tasks_total,
                    elapsed_seconds, total_tokens, agent_tokens, notes,
                    failure_reason, tech_stack,
                    prompt_tokens, completion_tokens, cached_tokens,
                    call_count, error_calls,
                    timestamp)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    session_id, requirement[:200], 1 if success else 0,
                    tasks_completed, tasks_total,
                    elapsed_seconds, total_tokens, agent_tokens_json, notes,
                    (failure_reason or "")[:500], tech_stack_json,
                    at.get("_prompt_tokens", 0),
                    at.get("_completion_tokens", 0),
                    at.get("_cached_tokens", 0),
                    at.get("_call_count", 0),
                    at.get("_error_calls", 0),
                    now,
                ),
            )
            conn.execute(
                "UPDATE project SET total_tokens=total_tokens+?, updated_at=? WHERE id='main'",
                (total_tokens, now),
            )

    def save_version_snapshot(
        self,
        version: str,
        requirement_type: str = "primary",
        requirement: str = "",
        tech_stack: list[str] | None = None,
        tasks: list[dict] | None = None,
        bugs_fixed: list[dict] | None = None,
        success: bool = False,
        total_tokens: int = 0,
        elapsed_seconds: float = 0,
        started_at: float = 0,
        ended_at: float = 0,
        session_count: int = 1,
    ):
        """保存版本快照到 version_snapshots 表（UPSERT）"""
        now = datetime.now().isoformat()
        with self._db.write() as conn:
            conn.execute(
                """INSERT INTO version_snapshots
                   (version, requirement_type, requirement, tech_stack, tasks,
                    bugs_fixed, success, total_tokens, elapsed_seconds,
                    started_at, ended_at, session_count, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(version) DO UPDATE SET
                    requirement_type=excluded.requirement_type,
                    requirement=excluded.requirement,
                    tech_stack=excluded.tech_stack,
                    tasks=excluded.tasks,
                    bugs_fixed=excluded.bugs_fixed,
                    success=excluded.success,
                    total_tokens=excluded.total_tokens,
                    elapsed_seconds=excluded.elapsed_seconds,
                    started_at=excluded.started_at,
                    ended_at=excluded.ended_at,
                    session_count=excluded.session_count,
                    created_at=excluded.created_at""",
                (
                    version, requirement_type, requirement[:2000],
                    json.dumps(tech_stack or [], ensure_ascii=False),
                    json.dumps(tasks or [], ensure_ascii=False),
                    json.dumps(bugs_fixed or [], ensure_ascii=False),
                    1 if success else 0,
                    total_tokens, elapsed_seconds,
                    started_at, ended_at, session_count, now,
                ),
            )

    def get_version_snapshots(self) -> list[dict]:
        """读取所有版本快照，按版本号排序"""
        with self._db.read() as conn:
            rows = conn.execute(
                "SELECT * FROM version_snapshots ORDER BY created_at ASC"
            ).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                for field in ("tech_stack", "tasks", "bugs_fixed"):
                    try:
                        d[field] = json.loads(d.get(field) or "[]")
                    except (json.JSONDecodeError, TypeError):
                        d[field] = []
                d["success"] = bool(d.get("success"))
                result.append(d)
            return result

    def record_ai_assist(
        self,
        action: str,
        total_tokens: int,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ):
        """记录 AI 辅助功能的 token 消耗，并累加到项目总量"""
        now = datetime.now().isoformat()
        name = ""
        try:
            meta = self.load()
            if meta:
                name = meta.name
        except Exception:
            pass
        with self._db.write() as conn:
            conn.execute(
                """INSERT INTO ai_assist_log
                   (action, project_name, total_tokens, prompt_tokens,
                    completion_tokens, timestamp)
                   VALUES (?,?,?,?,?,?)""",
                (action, name, total_tokens, prompt_tokens,
                 completion_tokens, now),
            )
            conn.execute(
                "UPDATE project SET total_tokens=total_tokens+?, updated_at=? WHERE id='main'",
                (total_tokens, now),
            )
            try:
                conn.execute(
                    "UPDATE project SET ai_assist_tokens=ai_assist_tokens+?, updated_at=? WHERE id='main'",
                    (total_tokens, now),
                )
            except Exception:
                pass

    def get_ai_assist_stats(self) -> dict:
        """获取 AI 辅助功能的 token 统计"""
        with self._db.read() as conn:
            rows = conn.execute(
                "SELECT action, total_tokens, prompt_tokens, completion_tokens, timestamp "
                "FROM ai_assist_log ORDER BY id DESC"
            ).fetchall()
            total = sum(r["total_tokens"] for r in rows)
            return {
                "total_tokens": total,
                "call_count": len(rows),
                "records": [
                    {
                        "action": r["action"],
                        "total_tokens": r["total_tokens"],
                        "prompt_tokens": r["prompt_tokens"],
                        "completion_tokens": r["completion_tokens"],
                        "timestamp": r["timestamp"],
                    }
                    for r in rows[:20]
                ],
            }

    def add_milestone(self, title: str, description: str, version: str = ""):
        now = datetime.now().isoformat()
        with self._db.write() as conn:
            conn.execute(
                "INSERT INTO milestones (title, description, version, timestamp) VALUES (?,?,?,?)",
                (title, description, version, now),
            )
            if version:
                conn.execute(
                    "UPDATE project SET version=?, updated_at=? WHERE id='main'",
                    (version, now),
                )

    # ── 版本管理 ──────────────────────────────────────────────────────

    def get_version(self) -> str:
        """读取当前项目版本（归一化为三段式 SemVer）"""
        with self._db.read() as conn:
            row = conn.execute("SELECT version FROM project WHERE id='main'").fetchone()
            raw = row["version"] if row else "1.0.0"
        major, minor, patch = parse_version(raw)
        return format_version(major, minor, patch)

    def set_version(self, version: str):
        """直接设置版本号"""
        now = datetime.now().isoformat()
        with self._db.write() as conn:
            conn.execute(
                "UPDATE project SET version=?, updated_at=? WHERE id='main'",
                (version, now),
            )

    def bump_version(self, bump_type: RequirementType) -> str:
        """根据需求类型自动递增版本号，返回新版本"""
        current = self.get_version()
        if bump_type == RequirementType.PRIMARY:
            new_ver = bump_major(current)
        elif bump_type == RequirementType.SECONDARY:
            new_ver = bump_minor(current)
        else:
            new_ver = bump_patch(current)
        self.set_version(new_ver)
        logger.info(f"版本递增: {current} → {new_ver} ({bump_type.value})")
        return new_ver

    def record_requirement(
        self,
        req_id: str,
        title: str,
        description: str,
        req_type: RequirementType = RequirementType.PRIMARY,
        version: str = "",
        parent_version: str = "",
    ):
        """记录一条需求到 requirements 表"""
        now = datetime.now().isoformat()
        with self._db.write() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO requirements
                   (id, title, description, status, type, version, parent_version,
                    created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (req_id, title[:200], description[:2000], "pending",
                 req_type.value, version, parent_version, now, now),
            )

    def get_pending_tasks(self) -> list[dict]:
        """获取所有未通过的任务"""
        with self._db.read() as conn:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE passes=0"
            ).fetchall()
            return [dict(r) for r in rows]

    def delete(self, remove_files: bool = True) -> bool:
        if not self.exists():
            return False
        if remove_files:
            import shutil
            shutil.rmtree(self.project_path, ignore_errors=True)
        else:
            import shutil
            db_path = os.path.join(self.project_path, ProjectDB.DB_FILE)
            for f in (db_path, self.progress_file):
                if os.path.exists(f):
                    try:
                        os.remove(f)
                    except OSError:
                        pass
            # 清理 .autoc/ 状态目录（prd.json / plan/ / guardrails.md 等）
            state_dir = os.path.join(self.project_path, ".autoc")
            if os.path.isdir(state_dir):
                shutil.rmtree(state_dir, ignore_errors=True)
        return True

    # ── 状态摘要 ──────────────────────────────────────────────────────

    def get_status_summary(self) -> str:
        meta = self.load()
        if not meta:
            return "项目不存在"
        from .progress import ProgressTracker
        pt = ProgressTracker(self.project_path)
        tasks = pt.load_tasks()

        status_icons = {
            ProjectStatus.IDLE.value: "💤",
            ProjectStatus.PLANNING.value: "📋",
            ProjectStatus.DEVELOPING.value: "🔨",
            ProjectStatus.TESTING.value: "🧪",
            ProjectStatus.INCOMPLETE.value: "⚠️",
            ProjectStatus.COMPLETED.value: "✅",
            ProjectStatus.ABORTED.value: "❌",
        }
        icon = status_icons.get(meta.status, "📁")
        total_tasks = meta.total_tasks
        verified = meta.verified_tasks
        task_pct = verified / total_tasks * 100 if total_tasks else 0

        task_detail = ""
        if tasks:
            task_detail = "\n任务列表:\n"
            for t in tasks:
                ti = "PASS" if t.get("passes", False) else "----"
                task_detail += f"   [{ti}] [{t['id']}] {t.get('title', '?')}\n"

        summary = (
            f"\n{icon} 项目: {meta.name}\n"
            f"{'━'*42}\n\n"
            f"描述: {meta.description}\n"
            f"路径: {meta.project_path}\n"
            f"版本: {meta.version}\n"
            f"状态: {meta.status.upper()}\n\n"
            f"技术栈: {', '.join(meta.tech_stack) if meta.tech_stack else '未指定'}\n\n"
            f"开发进度:\n"
            f"   任务: {verified}/{total_tasks} 验证 ({task_pct:.1f}%)\n"
            f"{task_detail}\n"
            f"创建: {meta.created_at[:19].replace('T', ' ')}\n"
            f"更新: {meta.updated_at[:19].replace('T', ' ')}\n"
            f"开发历史: {len(meta.sessions)} 个会话\n"
            f"里程碑: {len(meta.milestones)} 个\n"
        )
        if meta.milestones:
            lm = meta.milestones[-1]
            summary += f"\n最近里程碑: {lm['title']} ({lm.get('version', '')})"
        if meta.sessions:
            ls = meta.sessions[-1]
            summary += (
                f"\n最近会话: {str(ls.get('timestamp', ''))[:19].replace('T', ' ')}\n"
                f"   需求: {str(ls.get('requirement', ''))[:50]}...\n"
                f"   结果: {'成功' if ls.get('success') else '部分完成'}"
            )
        return summary


# ── 独立工具函数 ────────────────────────────────────────────────────

def slugify_project_name(name: str) -> str:
    """将项目名转为文件系统/Docker 安全的 ASCII slug。

    纯 ASCII 名保持不变（仅小写化 + 非法字符替换）；
    含中文等非 ASCII 字符时，用原名 MD5 短哈希生成唯一标识。
    """
    import re
    import hashlib

    slug = re.sub(r'[^a-zA-Z0-9_.-]', '-', name).strip('-')
    slug = re.sub(r'-+', '-', slug)

    if len(slug) < 2:
        h = hashlib.md5(name.encode('utf-8')).hexdigest()[:8]
        slug = f"proj-{h}" if not slug else f"{slug}-{h}"

    return slug.lower()


def validate_project_name(name: str) -> bool:
    if not name or len(name) < 2:
        return False
    invalid_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
    return not any(c in name for c in invalid_chars)


def generate_project_name(template: str = "project-{date}-{random}") -> str:
    import random
    import string
    now = datetime.now()
    replacements = {
        "{timestamp}": str(int(now.timestamp())),
        "{date}": now.strftime("%Y%m%d"),
        "{time}": now.strftime("%H%M%S"),
        "{random}": ''.join(random.choices(string.ascii_lowercase + string.digits, k=4)),
    }
    name = template
    for key, value in replacements.items():
        name = name.replace(key, value)
    return name
