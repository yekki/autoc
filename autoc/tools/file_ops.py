"""文件操作工具 - 提供文件读写、创建目录等功能"""

import os
import logging
import tempfile
from pathlib import Path

from autoc.exceptions import FileToolError

logger = logging.getLogger("autoc.tools.file_ops")

# 单文件读取上限（16 MB），防止意外读入超大二进制或日志文件耗尽内存
_READ_SIZE_LIMIT = 16 * 1024 * 1024
# 单文件写入上限（10 MB），防止意外写入超大内容
_WRITE_SIZE_LIMIT = 10 * 1024 * 1024


def _real_path(path: str) -> str:
    """解析真实路径：对已存在的路径调用 realpath 解析 symlink；
    对不存在的路径递归解析最近已存在的祖先目录，再拼接剩余部分。
    """
    if os.path.lexists(path):
        return os.path.realpath(path)
    parent = os.path.dirname(path)
    if not parent or parent == path:
        return path
    return os.path.join(_real_path(parent), os.path.basename(path))


class FileOps:
    """文件操作工具类"""

    # AutoC 内部文件，对 Agent 不可见，避免浪费 token
    _AUTOC_INTERNAL_FILES = {
        ".autoc.db", ".autoc.db-shm", ".autoc.db-wal",
        "autoc-progress.txt", "autoc-tasks.json", "project-plan.json",
    }
    # 临时/备份文件后缀，对 Agent 不可见
    _HIDDEN_SUFFIXES = (".backup", ".bak", ".tmp", ".swp")

    def __init__(self, workspace_dir: str):
        # 使用 realpath 解析 workspace 本身的 symlink，保证后续前缀检查正确
        self.workspace_dir = os.path.realpath(os.path.abspath(workspace_dir))
        os.makedirs(self.workspace_dir, exist_ok=True)

    def _is_hidden_from_agent(self, filename: str) -> bool:
        """判断文件是否应对 Agent 隐藏（AutoC 内部文件 / 临时备份）"""
        if filename in self._AUTOC_INTERNAL_FILES:
            return True
        return any(filename.endswith(s) for s in self._HIDDEN_SUFFIXES)

    def _resolve_path(self, path: str) -> str:
        """解析路径，确保在工作区内（解析 symlink 防止路径穿越）"""
        if os.path.isabs(path):
            candidate = path
        else:
            candidate = os.path.join(self.workspace_dir, path)
        candidate = os.path.normpath(candidate)
        # 解析 symlink：对已存在路径完整 realpath；对不存在路径解析最近已有祖先
        resolved = _real_path(candidate)
        # 安全检查：确保在工作区内（用 +/ 消除前缀碰撞，如 /ws/proj 不应匹配 /ws/project-evil）
        ws = self.workspace_dir.rstrip("/") + "/"
        if not (resolved + "/").startswith(ws):
            raise ValueError(f"路径 {path} 不在工作区 {self.workspace_dir} 内")
        return resolved

    def read_file(self, path: str, start_line: int | None = None,
                   end_line: int | None = None) -> str:
        """读取文件内容。支持可选的行号范围（1-based，闭区间）。"""
        resolved = self._resolve_path(path)
        try:
            file_size = os.path.getsize(resolved)
            if file_size > _READ_SIZE_LIMIT:
                raise FileToolError(
                    f"文件过大（{file_size // 1024} KB），超过单次读取上限 "
                    f"({_READ_SIZE_LIMIT // 1024 // 1024} MB）。请使用行号范围参数分段读取。"
                )
            with open(resolved, "r", encoding="utf-8") as f:
                if start_line is not None or end_line is not None:
                    lines = f.readlines()
                    total = len(lines)
                    s = max(1, start_line or 1) - 1
                    e = min(total, end_line or total)
                    selected = lines[s:e]
                    numbered = [f"{s + i + 1:4d}| {line}" for i, line in enumerate(selected)]
                    header = f"[{path} 行 {s + 1}-{e} / 共 {total} 行]\n"
                    content = header + "".join(numbered)
                else:
                    content = f.read()
            logger.debug(f"读取文件: {path} ({len(content)} 字符)")
            return content
        except FileNotFoundError:
            raise FileToolError(f"文件不存在: {path}")
        except FileToolError:
            raise
        except Exception as e:
            raise FileToolError(f"读取文件失败: {e}") from e

    def write_file(self, path: str, content: str) -> str:
        """写入文件内容（覆盖，原子写入），失败时抛出 FileToolError"""
        resolved = self._resolve_path(path)
        if len(content.encode("utf-8")) > _WRITE_SIZE_LIMIT:
            raise FileToolError(
                f"写入内容过大（{len(content) // 1024} KB），超过 {_WRITE_SIZE_LIMIT // (1024 * 1024)} MB 限制"
            )
        try:
            dir_path = os.path.dirname(resolved)
            os.makedirs(dir_path, exist_ok=True)
            # 原子写入：先写临时文件，再 os.replace() 防止写入中断导致文件损坏
            fd, tmp_path = tempfile.mkstemp(dir=dir_path, prefix=".autoc_write_")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(content)
                os.replace(tmp_path, resolved)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
            logger.info(f"写入文件: {path} ({len(content)} 字符)")
            return f"文件已写入: {path}"
        except FileToolError:
            raise
        except Exception as e:
            raise FileToolError(f"写入文件失败: {e}") from e

    def edit_file(self, path: str, old_str: str, new_str: str) -> str:
        """精确编辑：在文件中查找 old_str 并替换为 new_str（仅替换首次匹配）。

        相比 write_file 全量覆盖，大幅节省 Token（只需传变更片段）。
        old_str 必须在文件中唯一出现，否则报错要求提供更精确的上下文。
        """
        resolved = self._resolve_path(path)
        try:
            file_size = os.path.getsize(resolved)
            if file_size > _READ_SIZE_LIMIT:
                raise FileToolError(
                    f"文件过大（{file_size // (1024*1024)} MB），超过 {_READ_SIZE_LIMIT // (1024*1024)} MB 限制，请使用分段写入"
                )
            with open(resolved, "r", encoding="utf-8") as f:
                content = f.read()
        except FileNotFoundError:
            raise FileToolError(f"文件不存在: {path}")

        if old_str == new_str:
            return f"[跳过] old_str 与 new_str 相同，无需修改"

        count = content.count(old_str)
        if count == 0:
            raise FileToolError(
                f"未找到要替换的内容（在 {path} 中）。请检查 old_str 是否与文件内容完全一致（包括空格和缩进）。"
            )
        if count > 1:
            raise FileToolError(
                f"在 {path} 中找到 {count} 处匹配，请提供更多上下文使 old_str 唯一。"
            )

        new_content = content.replace(old_str, new_str, 1)
        new_content_bytes = new_content.encode("utf-8")
        if len(new_content_bytes) > _WRITE_SIZE_LIMIT:
            raise FileToolError(
                f"编辑后文件大小（{len(new_content_bytes) // 1024} KB）"
                f"超过 {_WRITE_SIZE_LIMIT // (1024 * 1024)} MB 限制"
            )
        dir_path = os.path.dirname(resolved)
        fd, tmp_path = tempfile.mkstemp(dir=dir_path, prefix=".autoc_edit_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(new_content)
            os.replace(tmp_path, resolved)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise FileToolError(f"精确编辑写入失败: {path}")
        logger.info(f"精确编辑: {path} (替换 {len(old_str)}→{len(new_str)} 字符)")
        return f"文件已编辑: {path}"

    def append_file(self, path: str, content: str) -> str:
        """追加写入文件，失败时抛出 FileToolError"""
        content_bytes = content.encode("utf-8")
        content_bytes_len = len(content_bytes)
        if content_bytes_len > _WRITE_SIZE_LIMIT:
            raise FileToolError(
                f"追加内容过大（{content_bytes_len // 1024} KB），超过 {_WRITE_SIZE_LIMIT // (1024*1024)} MB 限制"
            )
        resolved = self._resolve_path(path)
        # 检查追加后的总大小是否超限
        existing_size = os.path.getsize(resolved) if os.path.exists(resolved) else 0
        if existing_size + content_bytes_len > _WRITE_SIZE_LIMIT:
            raise FileToolError(
                f"追加后文件总大小（{(existing_size + content_bytes_len) // 1024} KB）超过 "
                f"{_WRITE_SIZE_LIMIT // (1024*1024)} MB 限制"
            )
        try:
            dir_path = os.path.dirname(resolved)
            os.makedirs(dir_path, exist_ok=True)
            # 原子写入：读取现有内容 → 拼接 → 写临时文件 → os.replace()
            if os.path.exists(resolved):
                with open(resolved, "r", encoding="utf-8") as f:
                    existing = f.read()
            else:
                existing = ""
            new_content = existing + content
            fd, tmp_path = tempfile.mkstemp(dir=dir_path, prefix=".autoc_append_")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(new_content)
                os.replace(tmp_path, resolved)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
            logger.info(f"追加文件: {path}")
            return f"内容已追加到: {path}"
        except FileToolError:
            raise
        except Exception as e:
            raise FileToolError(f"追加文件失败: {e}") from e

    def create_directory(self, path: str) -> str:
        """创建目录，失败时抛出 FileToolError"""
        resolved = self._resolve_path(path)
        try:
            os.makedirs(resolved, exist_ok=True)
            logger.info(f"创建目录: {path}")
            return f"目录已创建: {path}"
        except Exception as e:
            raise FileToolError(f"创建目录失败: {e}") from e

    def list_files(self, path: str = ".", recursive: bool = False) -> str:
        """列出目录内容，失败时抛出 FileToolError"""
        resolved = self._resolve_path(path)
        try:
            if not os.path.isdir(resolved):
                raise FileToolError(f"不是目录: {path}")

            items = []
            if recursive:
                for root, dirs, files in os.walk(resolved):
                    dirs[:] = [
                        d for d in dirs
                        if not d.startswith(".") and d not in ("node_modules", "__pycache__", ".git", "venv")
                    ]
                    rel_root = os.path.relpath(root, resolved)
                    for f in sorted(files):
                        if f.startswith(".") or self._is_hidden_from_agent(f):
                            continue
                        if rel_root == ".":
                            items.append(f)
                        else:
                            items.append(os.path.join(rel_root, f))
            else:
                for item in sorted(os.listdir(resolved)):
                    if item.startswith(".") or self._is_hidden_from_agent(item):
                        continue
                    full = os.path.join(resolved, item)
                    suffix = "/" if os.path.isdir(full) else ""
                    items.append(f"{item}{suffix}")

            return "\n".join(items) if items else "(空目录)"
        except FileToolError:
            raise
        except Exception as e:
            raise FileToolError(f"列出目录失败: {e}") from e

    def file_exists(self, path: str) -> bool:
        """检查文件是否存在"""
        resolved = self._resolve_path(path)
        return os.path.exists(resolved)

    def delete_file(self, path: str) -> str:
        """删除文件，失败时抛出 FileToolError"""
        resolved = self._resolve_path(path)
        try:
            if not os.path.isfile(resolved):
                raise FileToolError(f"文件不存在: {path}")
            os.remove(resolved)
            logger.info(f"删除文件: {path}")
            return f"文件已删除: {path}"
        except FileToolError:
            raise
        except Exception as e:
            raise FileToolError(f"删除文件失败: {e}") from e

    def glob_files(self, pattern: str) -> str:
        """按 glob 模式匹配文件路径（支持 ** 递归匹配）

        示例:
            glob_files("**/*.py")         → 所有 Python 文件
            glob_files("src/**/*.ts")     → src 下所有 TypeScript 文件
            glob_files("*.md")            → 根目录的 Markdown 文件
        """
        from pathlib import Path

        base = Path(self.workspace_dir)
        skip_dirs = {".git", "node_modules", "__pycache__", "venv", ".venv", ".autoc"}
        ws_prefix = self.workspace_dir.rstrip(os.sep) + os.sep
        matches = []
        for p in base.glob(pattern):
            if any(part in skip_dirs for part in p.parts):
                continue
            # symlink 安全检查：防止 symlink 指向工作区外部
            real = os.path.realpath(p)
            if not (real + os.sep).startswith(ws_prefix) and real != self.workspace_dir:
                continue
            if p.is_file() and not self._is_hidden_from_agent(p.name):
                matches.append(str(p.relative_to(base)))
        matches.sort()
        if not matches:
            return f"未找到匹配 '{pattern}' 的文件"
        if len(matches) > 200:
            return "\n".join(matches[:200]) + f"\n... 共 {len(matches)} 个文件（仅显示前 200 个）"
        return "\n".join(matches)

    def search_in_files(self, keyword: str, file_pattern: str = "*.py") -> str:
        """在文件中搜索关键词"""
        results = []
        skip_dirs = {".git", "node_modules", "__pycache__", "venv", ".venv", ".autoc"}
        pattern = Path(self.workspace_dir).rglob(file_pattern)
        ws_prefix = self.workspace_dir.rstrip(os.sep) + os.sep
        for file_path in pattern:
            # 跳过常见的大型/无关目录（与 glob_files 一致）
            if any(part in skip_dirs for part in file_path.parts):
                continue
            # symlink 安全检查：防止 symlink 指向工作区外部
            real = os.path.realpath(file_path)
            if not (real + os.sep).startswith(ws_prefix) and real != self.workspace_dir:
                continue
            if self._is_hidden_from_agent(file_path.name):
                continue
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    for i, line in enumerate(f, 1):
                        if keyword in line:
                            rel_path = os.path.relpath(file_path, self.workspace_dir)
                            results.append(f"{rel_path}:{i}: {line.rstrip()}")
            except (UnicodeDecodeError, PermissionError):
                continue

        if results:
            return "\n".join(results[:50])
        return f"未找到包含 '{keyword}' 的内容"
