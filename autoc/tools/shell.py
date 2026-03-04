"""Shell 工具 - 执行系统命令（强制 Docker 沙箱模式）

安全策略：不依赖字符串黑名单（容易被空白符变体绕过），
交由 SecurityAnalyzer 的正则模式做纵深防御。
"""

import logging
import re
import os

from autoc.exceptions import SandboxError

logger = logging.getLogger("autoc.tools.shell")

# 默认超时: 120s 总时间上限（Agent 可通过 timeout 参数覆盖）
DEFAULT_TIMEOUT = 120

# 输出限制：从 4000→16000 字符，避免截断编译错误等关键信息
OUTPUT_MAX_CHARS = 16000
OUTPUT_MAX_LINES = 200


def _compress_pip_output(output: str) -> str:
    """pip install 输出：智能提取摘要行（成功/已满足/失败）"""
    lines = [l for l in output.strip().splitlines() if l.strip()]
    if not lines:
        return output

    # 优先查找 "Successfully installed ..." — 最明确的成功信号
    for line in reversed(lines):
        if "Successfully installed" in line:
            return line

    # 过滤干扰行（WARNING / NOTICE / Downloading / Using cached 等非状态行）
    # 只保留真正的包状态行，避免 WARNING 误计入"行数"
    _NOISE_PREFIXES = ("WARNING", "NOTICE", "  Downloading", "  Using cached",
                       "Collecting", "  Obtaining", "Building")
    content_lines = [l for l in lines if not any(l.startswith(p) for p in _NOISE_PREFIXES)]

    satisfied = [l for l in content_lines if "Requirement already satisfied" in l or "already up-to-date" in l]
    if satisfied and len(satisfied) == len(content_lines):
        return f"所有依赖已满足（{len(satisfied)} 个包）"
    if satisfied:
        return f"部分依赖已满足（{len(satisfied)}/{len(content_lines)} 包），最后: {content_lines[-1]}"

    # 失败或其他情况：保留最后 5 个内容行（含错误摘要）
    return '\n'.join(content_lines[-5:] if content_lines else lines[-5:])


def _compress_shell_output(
    output: str,
    command: str = "",
    max_lines: int = OUTPUT_MAX_LINES,
    max_chars: int = OUTPUT_MAX_CHARS,
) -> str:
    """智能压缩 Shell 输出 — 命令类型感知 + 保留首尾关键信息"""
    # 命令类型感知压缩
    if re.search(r'pip[3]?\s+install\b', command):
        return _compress_pip_output(output)

    if re.search(r'python[3]?\s+-m\s+py_compile\b', command):
        stripped = output.strip()
        if not stripped:
            return "✓ 编译通过"
        # 编译错误通常很短，但批量编译（*.py）可能很长，仍需安全截断
        return stripped[:max_chars] if len(stripped) > max_chars else stripped

    if len(output) <= max_chars and output.count('\n') <= max_lines:
        return output
    lines = output.split('\n')
    if len(lines) <= max_lines:
        return output[:max_chars] + f"\n... [输出截断，原始 {len(output)} 字符]"
    keep = max(20, max_lines // 4)
    head = lines[:keep]
    tail = lines[-keep:]
    omitted = len(lines) - 2 * keep
    return '\n'.join(head) + f"\n\n... [{omitted} 行已省略] ...\n\n" + '\n'.join(tail)


class ShellExecutor:
    """安全的 Shell 命令执行器

    所有命令强制通过 DockerSandbox 在容器内执行，不支持本地模式。
    sandbox 属性由 Orchestrator 在初始化时注入。
    """

    def __init__(self, workspace_dir: str, timeout: int = DEFAULT_TIMEOUT, venv_manager=None):
        self.workspace_dir = os.path.abspath(workspace_dir)
        self.timeout = timeout
        self.venv_manager = venv_manager
        self.sandbox = None  # 由 Orchestrator 注入，执行前必须就绪

    @property
    def missing_tools(self) -> list[str]:
        """返回沙箱中安装失败的基础工具列表"""
        if self.sandbox:
            return self.sandbox.missing_tools
        return []

    @staticmethod
    def _fix_pip_install(command: str) -> str:
        """修复 pip install 命令中未加引号的版本指定符，避免 Shell 重定向。"""
        if not re.search(r'pip[3]?\s+install\b', command):
            return command
        pkg_pattern = r'(?<!["\'])(\b[A-Za-z0-9_][A-Za-z0-9_.~-]*(?:[><=!~]+[A-Za-z0-9_.*]+)+)(?!["\'])'
        return re.sub(pkg_pattern, r'"\1"', command)

    def execute(self, command: str, timeout: int | None = None) -> str:
        """在 Docker 沙箱内执行命令。

        安全策略由 SecurityAnalyzer 在 ToolRegistry.dispatch() 层统一拦截，
        此处不做字符串黑名单检查（容易被绕过，给人虚假安全感）。
        """
        command = self._fix_pip_install(command)
        timeout = timeout if timeout is not None else self.timeout

        if not self.sandbox or not self.sandbox.is_available:
            raise SandboxError(
                "Docker 沙箱不可用。所有命令必须在沙箱内执行，不支持本地模式。"
                "请确保 Docker 已安装并正在运行。"
            )

        logger.info(f"[沙箱] 执行命令: {command}")
        raw_output = self.sandbox.execute(command, timeout=timeout)
        return _compress_shell_output(raw_output, command=command)

    def send_input(self, text: str) -> str:
        """向容器内运行中的进程发送输入（交互式进程支持）

        依赖 Action Server 的持久 bash 通道。
        未启用 Action Server 时返回错误提示。
        """
        if not self.sandbox:
            return "[错误] 沙箱未就绪"
        client = getattr(self.sandbox, "action_client", None)
        if not client:
            return "[不支持] 交互式输入需要 Action Server（容器内持久 bash 通道）"
        ok = client.send_input(text)
        return "[OK] 输入已发送" if ok else "[错误] 输入发送失败"

    @property
    def supports_interactive(self) -> bool:
        """是否支持交互式输入（取决于 Action Server 是否就绪）"""
        if not self.sandbox:
            return False
        client = getattr(self.sandbox, "action_client", None)
        return client is not None
