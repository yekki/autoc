"""WorkspaceRuntime — 工作区运行时统一接口

参考 OpenHands Workspace 抽象层设计，统一 Local/Docker/Remote 三种后端：

- **文件操作**：read / write / list / exists / delete
- **命令执行**：execute / execute_background
- **环境管理**：is_available / get_info / cleanup

设计原则：
1. Agent 通过 WorkspaceRuntime 操作文件和执行命令，不感知底层实现
2. Local 实现用于测试和无 Docker 环境
3. Docker 实现包装现有 DockerSandbox（文件 bind mount，命令在容器内）
4. Remote 实现预留 E2B/云沙箱接口（文件通过 API 传输）

使用：
    runtime = create_workspace_runtime("docker", workspace_dir, sandbox=sandbox)
    content = runtime.read_file("main.py")
    runtime.write_file("main.py", new_content)
    output = runtime.execute("python main.py")
"""

import logging
import os
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("autoc.runtime.workspace")


@dataclass
class RuntimeInfo:
    """运行时环境信息"""
    name: str
    workspace_dir: str
    available: bool
    details: dict


class WorkspaceRuntime(ABC):
    """工作区运行时统一接口"""

    def __init__(self, workspace_dir: str):
        self._workspace_dir = os.path.abspath(workspace_dir)

    @property
    def workspace_dir(self) -> str:
        return self._workspace_dir

    @property
    @abstractmethod
    def name(self) -> str:
        """运行时名称"""
        ...

    # ---- 文件操作 ----

    @abstractmethod
    def read_file(self, path: str) -> str:
        """读取文件内容（相对于 workspace root）"""
        ...

    @abstractmethod
    def write_file(self, path: str, content: str) -> None:
        """写入文件内容"""
        ...

    @abstractmethod
    def list_files(
        self, path: str = ".", recursive: bool = False, max_depth: int = 3,
    ) -> list[str]:
        """列出目录下的文件（返回相对路径）"""
        ...

    @abstractmethod
    def file_exists(self, path: str) -> bool:
        """文件是否存在"""
        ...

    @abstractmethod
    def delete_file(self, path: str) -> bool:
        """删除文件"""
        ...

    @abstractmethod
    def mkdir(self, path: str) -> None:
        """创建目录（含中间目录）"""
        ...

    # ---- 命令执行 ----

    @abstractmethod
    def execute(self, command: str, timeout: int = 60) -> str:
        """执行命令，阻塞直到完成，返回 stdout + stderr"""
        ...

    @abstractmethod
    def execute_background(self, command: str) -> str:
        """启动后台进程，返回标识符（PID 或 ID）"""
        ...

    # ---- 环境管理 ----

    @abstractmethod
    def is_available(self) -> bool:
        """运行时是否可用"""
        ...

    @abstractmethod
    def get_info(self) -> RuntimeInfo:
        """获取运行时环境信息"""
        ...

    @abstractmethod
    def cleanup(self) -> None:
        """清理资源"""
        ...

    # ---- 路径工具 ----

    def _resolve(self, path: str) -> str:
        """解析相对路径到绝对路径，安全检查（realpath 防 symlink 穿越）"""
        if os.path.isabs(path):
            resolved = os.path.realpath(path)
        else:
            resolved = os.path.realpath(os.path.join(self._workspace_dir, path))
        workspace_real = os.path.realpath(self._workspace_dir)
        if not resolved.startswith(workspace_real + os.sep) and resolved != workspace_real:
            raise ValueError(f"路径越界: {path} 不在工作区 {self._workspace_dir} 内")
        return resolved


class LocalWorkspaceRuntime(WorkspaceRuntime):
    """本地运行时 — 直接操作文件系统和本地进程

    用途：单元测试 / 无 Docker 开发环境
    """

    _SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".autoc"}

    def __init__(self, workspace_dir: str):
        super().__init__(workspace_dir)
        self._bg_procs: list = []

    @property
    def name(self) -> str:
        return "local"

    def read_file(self, path: str) -> str:
        resolved = self._resolve(path)
        with open(resolved, "r", encoding="utf-8") as f:
            return f.read()

    def write_file(self, path: str, content: str) -> None:
        resolved = self._resolve(path)
        os.makedirs(os.path.dirname(resolved), exist_ok=True)
        with open(resolved, "w", encoding="utf-8") as f:
            f.write(content)

    def list_files(
        self, path: str = ".", recursive: bool = False, max_depth: int = 3,
    ) -> list[str]:
        resolved = self._resolve(path)
        result: list[str] = []
        self._walk(Path(resolved), Path(self._workspace_dir), recursive, max_depth, 0, result)
        return sorted(result)

    def _walk(
        self, root: Path, base: Path, recursive: bool,
        max_depth: int, depth: int, out: list[str],
    ) -> None:
        if depth > max_depth:
            return
        try:
            for entry in root.iterdir():
                rel = str(entry.relative_to(base))
                if entry.name in self._SKIP_DIRS:
                    continue
                if entry.is_file():
                    out.append(rel)
                elif entry.is_dir() and recursive:
                    self._walk(entry, base, recursive, max_depth, depth + 1, out)
        except PermissionError:
            pass

    def file_exists(self, path: str) -> bool:
        return os.path.exists(self._resolve(path))

    def delete_file(self, path: str) -> bool:
        resolved = self._resolve(path)
        if os.path.exists(resolved):
            os.remove(resolved)
            return True
        return False

    def mkdir(self, path: str) -> None:
        os.makedirs(self._resolve(path), exist_ok=True)

    def execute(self, command: str, timeout: int = 60) -> str:
        try:
            result = subprocess.run(
                ["bash", "-c", command],
                capture_output=True, text=True,
                timeout=timeout, cwd=self._workspace_dir,
            )
            output = result.stdout
            if result.stderr:
                output += f"\n[stderr]\n{result.stderr}"
            return output
        except subprocess.TimeoutExpired:
            return f"[超时] 命令执行超过 {timeout}s: {command[:80]}"
        except Exception as e:
            return f"[错误] {e}"

    def execute_background(self, command: str) -> str:
        try:
            proc = subprocess.Popen(
                ["bash", "-c", command],
                cwd=self._workspace_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._bg_procs.append(proc)
            return str(proc.pid)
        except Exception as e:
            return f"[错误] {e}"

    def is_available(self) -> bool:
        return os.path.isdir(self._workspace_dir)

    def get_info(self) -> RuntimeInfo:
        return RuntimeInfo(
            name="local",
            workspace_dir=self._workspace_dir,
            available=self.is_available(),
            details={"type": "local_filesystem"},
        )

    def cleanup(self) -> None:
        for proc in self._bg_procs:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self._bg_procs.clear()


class DockerWorkspaceRuntime(WorkspaceRuntime):
    """Docker 运行时 — 文件通过 bind mount 本地操作，命令在容器内执行

    文件操作走本地 FS（workspace bind mount 到 /workspace），
    命令执行走 DockerSandbox.execute()。
    """

    def __init__(self, workspace_dir: str, sandbox):
        super().__init__(workspace_dir)
        self._sandbox = sandbox
        self._local = LocalWorkspaceRuntime(workspace_dir)

    @property
    def name(self) -> str:
        return "docker"

    # 文件操作代理给 LocalWorkspaceRuntime（bind mount 共享文件系统）
    def read_file(self, path: str) -> str:
        return self._local.read_file(path)

    def write_file(self, path: str, content: str) -> None:
        self._local.write_file(path, content)

    def list_files(
        self, path: str = ".", recursive: bool = False, max_depth: int = 3,
    ) -> list[str]:
        return self._local.list_files(path, recursive, max_depth)

    def file_exists(self, path: str) -> bool:
        return self._local.file_exists(path)

    def delete_file(self, path: str) -> bool:
        return self._local.delete_file(path)

    def mkdir(self, path: str) -> None:
        self._local.mkdir(path)

    # 命令执行走 Docker
    def execute(self, command: str, timeout: int = 60) -> str:
        return self._sandbox.execute(command, timeout=timeout)

    def execute_background(self, command: str) -> str:
        return self._sandbox.execute_background(command)

    def is_available(self) -> bool:
        return bool(self._sandbox and self._sandbox.is_available)

    def get_info(self) -> RuntimeInfo:
        return RuntimeInfo(
            name="docker",
            workspace_dir=self._workspace_dir,
            available=self.is_available(),
            details={
                "type": "docker_sandbox",
                "container": getattr(self._sandbox, "_container_id", None),
                "image": getattr(self._sandbox, "image", None),
            },
        )

    def cleanup(self) -> None:
        if self._sandbox:
            self._sandbox.stop_background_processes()


class RemoteWorkspaceRuntime(WorkspaceRuntime):
    """远程运行时 — 所有操作通过网络 API（预留 E2B / 云沙箱）

    设计为可扩展的远程工作区接口：
    - 文件操作通过 API 传输（不依赖 bind mount）
    - 命令执行通过 API 调用
    - 具体 SDK 适配在子类中实现
    """

    def __init__(self, workspace_dir: str, api_endpoint: str = "", api_key: str = ""):
        super().__init__(workspace_dir)
        self._api_endpoint = api_endpoint
        self._api_key = api_key
        self._connected = False

    @property
    def name(self) -> str:
        return "remote"

    def read_file(self, path: str) -> str:
        self._ensure_connected()
        raise NotImplementedError("RemoteWorkspaceRuntime.read_file 需由子类实现")

    def write_file(self, path: str, content: str) -> None:
        self._ensure_connected()
        raise NotImplementedError("RemoteWorkspaceRuntime.write_file 需由子类实现")

    def list_files(
        self, path: str = ".", recursive: bool = False, max_depth: int = 3,
    ) -> list[str]:
        self._ensure_connected()
        raise NotImplementedError("RemoteWorkspaceRuntime.list_files 需由子类实现")

    def file_exists(self, path: str) -> bool:
        self._ensure_connected()
        raise NotImplementedError("RemoteWorkspaceRuntime.file_exists 需由子类实现")

    def delete_file(self, path: str) -> bool:
        self._ensure_connected()
        raise NotImplementedError("RemoteWorkspaceRuntime.delete_file 需由子类实现")

    def mkdir(self, path: str) -> None:
        self._ensure_connected()
        raise NotImplementedError("RemoteWorkspaceRuntime.mkdir 需由子类实现")

    def execute(self, command: str, timeout: int = 60) -> str:
        self._ensure_connected()
        raise NotImplementedError("RemoteWorkspaceRuntime.execute 需由子类实现")

    def execute_background(self, command: str) -> str:
        self._ensure_connected()
        raise NotImplementedError("RemoteWorkspaceRuntime.execute_background 需由子类实现")

    def is_available(self) -> bool:
        return bool(self._api_endpoint)

    def get_info(self) -> RuntimeInfo:
        return RuntimeInfo(
            name="remote",
            workspace_dir=self._workspace_dir,
            available=self.is_available(),
            details={
                "type": "remote",
                "endpoint": self._api_endpoint,
                "connected": self._connected,
            },
        )

    def cleanup(self) -> None:
        self._connected = False

    def _ensure_connected(self) -> None:
        if not self._api_endpoint:
            raise RuntimeError("远程运行时未配置 API endpoint")


def create_workspace_runtime(
    runtime_type: str,
    workspace_dir: str,
    sandbox=None,
    config: dict | None = None,
) -> WorkspaceRuntime:
    """工厂函数 — 根据类型创建 WorkspaceRuntime

    Args:
        runtime_type: "local" / "docker" / "remote"
        workspace_dir: 工作区路径
        sandbox: DockerSandbox 实例（docker 类型必需）
        config: 额外配置（remote 类型需要 api_endpoint/api_key）

    Returns:
        WorkspaceRuntime 实例

    Raises:
        ValueError: 未知类型
        RuntimeError: 创建失败
    """
    config = config or {}

    if runtime_type == "local":
        return LocalWorkspaceRuntime(workspace_dir)

    if runtime_type == "docker":
        if not sandbox:
            raise RuntimeError("Docker 运行时需要提供 DockerSandbox 实例")
        return DockerWorkspaceRuntime(workspace_dir, sandbox)

    if runtime_type == "remote":
        return RemoteWorkspaceRuntime(
            workspace_dir,
            api_endpoint=config.get("api_endpoint", ""),
            api_key=config.get("api_key", ""),
        )

    raise ValueError(f"未知运行时类型: {runtime_type}，支持 local/docker/remote")
