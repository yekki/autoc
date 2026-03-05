#!/usr/bin/env python3
"""
迁移脚本：将旧 JSON 格式项目迁移到新 SQLite (autoc.db) 格式

旧格式:
  - autoc-tasks.json     → requirements + tasks 数据
  - project-plan.json    → 项目元数据（技术栈、架构等）
  - autoc-progress.txt   → 会话日志（只读，保留原文件）

新格式:
  - autoc.db             → SQLite 数据库（project + requirements + tasks + dev_sessions）

用法:
  cd /path/to/autoc
  python scripts/migrate_to_sqlite.py [workspace_root]

  workspace_root 默认为 ./workspace
"""

import json
import os
import sys
import sqlite3
from datetime import datetime

# 添加项目根目录到 Python 路径
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.insert(0, project_root)


def migrate_project(project_dir: str):
    """迁移单个项目目录"""
    project_name = os.path.basename(project_dir)
    db_path = os.path.join(project_dir, "autoc.db")

    if os.path.exists(db_path):
        print(f"  ⏭  [{project_name}] 已有 autoc.db，跳过")
        return

    tasks_file = os.path.join(project_dir, "autoc-tasks.json")
    plan_file = os.path.join(project_dir, "project-plan.json")

    if not os.path.exists(tasks_file):
        print(f"  ⚠️  [{project_name}] 无 autoc-tasks.json，跳过")
        return

    print(f"  🔄 [{project_name}] 开始迁移...")

    # ── 读取旧数据 ──────────────────────────────────────────────────
    with open(tasks_file, encoding="utf-8") as f:
        tasks_data = json.load(f)

    plan_data = {}
    if os.path.exists(plan_file):
        with open(plan_file, encoding="utf-8") as f:
            plan_data = json.load(f)

    requirements = tasks_data.get("requirements", [])
    tasks = tasks_data.get("tasks", [])
    now = datetime.now().isoformat()

    # 项目元数据
    proj_name = plan_data.get("project_name") or project_name
    description = plan_data.get("description", "")
    tech_stack = json.dumps(plan_data.get("tech_stack", []), ensure_ascii=False)
    architecture = plan_data.get("architecture", "")
    updated_at = tasks_data.get("updated_at", now)

    # ── 创建 SQLite 数据库 ──────────────────────────────────────────
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

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
        updated_at  TEXT NOT NULL DEFAULT '',
        FOREIGN KEY (requirement_id) REFERENCES requirements(id)
    );
    CREATE INDEX IF NOT EXISTS idx_tasks_req ON tasks(requirement_id);

    CREATE TABLE IF NOT EXISTS dev_sessions (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        requirement_id TEXT DEFAULT '',
        requirement TEXT DEFAULT '',
        success     INTEGER DEFAULT 0,
        tasks_completed INTEGER DEFAULT 0,
        tasks_total INTEGER DEFAULT 0,
        requirements_completed INTEGER DEFAULT 0,
        requirements_total INTEGER DEFAULT 0,
        elapsed_seconds REAL DEFAULT 0,
        total_tokens INTEGER DEFAULT 0,
        notes       TEXT DEFAULT '',
        timestamp   TEXT NOT NULL DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS milestones (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        title       TEXT NOT NULL DEFAULT '',
        description TEXT DEFAULT '',
        version     TEXT DEFAULT '',
        timestamp   TEXT NOT NULL DEFAULT ''
    );
    """)

    # ── 写入项目元数据 ──────────────────────────────────────────────
    # 根据任务状态推导项目状态
    all_passes = all(t.get("passes", False) for t in tasks) if tasks else False
    any_started = any(t.get("status") != "pending" for t in tasks) if tasks else False
    if all_passes and tasks:
        proj_status = "completed"
    elif any_started:
        proj_status = "in_progress"
    else:
        proj_status = "planning"

    # 计算 total_tokens
    total_tokens = sum(r.get("tokens_used", 0) for r in requirements)

    conn.execute(
        """INSERT OR REPLACE INTO project
           (id, name, description, project_path, status, version,
            tech_stack, architecture, total_tokens, git_enabled,
            autoc_version, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "main",
            proj_name,
            description,
            project_dir,
            proj_status,
            "0.1.0",
            tech_stack,
            architecture,
            total_tokens,
            1,
            "0.1.0",
            requirements[0].get("created_at", now) if requirements else now,
            updated_at,
        ),
    )

    # ── 写入需求 ────────────────────────────────────────────────────
    for req in requirements:
        conn.execute(
            """INSERT OR REPLACE INTO requirements
               (id, title, description, status, priority,
                acceptance_criteria, tokens_used, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                req.get("id", ""),
                req.get("title", ""),
                req.get("description", ""),
                req.get("status", "pending"),
                req.get("priority", 0),
                json.dumps(req.get("acceptance_criteria", []), ensure_ascii=False),
                req.get("tokens_used", 0),
                req.get("created_at", now),
                req.get("updated_at", now),
            ),
        )

    # ── 写入任务 ────────────────────────────────────────────────────
    for task in tasks:
        req_id = task.get("requirement_id", "")
        # 如果没有 requirement_id（旧格式），绑定到第一个需求
        if not req_id and requirements:
            req_id = requirements[0]["id"]

        conn.execute(
            """INSERT OR REPLACE INTO tasks
               (id, title, description, status, assignee, priority,
                dependencies, files, result, error,
                requirement_id, verification_steps, passes,
                created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                task.get("id", ""),
                task.get("title", ""),
                task.get("description", ""),
                task.get("status", "pending"),
                task.get("assignee", ""),
                task.get("priority", 0),
                json.dumps(task.get("dependencies", []), ensure_ascii=False),
                json.dumps(task.get("files", []), ensure_ascii=False),
                task.get("result", ""),
                task.get("error", ""),
                req_id,
                json.dumps(task.get("verification_steps", []), ensure_ascii=False),
                1 if task.get("passes") else 0,
                task.get("created_at", now),
                task.get("updated_at", now),
            ),
        )

    conn.commit()
    conn.close()

    req_count = len(requirements)
    task_count = len(tasks)
    print(f"  ✅ [{project_name}] 迁移完成: {req_count} 个需求, {task_count} 个任务 → {db_path}")


def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else os.path.join(project_root, "workspace")
    workspace_root = os.path.abspath(workspace_root)

    print(f"🔍 扫描工作区: {workspace_root}")

    if not os.path.exists(workspace_root):
        print("❌ workspace 目录不存在")
        sys.exit(1)

    migrated = 0
    for item in sorted(os.listdir(workspace_root)):
        project_dir = os.path.join(workspace_root, item)
        if not os.path.isdir(project_dir):
            continue
        tasks_file = os.path.join(project_dir, "autoc-tasks.json")
        db_file = os.path.join(project_dir, "autoc.db")
        if os.path.exists(tasks_file) or os.path.exists(db_file):
            migrate_project(project_dir)
            migrated += 1

    if migrated == 0:
        print("⚠️  未找到任何需要迁移的项目")
    else:
        print(f"\n✨ 完成！共处理 {migrated} 个项目")


if __name__ == "__main__":
    main()
