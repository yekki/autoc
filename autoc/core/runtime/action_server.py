#!/usr/bin/env python3
"""Action Execution Server — 容器内持久化 Shell 服务

在 Docker 容器内运行的轻量 HTTP 服务，提供持久 bash session：
- cd / export 等环境状态跨请求保持
- 支持后台进程管理
- 支持输入发送（交互式进程，不阻塞 execute 锁）

通信协议：
  POST /execute  {"command": "...", "timeout": 30}
    → {"exit_code": 0, "output": "...", "cwd": "/workspace"}

  POST /input    {"text": "y\\n"}
    → {"ok": true}

  GET  /alive    → {"status": "running", "pid": ...}

  POST /reset    → 重启 bash session

启动方式（由宿主侧自动注入并执行）：
  python3 /tmp/action_server.py --port 23456
"""

import json
import os
import select
import signal
import subprocess
import sys
import threading
import time
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler

# 与 autoc/tools/schemas.py 的 ACTION_SERVER_DEFAULT_PORT 保持同步
# 此文件在容器内独立运行，不能 import schemas
ACTION_SERVER_DEFAULT_PORT = 23456

_READ_CHUNK = 4096


class PersistentBash:
    """通过 subprocess 维护一个持久 bash 进程

    锁策略：
    - _exec_lock: execute() 独占锁，保证一次只执行一条命令
    - _stdin_lock: send_input() 使用，允许在 execute 等待 stdout 时并发写入
    """

    NO_OUTPUT_TIMEOUT = 30

    def __init__(self, cwd: str = "/workspace"):
        self._cwd = cwd
        self._last_cwd = cwd
        self._proc: subprocess.Popen | None = None
        self._exec_lock = threading.Lock()
        self._stdin_lock = threading.Lock()
        self._start()

    def _start(self):
        self._proc = subprocess.Popen(
            ["bash", "--norc", "--noprofile"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=self._cwd,
            env={**os.environ, "TERM": "dumb", "PS1": ""},
            bufsize=0,
        )

    @property
    def pid(self) -> int:
        return self._proc.pid if self._proc else -1

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def cwd(self) -> str:
        return self._last_cwd

    def execute(self, command: str, timeout: int = 120) -> tuple[int, str, str]:
        """执行命令并等待完成，返回 (exit_code, output, cwd)

        双重超时策略（对齐 OpenHands NO_CHANGE_TIMEOUT_SECONDS）：
        - 总时间上限 `timeout` 秒（硬限，防无限阻塞）
        - 无新输出 NO_OUTPUT_TIMEOUT 秒则提前超时（智能超时）
        超时后重置 bash session，防止残留进程污染后续命令。

        使用 os.read 非阻塞读取替代 readline，避免部分行（如进度条）导致阻塞。
        sentinel 行同时输出 exit_code 和 cwd，消除额外 pwd 调用。
        """
        with self._exec_lock:
            if not self.alive:
                self._start()

            sentinel = f"__AUTOC_{uuid.uuid4().hex}__"
            # $'...' ANSI-C quoting 转义规则（顺序不可颠倒）：
            #   1. \ → \\   必须第一步，避免后续步骤引入的 \ 被再次转义
            #   2. ' → \'   闭合单引号保护
            #   3. \r → \r  真正的 CR 控制字符转为 ANSI-C \r 字面量（防止 PTY 污染 sentinel）
            #   4. \n → \n  真正的换行符转为 ANSI-C \n 字面量，避免多行命令破坏 sentinel 解析
            # 注意：bash $'...' 中 \n 会还原为换行，整体行为等价于原命令，但 sentinel 在同一行
            escaped = (
                command
                .replace("\\", "\\\\")
                .replace("'", "\\'")
                .replace("\r", "\\r")
                .replace("\n", "\\n")
            )
            # sentinel 行同时输出 exit_code 和 pwd，避免额外 execute("pwd")
            # 注意：full_cmd 末尾的 \n 是向 PTY stdin 写入的真实换行（触发 shell 执行），不在转义范围内
            full_cmd = f"eval $'{escaped}'\necho \"{sentinel} $? $(pwd)\"\n"
            with self._stdin_lock:
                self._proc.stdin.write(full_cmd.encode())
                self._proc.stdin.flush()

            buf = ""
            output_lines = []
            start = time.monotonic()
            last_output_time = start
            exit_code = -1
            result_cwd = self._last_cwd
            stdout_fd = self._proc.stdout.fileno()

            while True:
                now = time.monotonic()
                if now - start > timeout:
                    self._force_reset()
                    return -1, "\n".join(output_lines) + f"\n[超时] 命令执行超过 {timeout} 秒（已重置 bash session）", self._last_cwd
                if now - last_output_time > self.NO_OUTPUT_TIMEOUT:
                    self._force_reset()
                    return -1, "\n".join(output_lines) + f"\n[超时] {self.NO_OUTPUT_TIMEOUT} 秒无新输出（已重置 bash session）", self._last_cwd

                ready, _, _ = select.select([stdout_fd], [], [], 1.0)
                if not ready:
                    continue

                chunk = os.read(stdout_fd, _READ_CHUNK)
                if not chunk:
                    break
                last_output_time = time.monotonic()
                buf += chunk.decode("utf-8", errors="replace")

                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    if sentinel in line:
                        # 格式: __AUTOC_xxx__ <exit_code> <cwd>
                        tail = line.split(sentinel, 1)[1].strip()
                        parts = tail.split(None, 1)
                        if parts:
                            try:
                                exit_code = int(parts[0])
                            except ValueError:
                                exit_code = -1
                            if len(parts) > 1:
                                result_cwd = parts[1]
                                self._last_cwd = result_cwd
                        # sentinel 后 buf 中的残余内容丢弃（属于下一轮）
                        buf = ""
                        return exit_code, "\n".join(output_lines), result_cwd
                    output_lines.append(line)

            return exit_code, "\n".join(output_lines), result_cwd

    def _force_reset(self):
        """超时后强制重置 bash，防止残留进程污染后续命令"""
        if self._proc:
            if self.alive:
                self._proc.kill()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
            # 显式关闭管道防止 fd 泄漏
            for pipe in (self._proc.stdin, self._proc.stdout, self._proc.stderr):
                if pipe:
                    try:
                        pipe.close()
                    except Exception:
                        pass
        self._start()

    def send_input(self, text: str) -> bool:
        """向运行中的进程发送输入（不阻塞 execute）

        使用独立的 stdin 锁，允许在 execute 等待 stdout 时并发写入 stdin。
        """
        if not self.alive:
            return False
        try:
            with self._stdin_lock:
                self._proc.stdin.write(text.encode())
                self._proc.stdin.flush()
            return True
        except Exception:
            return False

    def reset(self):
        """重启 bash session"""
        with self._exec_lock:
            self._force_reset()

    def close(self):
        if self._proc:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()


_bash: PersistentBash | None = None


class ActionHandler(BaseHTTPRequestHandler):
    """HTTP 请求处理器"""

    def log_message(self, format, *args):
        pass

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length))

    def _respond(self, code: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/alive":
            self._respond(200, {
                "status": "running",
                "pid": _bash.pid if _bash else -1,
                "alive": _bash.alive if _bash else False,
            })
        else:
            self._respond(404, {"error": "not found"})

    def do_POST(self):
        body = self._read_body()

        if self.path == "/execute":
            command = body.get("command", "")
            timeout = body.get("timeout", 120)
            if not command:
                self._respond(400, {"error": "command required"})
                return
            exit_code, output, cwd = _bash.execute(command, timeout=timeout)
            self._respond(200, {
                "exit_code": exit_code,
                "output": output,
                "cwd": cwd,
            })

        elif self.path == "/input":
            text = body.get("text", "")
            ok = _bash.send_input(text)
            self._respond(200, {"ok": ok})

        elif self.path == "/reset":
            _bash.reset()
            self._respond(200, {"ok": True})

        else:
            self._respond(404, {"error": "not found"})


def main():
    global _bash
    port = ACTION_SERVER_DEFAULT_PORT
    if len(sys.argv) > 2 and sys.argv[1] == "--port":
        port = int(sys.argv[2])

    _bash = PersistentBash(cwd="/workspace")

    server = HTTPServer(("127.0.0.1", port), ActionHandler)
    print(f"Action Server listening on 127.0.0.1:{port}", flush=True)

    def shutdown_handler(sig, frame):
        _bash.close()
        server.shutdown()

    signal.signal(signal.SIGTERM, shutdown_handler)
    signal.signal(signal.SIGINT, shutdown_handler)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        _bash.close()


if __name__ == "__main__":
    main()
