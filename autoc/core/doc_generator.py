"""文档自动生成 — Agent 完成后自动生成 README + API 文档

在项目开发完成后，自动从代码结构和项目元数据生成文档。
"""

import logging
import os
import re
from pathlib import Path

logger = logging.getLogger("autoc.doc_generator")


def generate_readme(workspace_dir: str) -> str:
    """从项目元数据和文件结构自动生成 README.md"""
    from autoc.core.project import ProjectManager
    from autoc.core.project.progress import ProgressTracker

    pm = ProjectManager(workspace_dir)
    metadata = pm.load()
    pt = ProgressTracker(workspace_dir)
    tasks = pt.load_tasks()

    project_name = metadata.name if metadata else os.path.basename(workspace_dir)
    description = metadata.description if metadata else ""
    tech_stack = metadata.tech_stack if metadata else []

    # 扫描文件结构
    file_tree = _build_file_tree(workspace_dir)

    # 检测入口文件和启动方式
    start_cmd = _detect_start_command(workspace_dir, tech_stack)

    # 构建 README
    sections = [
        f"# {project_name}\n",
        f"{description}\n" if description else "",
    ]

    if tech_stack:
        sections.append(f"## 技术栈\n\n{', '.join(tech_stack)}\n")

    if start_cmd:
        sections.append(f"## 快速开始\n\n```bash\n{start_cmd}\n```\n")

    if file_tree:
        sections.append(f"## 项目结构\n\n```\n{file_tree}\n```\n")

    if tasks:
        sections.append("## 功能列表\n")
        for t in tasks:
            status = "✅" if t.get("passes") else "⬜"
            sections.append(f"- {status} {t.get('title', '')}")
        sections.append("")

    # 检测 API 路由
    api_docs = _extract_api_routes(workspace_dir)
    if api_docs:
        sections.append(f"## API 文档\n\n{api_docs}\n")

    sections.append(
        "\n---\n\n"
        f"> 由 [AutoC](https://github.com/autoc) 自动生成\n"
    )

    return "\n".join(sections)


def generate_and_save(workspace_dir: str) -> str | None:
    """生成并保存 README.md，返回文件路径"""
    readme_path = os.path.join(workspace_dir, "README.md")

    # 如果已有手写的 README，不覆盖
    if os.path.exists(readme_path):
        content = Path(readme_path).read_text(encoding="utf-8", errors="ignore")
        if content.strip() and "由 [AutoC]" not in content:
            logger.info("已有手写 README.md，跳过自动生成")
            return None

    content = generate_readme(workspace_dir)
    Path(readme_path).write_text(content, encoding="utf-8")
    logger.info(f"README.md 已自动生成: {readme_path}")
    return readme_path


def _build_file_tree(workspace_dir: str, max_depth: int = 3) -> str:
    """构建简化的文件树"""
    skip_dirs = {".git", "__pycache__", "node_modules", ".venv", "venv",
                 "dist", "build", ".pytest_cache", ".autoc", ".mypy_cache"}
    skip_files = {".autoc.db", ".DS_Store", "autoc-progress.txt"}
    lines = []

    def _walk(dir_path: str, prefix: str, depth: int):
        if depth > max_depth:
            return
        try:
            entries = sorted(os.listdir(dir_path))
        except OSError:
            return
        dirs = [e for e in entries if os.path.isdir(os.path.join(dir_path, e)) and e not in skip_dirs]
        files = [e for e in entries if os.path.isfile(os.path.join(dir_path, e)) and e not in skip_files]

        for i, d in enumerate(dirs):
            is_last = (i == len(dirs) - 1 and not files)
            connector = "└── " if is_last else "├── "
            lines.append(f"{prefix}{connector}{d}/")
            next_prefix = prefix + ("    " if is_last else "│   ")
            _walk(os.path.join(dir_path, d), next_prefix, depth + 1)

        for i, f in enumerate(files):
            is_last = (i == len(files) - 1)
            connector = "└── " if is_last else "├── "
            lines.append(f"{prefix}{connector}{f}")

    _walk(workspace_dir, "", 0)
    return "\n".join(lines[:50])


def _detect_start_command(workspace_dir: str, tech_stack: list[str]) -> str:
    """检测项目启动命令"""
    files = set(os.listdir(workspace_dir))
    tech = set(t.lower() for t in tech_stack)

    if "package.json" in files:
        return "npm install\nnpm start"
    if "requirements.txt" in files:
        if "flask" in tech:
            return "pip install -r requirements.txt\npython -m flask run"
        if "fastapi" in tech:
            return "pip install -r requirements.txt\nuvicorn main:app --reload"
        return "pip install -r requirements.txt\npython main.py"
    if "go.mod" in files:
        return "go run ."
    if "Cargo.toml" in files:
        return "cargo run"
    if "main.py" in files:
        return "python main.py"
    return ""


def _extract_api_routes(workspace_dir: str) -> str:
    """从源码中提取 API 路由文档"""
    routes = []
    for root, _, files in os.walk(workspace_dir):
        for filename in files:
            if not filename.endswith(".py"):
                continue
            filepath = os.path.join(root, filename)
            try:
                content = Path(filepath).read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            # Flask/FastAPI 路由
            for m in re.finditer(
                r'@\w+\.(get|post|put|delete|patch)\(\s*["\']([^"\']+)["\']',
                content, re.IGNORECASE,
            ):
                method = m.group(1).upper()
                path = m.group(2)
                routes.append(f"| `{method}` | `{path}` |")

    if not routes:
        return ""
    header = "| 方法 | 路径 |\n|------|------|\n"
    return header + "\n".join(routes[:30])
