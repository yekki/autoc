"""Action Execution Client — 与容器内 Action Server 通信

宿主侧客户端，通过 HTTP 与容器内的 PersistentBash 交互。
取代 `docker exec` 的无状态模式：
- cd / export 等环境状态自动保持
- 不再需要 VenvManager 补丁
- 支持交互式输入（send_input）
"""

import json
import logging
import time
import urllib.request
import urllib.error

logger = logging.getLogger("autoc.runtime.action_client")


class ActionClient:
    """与容器内 Action Server 通信的 HTTP 客户端"""

    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        if port <= 0:
            raise ValueError(f"ActionClient 需要有效端口号, 收到 port={port}")
        self._base_url = f"http://{host}:{port}"
        self._ready = False
        self._last_cwd = "/workspace"

    @property
    def base_url(self) -> str:
        return self._base_url

    def is_alive(self) -> bool:
        """检查 Action Server 是否在线（不会阻塞 execute 锁）"""
        try:
            resp = self._get("/alive", timeout=3)
            return resp.get("status") == "running"
        except Exception:
            return False

    def wait_until_ready(self, max_wait: int = 30, interval: float = 0.5) -> bool:
        """等待 Action Server 启动就绪"""
        start = time.monotonic()
        while time.monotonic() - start < max_wait:
            if self.is_alive():
                self._ready = True
                logger.info("Action Server 已就绪")
                return True
            time.sleep(interval)
        logger.warning(f"Action Server 在 {max_wait}s 内未就绪")
        return False

    def execute(self, command: str, timeout: int = 120) -> tuple[int, str]:
        """执行命令，返回 (exit_code, output)

        内部缓存 cwd（由 /execute 响应携带），避免额外 HTTP 往返。
        """
        resp = self._post("/execute", {
            "command": command,
            "timeout": timeout,
        }, timeout=timeout + 10)
        cwd = resp.get("cwd")
        if cwd:
            self._last_cwd = cwd
        return resp.get("exit_code", -1), resp.get("output", "")

    def send_input(self, text: str) -> bool:
        """向运行中的进程发送输入（交互式进程支持）"""
        resp = self._post("/input", {"text": text}, timeout=5)
        return resp.get("ok", False)

    def reset(self) -> bool:
        """重启 bash session"""
        resp = self._post("/reset", {}, timeout=10)
        return resp.get("ok", False)

    def get_cwd(self) -> str:
        """获取当前工作目录（使用缓存，不发 HTTP 请求）"""
        return self._last_cwd

    # ── 内部 HTTP 方法 ──

    def _get(self, path: str, timeout: int = 10) -> dict:
        req = urllib.request.Request(self._base_url + path)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())

    def _post(self, path: str, data: dict, timeout: int = 30) -> dict:
        body = json.dumps(data).encode()
        req = urllib.request.Request(
            self._base_url + path,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
