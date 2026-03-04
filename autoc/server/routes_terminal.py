"""终端 WebSocket — PTY 方式支持真正的交互式终端

通路 A (Docker):  xterm.js ←WS→ 本端点 ←PTY→ docker exec -it → 容器 shell
通路 B (本地):    xterm.js ←WS→ 本端点 ←PTY→ 宿主机 shell (cwd=项目目录)

协议（JSON 文本帧）：
  客户端→服务端:  {"type": "input",  "data": "<按键>"}
                  {"type": "resize", "cols": 80, "rows": 24}
  服务端→客户端:  {"type": "output", "data": "<终端输出>"}
                  {"type": "error",  "data": "<错误信息>"}
                  {"type": "status", "data": "connected"|"exited"|"docker_unavailable",
                   "mode": "local"|"docker"}
"""

import asyncio
import fcntl
import json
import logging
import os
import pty
import shutil
import struct
import subprocess
import termios

from fastapi import WebSocket, WebSocketDisconnect

from autoc.server import router, _find_project_path_safe

logger = logging.getLogger("autoc.server.terminal")

_DOCKER_AVAILABLE: bool | None = None
_DOCKER_CHECK_TIME: float = 0.0
_DOCKER_CACHE_TTL = 60.0  # 失败结果 60 秒后重试


def _check_docker() -> bool:
    global _DOCKER_AVAILABLE, _DOCKER_CHECK_TIME
    import time
    now = time.monotonic()
    # 成功结果永久缓存，失败结果 TTL 后重试
    if _DOCKER_AVAILABLE is True:
        return True
    if _DOCKER_AVAILABLE is False and (now - _DOCKER_CHECK_TIME) < _DOCKER_CACHE_TTL:
        return False
    # 检测
    if not shutil.which("docker"):
        _DOCKER_AVAILABLE = False
        _DOCKER_CHECK_TIME = now
        return False
    try:
        r = subprocess.run(["docker", "info"], capture_output=True, timeout=10)
        _DOCKER_AVAILABLE = r.returncode == 0
    except Exception:
        _DOCKER_AVAILABLE = False
    _DOCKER_CHECK_TIME = now
    return _DOCKER_AVAILABLE


def _container_name_for(project_name: str) -> str:
    from autoc.core.project.manager import slugify_project_name
    return f"autoc-sandbox-{slugify_project_name(project_name)}"


def _find_running_container(container_name: str) -> str | None:
    try:
        r = subprocess.run(
            ["docker", "ps", "-q", "--filter", f"name=^{container_name}$"],
            capture_output=True, text=True, timeout=10,
        )
        cid = r.stdout.strip()
        return cid or None
    except Exception:
        return None


def _find_any_sandbox_container() -> str | None:
    try:
        r = subprocess.run(
            ["docker", "ps", "-q", "--filter", "name=autoc-sandbox"],
            capture_output=True, text=True, timeout=10,
        )
        cid = r.stdout.strip().split("\n")[0]
        return cid or None
    except Exception:
        return None


def _find_container_any_state(container_name: str) -> tuple[str | None, bool]:
    """返回 (container_id, is_running)。容器不存在时返回 (None, False)。"""
    try:
        r = subprocess.run(
            ["docker", "inspect", "-f", "{{.Id}} {{.State.Running}}", container_name],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            return None, False
        parts = r.stdout.strip().split()
        if len(parts) < 2:
            return None, False
        cid = parts[0][:12]
        is_running = parts[1].lower() == "true"
        return cid, is_running
    except Exception:
        return None, False


def _create_container(
    project_path: str, container_name: str, image: str = "nikolaik/python-nodejs:python3.12-nodejs22",
) -> str:
    """创建或启动沙箱容器。安全策略：不删除已有容器，仅启动已停止的或创建新的。"""
    cid, is_running = _find_container_any_state(container_name)
    if cid:
        if is_running:
            return cid
        # 容器存在但已停止，启动即可
        r = subprocess.run(
            ["docker", "start", container_name],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode == 0:
            return cid
        raise RuntimeError(f"启动已存在容器失败: {r.stderr.strip()}")

    cmd = [
        "docker", "run", "-d", "--name", container_name,
        "-v", f"{os.path.abspath(project_path)}:/workspace", "-w", "/workspace",
        "--memory", "2g", "--cpus=2.0", "--network", "bridge",
        "--security-opt", "no-new-privileges", "--cap-drop", "ALL",
        "--cap-add", "CHOWN", "--cap-add", "DAC_OVERRIDE",
        "--cap-add", "FOWNER", "--cap-add", "SETGID",
        "--cap-add", "SETUID", "--cap-add", "NET_BIND_SERVICE",
        image, "tail", "-f", "/dev/null",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"容器启动失败: {r.stderr.strip()}")
    return r.stdout.strip()[:12]


# ─── PTY Shell ───────────────────────────────────────────────────

def _make_pty(rows: int = 30, cols: int = 120) -> tuple[int, int]:
    master_fd, slave_fd = pty.openpty()
    winsize = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, winsize)
    return master_fd, slave_fd


async def _start_local_shell(
    cwd: str, rows: int = 30, cols: int = 120,
) -> tuple[asyncio.subprocess.Process, int]:
    master_fd, slave_fd = _make_pty(rows, cols)
    shell_bin = os.environ.get("SHELL", "/bin/bash")
    try:
        proc = await asyncio.create_subprocess_exec(
            shell_bin, "-l",
            stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
            cwd=cwd,
            env={**os.environ, "TERM": "xterm-256color"},
            preexec_fn=os.setsid,
        )
    except Exception:
        os.close(master_fd)
        os.close(slave_fd)
        raise
    os.close(slave_fd)
    return proc, master_fd


async def _start_docker_shell(
    container_id: str, rows: int = 30, cols: int = 120,
) -> tuple[asyncio.subprocess.Process, int]:
    master_fd, slave_fd = _make_pty(rows, cols)
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", "-it",
            "-e", "TERM=xterm-256color",
            "-e", f"COLUMNS={cols}", "-e", f"LINES={rows}",
            container_id, "/bin/bash",
            stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
            preexec_fn=os.setsid,
        )
    except Exception:
        os.close(master_fd)
        os.close(slave_fd)
        raise
    os.close(slave_fd)
    return proc, master_fd


# ─── WebSocket ↔ PTY 双向管道 ────────────────────────────────────

async def _pipe_pty(websocket: WebSocket, proc, master_fd: int):
    loop = asyncio.get_running_loop()

    flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
    fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    queue: asyncio.Queue[bytes | None] = asyncio.Queue()

    def _on_readable():
        try:
            data = os.read(master_fd, 4096)
            queue.put_nowait(data if data else None)
        except OSError:
            queue.put_nowait(None)

    loop.add_reader(master_fd, _on_readable)

    async def _sender():
        try:
            while True:
                data = await queue.get()
                if data is None:
                    break
                await websocket.send_json({
                    "type": "output",
                    "data": data.decode("utf-8", errors="replace"),
                })
        except Exception:
            pass
        try:
            await websocket.send_json({"type": "status", "data": "exited"})
        except Exception:
            pass

    sender = asyncio.create_task(_sender())

    try:
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            mtype = msg.get("type")
            if mtype == "input":
                try:
                    os.write(master_fd, msg["data"].encode("utf-8"))
                except OSError:
                    break
            elif mtype == "resize":
                try:
                    ws = struct.pack(
                        "HHHH", msg.get("rows", 30), msg.get("cols", 120), 0, 0,
                    )
                    fcntl.ioctl(master_fd, termios.TIOCSWINSZ, ws)
                except OSError:
                    pass
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        try:
            loop.remove_reader(master_fd)
        except Exception:
            pass
        sender.cancel()
        try:
            await sender
        except asyncio.CancelledError:
            pass
        try:
            os.close(master_fd)
        except OSError:
            pass
        if proc.returncode is None:
            try:
                proc.kill()
            except Exception:
                pass
        try:
            await proc.wait()
        except Exception:
            pass


# ─── WebSocket 端点 ──────────────────────────────────────────────

@router.websocket("/terminal/{project_name}")
async def websocket_terminal(websocket: WebSocket, project_name: str):
    await websocket.accept()

    # 默认 auto：优先连接 Docker 沙箱，沙箱不可用时才回落到本地 Shell
    # 显式传 local 仅用于调试，不应在生产沙箱模式下出现
    mode = (websocket.query_params.get("mode") or "auto").lower()
    if mode not in ("auto", "docker", "local"):
        mode = "auto"

    try:
        project_path = _find_project_path_safe(project_name)
        if not project_path:
            await websocket.send_json({
                "type": "error",
                "data": f"项目 '{project_name}' 不存在。请先创建或运行项目。",
            })
            await websocket.close(code=1011)
            return

        proc = None
        master_fd = None
        actual_mode = "local"

        if mode in ("auto", "docker"):
            docker_ok = _check_docker()
            if docker_ok:
                container_name = _container_name_for(project_name)
                container_id = _find_running_container(container_name)
                if not container_id:
                    container_id = _find_any_sandbox_container()
                if not container_id:
                    try:
                        container_id = await asyncio.get_running_loop().run_in_executor(
                            None, _create_container, project_path, container_name,
                        )
                    except Exception as e:
                        logger.warning(f"Docker 容器启动失败: {e}")
                        docker_ok = False
                if docker_ok and container_id:
                    try:
                        proc, master_fd = await _start_docker_shell(container_id)
                        actual_mode = "docker"
                    except Exception as e:
                        logger.warning(f"Docker Shell 启动失败: {e}")
                        proc = None

        if proc is None and mode in ("docker", "auto"):
            # 强制沙箱策略：docker/auto 模式下 Docker 不可用时拒绝连接，不回落本地 Shell
            logger.warning(f"Docker 不可用，拒绝终端连接 (mode={mode}): {project_name}")
            await websocket.send_json({
                "type": "status", "data": "docker_unavailable",
                "message": "Docker 沙箱不可用，无法启动终端",
            })
            await websocket.close(code=1011)
            return

        if proc is None:
            actual_mode = "local"
            proc, master_fd = await _start_local_shell(project_path)

        await websocket.send_json({
            "type": "status", "data": "connected", "mode": actual_mode,
        })
        await _pipe_pty(websocket, proc, master_fd)

    except WebSocketDisconnect:
        logger.info(f"终端 WS 断开: {project_name}")
    except Exception as e:
        logger.error(f"终端 WS 异常: {e}")
        try:
            await websocket.send_json({"type": "error", "data": str(e)})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
