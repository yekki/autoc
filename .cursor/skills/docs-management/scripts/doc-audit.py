#!/usr/bin/env python3
"""文档审计脚本 — 检查代码与文档的一致性。

用法：python .cursor/skills/docs-management/scripts/doc-audit.py [项目根目录]

输出审计报告：覆盖率、过时模块、缺失文档。
"""

import sys
import re
from pathlib import Path
from datetime import datetime


def find_project_root(start: Path = Path.cwd()) -> Path:
    current = start
    while current != current.parent:
        if (current / "AGENTS.md").exists():
            return current
        current = current.parent
    return start


def scan_code_modules(root: Path) -> dict[str, list[str]]:
    """扫描代码模块，返回 {模块路径: [py文件列表]}。"""
    modules = {}
    autoc_dir = root / "autoc"
    if not autoc_dir.is_dir():
        return modules

    for pkg in sorted(autoc_dir.rglob("__init__.py")):
        pkg_dir = pkg.parent
        rel = str(pkg_dir.relative_to(root))
        py_files = [f.name for f in pkg_dir.glob("*.py") if f.name != "__init__.py"]
        if py_files:
            modules[rel] = py_files

    web_src = root / "web" / "src"
    if web_src.is_dir():
        for d in ["components", "stores", "utils", "hooks"]:
            sub = web_src / d
            if sub.is_dir():
                js_files = [f.name for f in sub.rglob("*.jsx")] + [f.name for f in sub.rglob("*.js")]
                if js_files:
                    modules[f"web/src/{d}"] = js_files

    return modules


def parse_mapping(mapping_file: Path) -> dict[str, list[str]]:
    """解析 mapping.md，返回 {design文档: [覆盖的代码路径]}。"""
    doc_to_code: dict[str, list[str]] = {}
    if not mapping_file.is_file():
        return doc_to_code

    content = mapping_file.read_text(encoding="utf-8")
    # 匹配表格行：| PRD 文件 | 覆盖模块 | ...
    for line in content.split("\n"):
        match = re.match(r"\|\s*`(.+?\.md)`\s*\|\s*(.+?)\s*\|", line)
        if match:
            doc_name = match.group(1)
            code_refs = re.findall(r"`([^`]+\.py|[^`]+/)`?", match.group(2))
            doc_to_code[doc_name] = code_refs

    return doc_to_code


def main():
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else find_project_root()
    docs_dir = root / "docs"
    design_dir = docs_dir / "design"
    mapping_file = docs_dir / "mapping.md"

    print(f"\n🔍 AutoC 文档审计报告 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    # 1. 代码模块扫描
    modules = scan_code_modules(root)
    print(f"\n📦 代码模块: {len(modules)} 个包")
    for mod, files in modules.items():
        print(f"  {mod}/ ({len(files)} files)")

    # 2. Design 文档清单
    design_docs = []
    if design_dir.is_dir():
        design_docs = sorted([f.name for f in design_dir.glob("*.md")])
    print(f"\n📘 Design 文档: {len(design_docs)} 篇")
    for d in design_docs:
        print(f"  {d}")

    # 3. 映射覆盖分析
    doc_to_code = parse_mapping(mapping_file)
    all_mapped_paths = set()
    for paths in doc_to_code.values():
        all_mapped_paths.update(paths)

    covered = 0
    uncovered = []
    for mod in modules:
        if any(mod in p or p in mod for p in all_mapped_paths):
            covered += 1
        else:
            uncovered.append(mod)

    total = len(modules)
    rate = (covered / total * 100) if total > 0 else 0
    print(f"\n📊 映射覆盖率: {covered}/{total} ({rate:.0f}%)")

    if uncovered:
        print(f"\n⚠️  未覆盖的代码模块 ({len(uncovered)}):")
        for u in uncovered:
            print(f"  • {u}")

    # 4. 孤立文档（design 文档不在 mapping 中）
    mapped_docs = set(doc_to_code.keys())
    orphan_docs = [d for d in design_docs if d not in mapped_docs]
    if orphan_docs:
        print(f"\n⚠️  孤立 design 文档（不在 mapping.md 中）:")
        for o in orphan_docs:
            print(f"  • {o}")

    # 5. Research 文档状态
    research_dir = docs_dir / "research"
    if research_dir.is_dir():
        research_docs = sorted(research_dir.glob("*.md"))
        active = archived = outdated = 0
        for rd in research_docs:
            content = rd.read_text(encoding="utf-8")[:500]
            if "🟢" in content or "活跃" in content:
                active += 1
            elif "🔴" in content or "已归档" in content:
                archived += 1
            elif "🟡" in content or "过时" in content:
                outdated += 1
            else:
                active += 1
        print(f"\n🔬 Research 文档: {len(research_docs)} 篇 (🟢{active} 🟡{outdated} 🔴{archived})")

    print(f"\n{'=' * 60}")
    print("审计完成。")

    sys.exit(0)


if __name__ == "__main__":
    main()
