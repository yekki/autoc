#!/usr/bin/env python3
"""文档校验脚本 — 检查文档体系的结构完整性。

用法：python .cursor/skills/docs-management/scripts/doc-validate.py [项目根目录]
"""

import sys
import re
from pathlib import Path

REQUIRED_DIRS = ["design", "research", "guides", "archive"]
REQUIRED_FILES = ["README.md", "mapping.md"]
DESIGN_REQUIRED_SECTIONS = ["实现追踪表", "变更记录"]
RESEARCH_REQUIRED_SECTIONS = ["改进建议", "实现追踪表", "变更记录"]


def find_project_root(start: Path = Path.cwd()) -> Path:
    """向上查找包含 AGENTS.md 的项目根目录。"""
    current = start
    while current != current.parent:
        if (current / "AGENTS.md").exists():
            return current
        current = current.parent
    return start


def check_directory_structure(docs_dir: Path) -> list[str]:
    errors = []
    for d in REQUIRED_DIRS:
        if not (docs_dir / d).is_dir():
            errors.append(f"缺少目录: docs/{d}/")
    for f in REQUIRED_FILES:
        if not (docs_dir / f).is_file():
            errors.append(f"缺少文件: docs/{f}")
    return errors


def check_document_sections(filepath: Path, required: list[str]) -> list[str]:
    errors = []
    try:
        content = filepath.read_text(encoding="utf-8")
        for section in required:
            if section not in content:
                errors.append(f"{filepath.name}: 缺少必须章节 '{section}'")
    except Exception as e:
        errors.append(f"{filepath.name}: 读取失败 — {e}")
    return errors


def check_mapping_coverage(root: Path, mapping_file: Path) -> list[str]:
    """检查 mapping.md 是否覆盖了主要代码模块。"""
    errors = []
    try:
        mapping_content = mapping_file.read_text(encoding="utf-8")
    except Exception:
        return ["mapping.md 读取失败"]

    code_dirs = []
    autoc_dir = root / "autoc"
    if autoc_dir.is_dir():
        for child in sorted(autoc_dir.iterdir()):
            if child.is_dir() and not child.name.startswith("_"):
                code_dirs.append(f"autoc/{child.name}")
        core_dir = autoc_dir / "core"
        if core_dir.is_dir():
            for child in sorted(core_dir.iterdir()):
                if child.is_dir() and not child.name.startswith("_"):
                    code_dirs.append(f"autoc/core/{child.name}")

    for code_dir in code_dirs:
        if code_dir not in mapping_content:
            errors.append(f"mapping.md 未覆盖代码模块: {code_dir}")

    return errors


def main():
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else find_project_root()
    docs_dir = root / "docs"

    if not docs_dir.is_dir():
        print("❌ docs/ 目录不存在")
        sys.exit(1)

    all_errors = []
    all_warnings = []

    # 1. 目录结构
    all_errors.extend(check_directory_structure(docs_dir))

    # 2. Design 文档必须章节
    design_dir = docs_dir / "design"
    if design_dir.is_dir():
        for md in sorted(design_dir.glob("*.md")):
            all_errors.extend(check_document_sections(md, DESIGN_REQUIRED_SECTIONS))

    # 3. Research 文档必须章节
    research_dir = docs_dir / "research"
    if research_dir.is_dir():
        for md in sorted(research_dir.glob("*.md")):
            errs = check_document_sections(md, RESEARCH_REQUIRED_SECTIONS)
            # research 缺失降级为 warning（部分老文档可能不完整）
            all_warnings.extend(errs)

    # 4. Mapping 覆盖率
    mapping_file = docs_dir / "mapping.md"
    if mapping_file.is_file():
        all_warnings.extend(check_mapping_coverage(root, mapping_file))

    # 5. AGENTS.md 存在
    if not (root / "AGENTS.md").is_file():
        all_errors.append("项目根目录缺少 AGENTS.md")

    # 输出
    print(f"\n📋 AutoC 文档校验报告 — {root}")
    print("=" * 60)

    if all_errors:
        print(f"\n❌ 错误 ({len(all_errors)})")
        for e in all_errors:
            print(f"  • {e}")

    if all_warnings:
        print(f"\n⚠️  警告 ({len(all_warnings)})")
        for w in all_warnings:
            print(f"  • {w}")

    if not all_errors and not all_warnings:
        print("\n✅ 全部通过！")

    total = len(all_errors) + len(all_warnings)
    print(f"\n汇总: {len(all_errors)} 错误, {len(all_warnings)} 警告")

    sys.exit(1 if all_errors else 0)


if __name__ == "__main__":
    main()
