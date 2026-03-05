#!/usr/bin/env python3
"""迁移脚本: 去除 Requirement 层

将现有项目 DB 中 tasks.requirement_id 的值保留为 feature_tag（向后兼容）。
requirements 表保留但不再写入。

用法:
    python scripts/migrate_drop_requirements.py [workspace_root]
"""

import os
import sqlite3
import sys


def migrate_project(project_path: str) -> bool:
    """迁移单个项目的 autoc.db"""
    db_path = os.path.join(project_path, "autoc.db")
    if not os.path.exists(db_path):
        return False

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()

        # 检查 tasks 表是否有 requirement_id 列
        cols = [row[1] for row in cursor.execute("PRAGMA table_info(tasks)").fetchall()]
        if "requirement_id" not in cols:
            print(f"  [跳过] {project_path} — tasks 表无 requirement_id 列")
            return False

        # requirement_id 值作为 feature_tag 保留在同一列中，无需实际迁移列
        # 只需确认数据仍可正常读取即可
        task_count = cursor.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        req_count = cursor.execute(
            "SELECT COUNT(DISTINCT requirement_id) FROM tasks WHERE requirement_id != ''"
        ).fetchone()[0]

        print(f"  [OK] {project_path} — {task_count} 个任务, {req_count} 个 feature_tag 值")
        conn.commit()
        return True
    except Exception as e:
        print(f"  [错误] {project_path}: {e}")
        return False
    finally:
        conn.close()


def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "./workspace"
    workspace_root = os.path.abspath(workspace_root)

    if not os.path.isdir(workspace_root):
        print(f"工作区不存在: {workspace_root}")
        sys.exit(1)

    print(f"扫描工作区: {workspace_root}\n")

    migrated = 0
    for name in sorted(os.listdir(workspace_root)):
        project_path = os.path.join(workspace_root, name)
        if not os.path.isdir(project_path):
            continue
        if migrate_project(project_path):
            migrated += 1

    print(f"\n迁移完成: {migrated} 个项目已检查")


if __name__ == "__main__":
    main()
