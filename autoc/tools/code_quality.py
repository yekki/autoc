"""代码质量工具 - 参考 OpenHands/MetaGPT 的代码格式化和 Linting 集成

提供自动化代码质量保障:
- Python: black (格式化) + flake8 (linting)
- JavaScript/TypeScript: prettier (格式化) + eslint (linting)
- 通用: 检测可用工具并自动运行

设计理念:
- 参考 OpenHands 的 linter 集成
- 参考 MetaGPT 的代码规范检查
- 开发完成后自动运行，提升代码质量
"""

import logging
import os
import shutil
import subprocess
from typing import Optional

logger = logging.getLogger("autoc.tools.code_quality")


class CodeQualityTools:
    """代码格式化和静态检查工具"""

    def __init__(self, workspace_dir: str):
        self.workspace_dir = os.path.abspath(workspace_dir)
        self._tool_cache: dict[str, Optional[str]] = {}

    def _resolve_safe_path(self, path: str) -> str:
        """解析路径并确保不越出工作区，防止 Agent 传入 ../../ 等越界路径。

        Raises:
            ValueError: 路径越界时抛出，由调用方决定处理方式。
        """
        if path == ".":
            return self.workspace_dir
        if os.path.isabs(path):
            resolved = os.path.abspath(path)
        else:
            resolved = os.path.abspath(os.path.join(self.workspace_dir, path))
        # 用 +/ 后缀消除前缀碰撞（/ws/proj 不应匹配 /ws/project-evil）
        if not (resolved + "/").startswith(self.workspace_dir + "/"):
            raise ValueError(f"路径越界，拒绝访问: {path!r} → {resolved}")
        return resolved

    def _find_tool(self, name: str) -> Optional[str]:
        """查找工具路径，带缓存"""
        if name not in self._tool_cache:
            self._tool_cache[name] = shutil.which(name)
        return self._tool_cache[name]

    def _run_cmd(self, cmd: list[str], timeout: int = 60) -> tuple[int, str]:
        """执行命令"""
        try:
            result = subprocess.run(
                cmd,
                cwd=self.workspace_dir,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            output = result.stdout.strip()
            if result.stderr.strip():
                output += f"\n{result.stderr.strip()}" if output else result.stderr.strip()
            return result.returncode, output
        except subprocess.TimeoutExpired:
            return -1, "[超时]"
        except Exception as e:
            return -1, str(e)

    # ==================== Python 工具 ====================

    def format_python(self, path: str = ".") -> str:
        """
        用 black 格式化 Python 代码

        Args:
            path: 文件或目录路径（相对于工作区）

        Returns:
            格式化结果
        """
        if not self._find_tool("black"):
            # 尝试安装
            self._run_cmd(["pip", "install", "black", "-q"], timeout=30)
            self._tool_cache.pop("black", None)

        if not self._find_tool("black"):
            return "[跳过] black 未安装"

        try:
            target = self._resolve_safe_path(path)
        except ValueError as e:
            return f"[错误] {e}"
        code, output = self._run_cmd([
            "black", target,
            "--line-length", "120",
            "--quiet",
        ])

        if code == 0:
            logger.info(f"Python 代码已格式化: {path}")
            return f"✅ Python 代码格式化完成: {output or '无需修改'}"
        return f"⚠️ 格式化出现问题: {output}"

    def lint_python(self, path: str = ".") -> str:
        """
        用 flake8 检查 Python 代码

        Args:
            path: 文件或目录路径

        Returns:
            Linting 结果
        """
        if not self._find_tool("flake8"):
            self._run_cmd(["pip", "install", "flake8", "-q"], timeout=30)
            self._tool_cache.pop("flake8", None)

        if not self._find_tool("flake8"):
            return "[跳过] flake8 未安装"

        try:
            target = self._resolve_safe_path(path)
        except ValueError as e:
            return f"[错误] {e}"
        code, output = self._run_cmd([
            "flake8", target,
            "--max-line-length", "120",
            "--ignore", "E501,W503,E203,E402",
            "--count",
            "--statistics",
        ])

        if code == 0:
            return "✅ Python 代码检查通过，没有发现问题"
        return f"⚠️ 发现以下问题:\n{output}"

    # ==================== JavaScript/TypeScript 工具 ====================

    def format_js(self, path: str = ".") -> str:
        """用 prettier 格式化 JS/TS 代码"""
        npx = self._find_tool("npx")
        if not npx:
            return "[跳过] npx/Node.js 未安装"

        try:
            target = self._resolve_safe_path(path)
        except ValueError as e:
            return f"[错误] {e}"
        code, output = self._run_cmd([
            npx, "prettier", "--write",
            target,
            "--ignore-unknown",
        ], timeout=30)

        if code == 0:
            return f"✅ JS/TS 代码格式化完成"
        return f"⚠️ 格式化问题: {output}"

    def lint_js(self, path: str = ".") -> str:
        """用 eslint 检查 JS/TS 代码"""
        npx = self._find_tool("npx")
        if not npx:
            return "[跳过] npx/Node.js 未安装"

        try:
            target = self._resolve_safe_path(path)
        except ValueError as e:
            return f"[错误] {e}"
        code, output = self._run_cmd([
            npx, "eslint", target,
            "--ext", ".js,.ts,.jsx,.tsx",
            "--no-error-on-unmatched-pattern",
        ], timeout=30)

        if code == 0:
            return "✅ JS/TS 代码检查通过"
        return f"⚠️ 发现以下问题:\n{output}"

    # ==================== 综合方法 ====================

    def detect_languages(self) -> set[str]:
        """检测工作区中使用的编程语言"""
        langs = set()
        for root, _, files in os.walk(self.workspace_dir):
            # 跳过忽略目录（使用路径组件匹配，避免目录名包含关键词时误跳）
            root_parts = set(os.path.normpath(root).split(os.sep))
            if root_parts & {"node_modules", "__pycache__", ".git", "venv", ".venv"}:
                continue
            for f in files:
                if f.endswith((".py",)):
                    langs.add("python")
                elif f.endswith((".js", ".jsx", ".ts", ".tsx")):
                    langs.add("javascript")
                elif f.endswith((".html", ".css")):
                    langs.add("web")
                elif f.endswith((".go",)):
                    langs.add("go")
                elif f.endswith((".rs",)):
                    langs.add("rust")
        return langs

    def run_all(self) -> str:
        """运行所有适用的代码质量检查"""
        results = []
        langs = self.detect_languages()

        if "python" in langs:
            results.append("### Python")
            results.append(self.format_python())
            results.append(self.lint_python())

        if "javascript" in langs:
            results.append("### JavaScript/TypeScript")
            results.append(self.format_js())

        if not results:
            return "未检测到需要检查的代码文件"

        return "\n".join(results)


# 工具定义 (用于 Function Calling)
CODE_QUALITY_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "format_code",
            "description": "格式化代码文件（Python 使用 black，JS/TS 使用 prettier）",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "要格式化的文件或目录路径（相对于工作区），默认格式化整个工作区",
                        "default": ".",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lint_code",
            "description": "检查代码质量（Python 使用 flake8，JS/TS 使用 eslint）",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "要检查的文件或目录路径，默认检查整个工作区",
                        "default": ".",
                    },
                },
            },
        },
    },
]
