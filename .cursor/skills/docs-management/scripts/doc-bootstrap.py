#!/usr/bin/env python3
"""文档骨架生成脚本 — 扫描代码库并输出建议的文档结构。

用法：python .cursor/skills/docs-management/scripts/doc-bootstrap.py [项目根目录]

输出 JSON 格式的文档生成计划，供 AI Agent 消费。
"""

import json
import sys
from pathlib import Path


def find_project_root(start: Path = Path.cwd()) -> Path:
    current = start
    while current != current.parent:
        if (current / "AGENTS.md").exists() or (current / "requirements.txt").exists():
            return current
        current = current.parent
    return start


def scan_python_packages(root: Path) -> list[dict]:
    """扫描 Python 包结构。"""
    packages = []
    autoc_dir = root / "autoc"
    if not autoc_dir.is_dir():
        return packages

    for init in sorted(autoc_dir.rglob("__init__.py")):
        pkg_dir = init.parent
        rel = str(pkg_dir.relative_to(root))
        py_files = sorted([f.name for f in pkg_dir.glob("*.py") if f.name != "__init__.py"])
        if py_files:
            classes = []
            for pf in py_files:
                content = (pkg_dir / pf).read_text(encoding="utf-8", errors="ignore")
                for line in content.split("\n"):
                    if line.startswith("class ") and "(" in line:
                        cls_name = line.split("class ")[1].split("(")[0].strip()
                        classes.append(cls_name)
            packages.append({
                "path": rel,
                "files": py_files,
                "classes": classes[:10],
            })
    return packages


def scan_web_structure(root: Path) -> dict:
    """扫描前端结构。"""
    web_src = root / "web" / "src"
    if not web_src.is_dir():
        return {}

    structure = {}
    for d in ["components", "stores", "utils", "hooks", "pages"]:
        sub = web_src / d
        if sub.is_dir():
            files = sorted([str(f.relative_to(sub)) for f in sub.rglob("*") if f.is_file() and f.suffix in (".js", ".jsx", ".ts", ".tsx")])
            if files:
                structure[d] = files
    return structure


def detect_tech_stack(root: Path) -> list[str]:
    """检测技术栈。"""
    stack = []
    if (root / "requirements.txt").is_file():
        stack.append("Python")
        content = (root / "requirements.txt").read_text(errors="ignore")
        if "fastapi" in content.lower():
            stack.append("FastAPI")
        if "pydantic" in content.lower():
            stack.append("Pydantic")
    if (root / "package.json").is_file():
        stack.append("Node.js")
        content = (root / "package.json").read_text(errors="ignore")
        if "react" in content.lower():
            stack.append("React")
    if (root / "Dockerfile").is_file() or (root / "docker-compose.yml").is_file():
        stack.append("Docker")
    return stack


def suggest_design_docs(packages: list[dict]) -> list[dict]:
    """根据代码包结构建议 design 文档。"""
    GROUP_MAP = {
        "autoc/agents": "Agent系统设计",
        "autoc/core/orchestrator": "编排器",
        "autoc/core/llm": "LLM客户端",
        "autoc/core/project": "项目管理",
        "autoc/core/runtime": "运行时沙箱",
        "autoc/core/planning": "规划引擎",
        "autoc/core/security": "安全框架",
        "autoc/core/critic": "评审框架",
        "autoc/core/analysis": "分析基础设施",
        "autoc/core/infra": "分析基础设施",
        "autoc/core/conversation": "对话与事件系统",
        "autoc/core/event": "对话与事件系统",
        "autoc/core/skill": "技能系统",
        "autoc/tools": "工具系统",
        "autoc/stacks": "工具系统",
        "autoc/prompts": "Prompt系统",
        "autoc/server": "Web前端",
    }

    suggestions = {}
    for pkg in packages:
        doc_name = None
        for prefix, name in GROUP_MAP.items():
            if pkg["path"].startswith(prefix):
                doc_name = name
                break
        if doc_name:
            if doc_name not in suggestions:
                suggestions[doc_name] = {"name": doc_name, "modules": [], "classes": []}
            suggestions[doc_name]["modules"].append(pkg["path"])
            suggestions[doc_name]["classes"].extend(pkg["classes"])

    return list(suggestions.values())


def main():
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else find_project_root()

    packages = scan_python_packages(root)
    web = scan_web_structure(root)
    stack = detect_tech_stack(root)
    design_suggestions = suggest_design_docs(packages)

    result = {
        "project_root": str(root),
        "tech_stack": stack,
        "python_packages": len(packages),
        "web_structure": {k: len(v) for k, v in web.items()} if web else None,
        "suggested_design_docs": design_suggestions,
        "suggested_guides": [
            "使用手册",
            "Web界面指南",
            "项目管理指南",
        ],
    }

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
