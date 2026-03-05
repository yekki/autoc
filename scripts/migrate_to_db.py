#!/usr/bin/env python3
"""AutoC JSON → SQLite 一次性迁移脚本

迁移内容:
  workspace/{project}/autoc-project.json  → autoc.db (project + dev_sessions + milestones)
  workspace/{project}/autoc-tasks.json    → autoc.db (requirements + tasks)
  .autoc_sessions.json                    → .autoc.db (run_sessions)
  .autoc_experience/experiences.json      → .autoc.db (experiences)
  .autoc_experience/patterns.json         → .autoc.db (experience_patterns)

用法:
  python scripts/migrate_to_db.py
  python scripts/migrate_to_db.py --workspace ./workspace --dry-run
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

# 确保能 import autoc 包
AUTOC_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(AUTOC_ROOT))


def load_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"  ⚠️  读取失败 {path}: {e}")
        return None


def migrate_project(project_dir: str, dry_run: bool = False) -> bool:
    """迁移单个项目目录"""
    folder = os.path.basename(project_dir)
    proj_file = os.path.join(project_dir, "autoc-project.json")
    tasks_file = os.path.join(project_dir, "autoc-tasks.json")
    db_file = os.path.join(project_dir, "autoc.db")

    if not os.path.exists(proj_file):
        return False

    if os.path.exists(db_file):
        print(f"  ✅ 已迁移，跳过: {folder}/autoc.db")
        return True

    proj_data = load_json(proj_file)
    if not proj_data:
        return False

    tasks_data = load_json(tasks_file) or {}
    requirements = tasks_data.get("requirements", [])
    tasks = tasks_data.get("tasks", [])

    print(f"  📦 迁移项目: {proj_data.get('name', folder)}")
    print(f"     需求: {len(requirements)}, 任务: {len(tasks)}")

    if dry_run:
        return True

    from autoc.core.infra.db import ProjectDB, jdump
    from datetime import datetime

    db = ProjectDB(project_dir)
    now = datetime.now().isoformat()

    with db.write() as conn:
        # ── project 表 ──────────────────────────────────────────────
        conn.execute(
            """INSERT OR REPLACE INTO project
               (id, name, description, project_path, status, version,
                tech_stack, architecture, total_tokens, git_enabled,
                autoc_version, created_at, updated_at)
               VALUES ('main',?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                proj_data.get("name", folder),
                proj_data.get("description", ""),
                proj_data.get("project_path", project_dir),
                proj_data.get("status", "planning"),
                proj_data.get("version", "0.1.0"),
                jdump(proj_data.get("tech_stack", [])),
                proj_data.get("architecture", ""),
                proj_data.get("total_tokens", 0),
                1 if proj_data.get("git_enabled", True) else 0,
                proj_data.get("autoc_version", "0.1.0"),
                proj_data.get("created_at", now),
                proj_data.get("updated_at", now),
            ),
        )

        # ── dev_sessions 表 ─────────────────────────────────────────
        for sess in proj_data.get("sessions", []):
            conn.execute(
                """INSERT INTO dev_sessions
                   (requirement_id, requirement, success,
                    tasks_completed, tasks_total,
                    requirements_completed, requirements_total,
                    elapsed_seconds, total_tokens, notes, timestamp)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    sess.get("requirement_id", ""),
                    sess.get("requirement", "")[:200],
                    1 if sess.get("success") else 0,
                    sess.get("tasks_completed", 0),
                    sess.get("tasks_total", 0),
                    sess.get("requirements_completed", 0),
                    sess.get("requirements_total", 0),
                    sess.get("elapsed_seconds", 0.0),
                    sess.get("total_tokens", 0),
                    sess.get("notes", ""),
                    sess.get("timestamp", now),
                ),
            )

        # ── milestones 表 ───────────────────────────────────────────
        for ms in proj_data.get("milestones", []):
            conn.execute(
                "INSERT INTO milestones (title, description, version, timestamp) VALUES (?,?,?,?)",
                (
                    ms.get("title", ""),
                    ms.get("description", ""),
                    ms.get("version", ""),
                    ms.get("timestamp", now),
                ),
            )

        # ── requirements 表 ─────────────────────────────────────────
        for req in requirements:
            conn.execute(
                """INSERT OR REPLACE INTO requirements
                   (id, title, description, status, priority,
                    acceptance_criteria, pre_pause_status, pause_reason,
                    status_notes, tokens_used, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    req.get("id", ""),
                    req.get("title", ""),
                    req.get("description", ""),
                    req.get("status", "pending"),
                    req.get("priority", 0),
                    jdump(req.get("acceptance_criteria", [])),
                    req.get("pre_pause_status", ""),
                    req.get("pause_reason", ""),
                    req.get("status_notes", ""),
                    req.get("tokens_used", 0),
                    req.get("created_at", now),
                    req.get("updated_at", now),
                ),
            )

        # ── tasks 表 ────────────────────────────────────────────────
        for t in tasks:
            conn.execute(
                """INSERT OR REPLACE INTO tasks
                   (id, title, description, status, assignee, priority,
                    dependencies, files, result, error, requirement_id,
                    verification_steps, passes, verified_at, verification_notes,
                    block_reason, block_attempts, block_context,
                    created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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
                    t.get("requirement_id", ""),
                    jdump(t.get("verification_steps", [])),
                    1 if t.get("passes", False) else 0,
                    t.get("verified_at", ""),
                    t.get("verification_notes", ""),
                    t.get("block_reason", ""),
                    t.get("block_attempts", 0),
                    t.get("block_context", ""),
                    t.get("created_at", now),
                    t.get("updated_at", now),
                ),
            )

    print(f"     ✅ autoc.db 写入完成")
    return True


def migrate_global(autoc_root: str, dry_run: bool = False):
    """迁移全局文件（sessions + experiences）"""
    sessions_file = os.path.join(autoc_root, ".autoc_sessions.json")
    exp_file = os.path.join(autoc_root, ".autoc_experience", "experiences.json")
    patterns_file = os.path.join(autoc_root, ".autoc_experience", "patterns.json")
    db_file = os.path.join(autoc_root, ".autoc.db")

    has_global = (
        os.path.exists(sessions_file)
        or os.path.exists(exp_file)
        or os.path.exists(patterns_file)
    )
    if not has_global:
        print("  ℹ️  无全局 JSON 文件，跳过")
        return

    sessions_data = []
    if os.path.exists(sessions_file):
        raw = load_json(sessions_file)
        if isinstance(raw, list):
            sessions_data = raw
        elif isinstance(raw, dict):
            sessions_data = raw.get("sessions", [])

    experiences_data = []
    if os.path.exists(exp_file):
        raw = load_json(exp_file)
        if isinstance(raw, list):
            experiences_data = raw

    patterns_data = {}
    if os.path.exists(patterns_file):
        raw = load_json(patterns_file)
        if isinstance(raw, dict):
            patterns_data = raw

    print(f"  🌐 迁移全局数据: {len(sessions_data)} 条会话, "
          f"{len(experiences_data)} 条经验")

    if dry_run:
        return

    from autoc.core.infra.db import GlobalDB, jdump
    from datetime import datetime

    db = GlobalDB(autoc_root)
    now_ts = time.time()

    with db.write() as conn:
        # ── run_sessions ─────────────────────────────────────────────
        for s in sessions_data:
            conn.execute(
                """INSERT OR REPLACE INTO run_sessions
                   (session_id, requirement, source, preset, status,
                    started_at, ended_at, workspace_dir, project_name,
                    has_events, pid)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    s.get("session_id", ""),
                    s.get("requirement", "")[:500],
                    s.get("source", "cli"),
                    s.get("preset", ""),
                    s.get("status", "completed"),
                    s.get("started_at", now_ts),
                    s.get("ended_at"),
                    s.get("workspace_dir", ""),
                    s.get("project_name", ""),
                    1 if s.get("has_events") else 0,
                    s.get("pid"),
                ),
            )

        # ── experiences ──────────────────────────────────────────────
        for exp in experiences_data:
            conn.execute(
                """INSERT INTO experiences
                   (exp_id, requirement_summary, project_name, tech_stack,
                    architecture, directory_structure, file_count, files_sample,
                    bugs_found_count, bugs_fixed_count, common_issues,
                    quality_score, success, elapsed_seconds, total_tokens,
                    failure_reason, rounds_attempted, unresolved_bugs, timestamp)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    exp.get("id", ""),
                    exp.get("requirement_summary", "")[:200],
                    exp.get("project_name", ""),
                    jdump(exp.get("tech_stack", [])),
                    exp.get("architecture", "")[:300],
                    exp.get("directory_structure", "")[:500],
                    exp.get("file_count", 0),
                    jdump(exp.get("files_sample", [])),
                    exp.get("bugs_found_count", 0),
                    exp.get("bugs_fixed_count", 0),
                    jdump(exp.get("common_issues", [])),
                    exp.get("quality_score", 0),
                    1 if exp.get("success", True) else 0,
                    exp.get("elapsed_seconds", 0.0),
                    exp.get("total_tokens", 0),
                    exp.get("failure_reason", "")[:300],
                    exp.get("rounds_attempted", 0),
                    jdump(exp.get("unresolved_bugs", [])),
                    exp.get("timestamp", datetime.now().isoformat()),
                ),
            )

        # ── experience_patterns ──────────────────────────────────────
        for keyword, tech_counts in patterns_data.items():
            if not isinstance(tech_counts, dict):
                continue
            for tech_str, count in tech_counts.items():
                conn.execute(
                    """INSERT INTO experience_patterns (keyword, tech_stack, count)
                       VALUES (?,?,?)
                       ON CONFLICT(keyword, tech_stack) DO UPDATE SET count=count+?""",
                    (keyword, tech_str, count, count),
                )

    print(f"     ✅ .autoc.db 写入完成")


def main():
    parser = argparse.ArgumentParser(description="AutoC JSON → SQLite 迁移工具")
    parser.add_argument(
        "--workspace", default="./workspace",
        help="workspace 目录路径（默认: ./workspace）"
    )
    parser.add_argument(
        "--autoc-root", default=".",
        help="autoc 项目根目录（含 .autoc_sessions.json，默认: 当前目录）"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="只显示将迁移什么，不实际写入"
    )
    args = parser.parse_args()

    workspace = os.path.abspath(args.workspace)
    autoc_root = os.path.abspath(args.autoc_root)

    print(f"\n{'='*50}")
    print(f"AutoC JSON → SQLite 迁移")
    print(f"workspace: {workspace}")
    print(f"autoc_root: {autoc_root}")
    print(f"dry_run: {args.dry_run}")
    print(f"{'='*50}\n")

    # 迁移各项目
    project_count = 0
    if os.path.exists(workspace):
        print("📁 迁移项目数据...")
        for item in sorted(os.listdir(workspace)):
            project_dir = os.path.join(workspace, item)
            if not os.path.isdir(project_dir):
                continue
            if migrate_project(project_dir, dry_run=args.dry_run):
                project_count += 1

    # 迁移全局数据
    print("\n🌐 迁移全局数据...")
    migrate_global(autoc_root, dry_run=args.dry_run)

    print(f"\n{'='*50}")
    if args.dry_run:
        print(f"✅ dry-run 完成，共发现 {project_count} 个项目可迁移")
        print("   去掉 --dry-run 参数后再次运行以实际迁移")
    else:
        print(f"✅ 迁移完成！共迁移 {project_count} 个项目")
        print("\n旧 JSON 文件保留未删除，确认无误后可手动清理:")
        print(f"  find {workspace} -name 'autoc-project.json' -o -name 'autoc-tasks.json'")
        print(f"  {autoc_root}/.autoc_sessions.json")
        print(f"  {autoc_root}/.autoc_experience/")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()
