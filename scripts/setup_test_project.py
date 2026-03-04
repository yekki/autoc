#!/usr/bin/env python3
"""测试项目初始化脚本

通过 Web API 创建样例项目（Todo 应用），供 Playwright E2E 测试使用。

用法：
    python scripts/setup_test_project.py           # 创建项目 + 启动执行
    python scripts/setup_test_project.py --no-run  # 仅创建项目，不启动执行
    python scripts/setup_test_project.py --clean   # 先删除已有同名项目再创建
    python scripts/setup_test_project.py --list    # 列出当前所有项目

输出（JSON 到 stdout）：
    {"status": "ok", "project_name": "...", "session_id": "..."}
"""

import argparse
import json
import sys
import time

import requests

DEFAULT_BASE_URL = "http://localhost:8080/api/v1"

# 样例项目默认配置
DEFAULT_PROJECT_NAME = "todo-demo"
PROJECT_DESCRIPTION = (
    "一个简单的 Todo 待办事项 Web 应用，支持添加、完成、删除任务，"
    "数据持久化存储，界面简洁美观。"
)
PROJECT_TECH_STACK = ["Python", "Flask", "SQLite", "HTML/CSS/JS"]
PROJECT_REQUIREMENT = (
    "创建一个 Todo 待办事项 Web 应用：\n"
    "1. 添加新任务（文本输入 + 回车/按钮提交）\n"
    "2. 标记任务为已完成（点击复选框）\n"
    "3. 删除任务（删除按钮）\n"
    "4. 显示任务统计（总数/已完成数）\n"
    "5. 数据持久化（SQLite）\n"
    "6. Flask 后端 + 原生 HTML/CSS/JS 前端，无需构建工具"
)


class ApiClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def check_server(self, timeout: int = 5) -> bool:
        try:
            resp = requests.get(f"{self.base_url}/projects", timeout=timeout)
            return resp.status_code in (200, 401)
        except requests.exceptions.ConnectionError:
            return False

    def wait_for_server(self, max_wait: int = 30) -> bool:
        print(f"⏳ 等待后端服务启动（最多 {max_wait}s）...", file=sys.stderr)
        for i in range(max_wait):
            if self.check_server():
                print("✅ 后端服务已就绪", file=sys.stderr)
                return True
            time.sleep(1)
            if i % 5 == 4:
                print(f"   已等待 {i+1}s...", file=sys.stderr)
        return False

    def list_projects(self) -> list:
        resp = requests.get(f"{self.base_url}/projects", timeout=10)
        resp.raise_for_status()
        return resp.json()

    def delete_project(self, name: str) -> bool:
        resp = requests.delete(
            f"{self.base_url}/projects/{name}",
            json={"force": True},
            timeout=10,
        )
        if resp.status_code == 404:
            return True
        resp.raise_for_status()
        return resp.json().get("success", False)

    def create_project(self, name: str, description: str, tech_stack: list) -> dict:
        resp = requests.post(
            f"{self.base_url}/projects",
            json={
                "name": name,
                "folder": name,
                "description": description,
                "tech_stack": tech_stack,
                "git_enabled": False,
                "single_task": False,
            },
            timeout=15,
        )
        if resp.status_code == 409:
            return {"success": True, "already_exists": True}
        resp.raise_for_status()
        return resp.json()

    def start_run(self, requirement: str, project_name: str) -> dict:
        resp = requests.post(
            f"{self.base_url}/run",
            json={
                "requirement": requirement,
                "project_name": project_name,
                "mode": "full",
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def get_project(self, name: str) -> dict:
        resp = requests.get(f"{self.base_url}/projects/{name}", timeout=10)
        if resp.status_code == 404:
            return {}
        resp.raise_for_status()
        return resp.json()


def main():
    parser = argparse.ArgumentParser(description="创建 Playwright 测试用样例项目")
    parser.add_argument(
        "--no-run", action="store_true",
        help="仅创建项目，不启动 AI 执行流程",
    )
    parser.add_argument(
        "--clean", action="store_true",
        help="先删除已有同名项目再重新创建",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="列出当前所有项目并退出",
    )
    parser.add_argument(
        "--name", default=DEFAULT_PROJECT_NAME,
        help=f"项目名称（默认: {DEFAULT_PROJECT_NAME}）",
    )
    parser.add_argument(
        "--url", default=DEFAULT_BASE_URL,
        help=f"后端 API 地址（默认: {DEFAULT_BASE_URL}）",
    )
    parser.add_argument(
        "--wait", action="store_true",
        help="如果服务未启动则等待（最多 30s）",
    )
    args = parser.parse_args()

    client = ApiClient(args.url)

    # 检查服务可用性
    if not client.check_server():
        if args.wait:
            if not client.wait_for_server():
                print(json.dumps({
                    "status": "error",
                    "message": "后端服务未启动，请先执行: ./scripts/pm2-manage.sh dev",
                }))
                sys.exit(1)
        else:
            print(json.dumps({
                "status": "error",
                "message": "后端服务未启动，请先执行: ./scripts/pm2-manage.sh dev",
            }))
            sys.exit(1)

    # --list: 列出所有项目
    if args.list:
        projects = client.list_projects()
        print(json.dumps({"status": "ok", "projects": projects}, ensure_ascii=False, indent=2))
        return

    project_name = args.name

    # --clean: 删除已有项目
    if args.clean:
        print(f"🗑  删除已有项目: {project_name}", file=sys.stderr)
        client.delete_project(project_name)
        time.sleep(0.5)

    # 创建项目
    print(f"📦 创建项目: {project_name}", file=sys.stderr)
    create_result = client.create_project(project_name, PROJECT_DESCRIPTION, PROJECT_TECH_STACK)

    if create_result.get("already_exists"):
        print("ℹ️  项目已存在，跳过创建（使用 --clean 可先删除）", file=sys.stderr)
    else:
        print("✅ 项目已创建", file=sys.stderr)

    result = {
        "status": "ok",
        "project_name": project_name,
        "session_id": None,
        "api_url": args.url,
        "web_url": "http://localhost:3000",
    }

    # 启动执行
    if not args.no_run:
        print("🚀 启动 AI 执行流程...", file=sys.stderr)
        run_result = client.start_run(PROJECT_REQUIREMENT, project_name)
        session_id = run_result.get("session_id", "")
        result["session_id"] = session_id
        print(f"✅ 执行已启动，session_id: {session_id}", file=sys.stderr)
        print(f"   SSE 事件流: GET {args.url}/events/{session_id}", file=sys.stderr)
    else:
        print("⏭  跳过执行（--no-run）", file=sys.stderr)

    # 输出 JSON 结果（供 Playwright globalSetup 解析）
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
