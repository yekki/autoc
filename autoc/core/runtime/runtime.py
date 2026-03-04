"""Runtime 抽象层 — 统一 Docker / E2B 两种执行环境

为 PreviewManager 提供统一的运行时接口。
不支持本地模式——所有命令必须在容器内执行。

用法:
    runtime = create_runtime(config, sandbox=sandbox)
    runtime.execute("npm install")
    pid = runtime.execute_background("npm run dev", port=3000)
    url = runtime.get_preview_url(3000)
"""

import logging
import os
import subprocess
import socket
import time
from abc import ABC, abstractmethod

from autoc.exceptions import SandboxError

logger = logging.getLogger("autoc.runtime")


class RuntimeBase(ABC):
    """运行时抽象基类"""

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def execute(self, command: str, timeout: int = 60) -> str:
        """执行命令，阻塞直到完成"""
        ...

    @abstractmethod
    def execute_background(self, command: str, port: int = 0) -> str:
        """启动后台进程（dev server），返回 PID"""
        ...

    @abstractmethod
    def install_deps(self, workspace_dir: str) -> str:
        """安装项目依赖"""
        ...

    @abstractmethod
    def get_preview_url(self, port: int) -> str:
        """获取预览 URL"""
        ...

    @abstractmethod
    def check_port_ready(self, port: int, retries: int = 15) -> bool:
        """检测端口是否就绪"""
        ...

    @abstractmethod
    def cleanup(self):
        """清理资源"""
        ...


class DockerRuntime(RuntimeBase):
    """Docker 运行时 — 包装 DockerSandbox"""

    def __init__(self, sandbox):
        self._sandbox = sandbox

    @property
    def name(self) -> str:
        return "docker"

    def execute(self, command: str, timeout: int = 60) -> str:
        return self._sandbox.execute(command, timeout=timeout)

    def execute_background(self, command: str, port: int = 0) -> str:
        return self._sandbox.execute_background(command)

    def install_deps(self, workspace_dir: str) -> str:
        output_parts = []
        pkg_json = os.path.join(workspace_dir, "package.json")
        if os.path.isfile(pkg_json):
            output_parts.append(self._sandbox.execute("npm install 2>&1", timeout=120))
        req_txt = os.path.join(workspace_dir, "requirements.txt")
        if os.path.isfile(req_txt):
            output_parts.append(self._sandbox.install_requirements())
        return "\n".join(output_parts) if output_parts else "(无需安装依赖)"

    def get_preview_url(self, port: int) -> str:
        for host_port, container_port in self._sandbox.port_mappings:
            if container_port == port:
                return f"http://localhost:{host_port}"
        return f"http://localhost:{port}"

    def check_port_ready(self, port: int, retries: int = 15) -> bool:
        return self._sandbox.check_port_ready(port, retries=retries)

    def cleanup(self):
        self._sandbox.stop_background_processes()


class E2BRuntime(RuntimeBase):
    """E2B 云沙箱运行时

    需要安装 e2b 包: pip install e2b
    需要 E2B_API_KEY 环境变量。
    """

    def __init__(self, workspace_dir: str, template: str = "", api_key: str = ""):
        self.workspace_dir = os.path.abspath(workspace_dir)
        self._template = template
        self._api_key = api_key or os.environ.get("E2B_API_KEY", "")
        self._sandbox = None
        self._setup()

    def _setup(self):
        try:
            from e2b import Sandbox
            kwargs = {}
            if self._template:
                kwargs["template"] = self._template
            if self._api_key:
                os.environ["E2B_API_KEY"] = self._api_key
            self._sandbox = Sandbox.create(**kwargs)
            self._upload_workspace()
            logger.info(f"E2B 沙箱已创建: {self._sandbox.sandbox_id}")
        except ImportError:
            raise RuntimeError(
                "E2B SDK 未安装。请运行: pip install e2b\n"
                "并设置环境变量 E2B_API_KEY"
            )
        except Exception as e:
            raise RuntimeError(f"E2B 沙箱创建失败: {e}")

    def _upload_workspace(self):
        """将本地工作区文件上传到 E2B 沙箱"""
        for root, dirs, files in os.walk(self.workspace_dir):
            dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__", ".venv", "venv")]
            for f in files:
                local_path = os.path.join(root, f)
                relative = os.path.relpath(local_path, self.workspace_dir)
                remote_path = f"/home/user/workspace/{relative}"
                try:
                    with open(local_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    self._sandbox.files.write(remote_path, content)
                except (UnicodeDecodeError, OSError):
                    pass

    @property
    def name(self) -> str:
        return "e2b"

    def execute(self, command: str, timeout: int = 60) -> str:
        if not self._sandbox:
            return "[错误] E2B 沙箱未初始化"
        try:
            result = self._sandbox.commands.run(
                command, cwd="/home/user/workspace", timeout=timeout,
            )
            return result.stdout + (f"\n[stderr]\n{result.stderr}" if result.stderr else "")
        except Exception as e:
            return f"[错误] {e}"

    def execute_background(self, command: str, port: int = 0) -> str:
        if not self._sandbox:
            return "[错误] E2B 沙箱未初始化"
        try:
            self._sandbox.commands.run(
                f"nohup bash -c '{command}' > /tmp/server.log 2>&1 &",
                cwd="/home/user/workspace", timeout=10,
            )
            time.sleep(2)
            return "bg"
        except Exception as e:
            return f"[错误] {e}"

    def install_deps(self, workspace_dir: str) -> str:
        output_parts = []
        pkg_json = os.path.join(workspace_dir, "package.json")
        if os.path.isfile(pkg_json):
            output_parts.append(self.execute("npm install", timeout=120))
        req_txt = os.path.join(workspace_dir, "requirements.txt")
        if os.path.isfile(req_txt):
            output_parts.append(self.execute("pip install -r requirements.txt", timeout=120))
        return "\n".join(output_parts) if output_parts else "(无需安装依赖)"

    def get_preview_url(self, port: int) -> str:
        if not self._sandbox:
            return ""
        try:
            return self._sandbox.get_host(port)
        except Exception:
            return f"https://{self._sandbox.sandbox_id}-{port}.e2b.dev"

    def check_port_ready(self, port: int, retries: int = 20) -> bool:
        for _ in range(retries):
            try:
                result = self._sandbox.commands.run(
                    f"bash -c 'echo > /dev/tcp/127.0.0.1/{port}' 2>/dev/null",
                    timeout=3,
                )
                if result.exit_code == 0:
                    return True
            except Exception:
                pass
            time.sleep(1)
        return False

    def cleanup(self):
        if self._sandbox:
            try:
                self._sandbox.kill()
            except Exception:
                pass
            self._sandbox = None


def create_runtime(
    workspace_dir: str,
    config: dict | None = None,
    sandbox=None,
) -> RuntimeBase:
    """根据配置创建 Runtime（Docker 或 E2B，不支持本地模式）。

    Args:
        workspace_dir: 工作区路径
        config: 完整配置字典
        sandbox: DockerSandbox 实例

    Returns:
        RuntimeBase 子类实例

    Raises:
        SandboxError: Docker 沙箱不可用时
    """
    config = config or {}
    preview_cfg = config.get("preview", {})
    runtime_type = preview_cfg.get("runtime", "auto")

    if runtime_type == "e2b":
        api_key = preview_cfg.get("e2b_api_key", "") or os.environ.get("E2B_API_KEY", "")
        template = preview_cfg.get("e2b_template", "")
        if api_key:
            try:
                return E2BRuntime(workspace_dir, template=template, api_key=api_key)
            except Exception as e:
                logger.warning(f"E2B Runtime 创建失败: {e}")

    if sandbox and sandbox.is_available:
        return DockerRuntime(sandbox)

    raise SandboxError(
        "Docker 沙箱不可用，无法创建 Runtime。"
        "请确保 Docker 已安装并正在运行。"
    )
