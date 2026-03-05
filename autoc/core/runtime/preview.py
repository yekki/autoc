"""Preview Manager — 项目类型检测与预览管理

检测生成项目的类型（Web 前端/后端 API/CLI 工具/纯库），
根据类型自动选择 dev server 启动命令，提供预览 URL 或执行输出。

支持两种运行时:
1. Docker 沙箱: 容器内启动 → 端口映射 → localhost 访问
2. 本地进程: 直接启动子进程 → localhost 访问
3. 云沙箱 (E2B/Daytona): 远端启动 → 公网 Preview URL
"""

import json
import logging
import os
import re
import subprocess
import socket
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger("autoc.preview")


class ProjectType(str, Enum):
    WEB_FRONTEND = "web_frontend"
    WEB_FULLSTACK = "web_fullstack"
    WEB_BACKEND = "web_backend"
    CLI_TOOL = "cli_tool"
    GUI_APP = "gui_app"       # pygame / tkinter / arcade 等需要图形环境的应用
    LIBRARY = "library"
    UNKNOWN = "unknown"


# 需要图形显示环境的框架，无法在无头容器中预览
_GUI_FRAMEWORK_RE = re.compile(
    r"(import\s+pygame|from\s+pygame\b"
    r"|import\s+tkinter|from\s+tkinter\b"
    r"|import\s+turtle\b"
    r"|import\s+arcade|from\s+arcade\b"
    r"|import\s+pyglet|from\s+pyglet\b"
    r"|import\s+kivy|from\s+kivy\b"
    r"|import\s+wx\b|import\s+PyQt[456]|from\s+PyQt[456]\b"
    r"|import\s+PySide[26]|from\s+PySide[26]\b"
    r")"
)


@dataclass
class PreviewInfo:
    """预览信息"""
    available: bool = False
    project_type: ProjectType = ProjectType.UNKNOWN
    url: str = ""
    host: str = "localhost"
    port: int = 0
    command: str = ""
    pid: str = ""
    runtime: str = "local"
    message: str = ""
    files_hint: list[str] = field(default_factory=list)
    framework: str = ""  # flask / fastapi / django / node / vite / go / static / ""


def _find_free_port() -> int:
    """在高位端口范围内随机分配一个空闲端口"""
    return find_free_port()


class ProjectTypeDetector:
    """从工作区文件推断项目类型和适合的启动命令"""

    @staticmethod
    def detect(workspace_dir: str) -> tuple[ProjectType, str, int]:
        """检测项目类型、推荐启动命令、默认端口。

        Returns:
            (project_type, start_command, default_port)
        """
        pkg_json = os.path.join(workspace_dir, "package.json")
        req_txt = os.path.join(workspace_dir, "requirements.txt")
        index_html = os.path.join(workspace_dir, "index.html")
        manage_py = os.path.join(workspace_dir, "manage.py")
        app_py = os.path.join(workspace_dir, "app.py")
        main_py = os.path.join(workspace_dir, "main.py")
        pyproject = os.path.join(workspace_dir, "pyproject.toml")

        # 1) Node.js 项目 — package.json
        if os.path.isfile(pkg_json):
            try:
                with open(pkg_json, encoding="utf-8") as f:
                    pkg = json.load(f)
                scripts = pkg.get("scripts", {})
                deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}

                # Next.js / Nuxt / Remix
                for fw, cmd, port in [
                    ("next", "npm run dev", 3000),
                    ("nuxt", "npm run dev", 3000),
                    ("@remix-run/dev", "npm run dev", 3000),
                ]:
                    if fw in deps:
                        return ProjectType.WEB_FULLSTACK, cmd, port

                # concurrently 驱动的 monorepo：root dev 命令只是聚合，
                # 跳过步骤 1 整体，交给步骤 5 _detect_monorepo() 处理
                _is_concurrently = "concurrently" in scripts.get("dev", "")

                if not _is_concurrently:
                    # Vite / React / Vue / Svelte / Angular
                    if "dev" in scripts:
                        return ProjectType.WEB_FRONTEND, "npm run dev", 5173
                    if "start" in scripts:
                        return ProjectType.WEB_FRONTEND, "npm start", 3000

                    # Express / Fastify / Koa → 后端
                    for fw in ("express", "fastify", "koa", "@hapi/hapi"):
                        if fw in deps:
                            cmd = "npm run dev" if "dev" in scripts else "npm start"
                            return ProjectType.WEB_BACKEND, cmd, 3000

                    if scripts:
                        return ProjectType.WEB_FRONTEND, "npm start", 3000

            except (json.JSONDecodeError, OSError):
                pass

        # 2) 纯静态 HTML
        if os.path.isfile(index_html):
            port = _find_free_port()
            return ProjectType.WEB_FRONTEND, f"python -m http.server {port}", port

        # 3) Django
        if os.path.isfile(manage_py):
            port = _find_free_port()
            return ProjectType.WEB_FULLSTACK, f"python manage.py runserver 0.0.0.0:{port}", port

        # 4) Flask / FastAPI / 其他 Python Web（优先检查 app.py / main.py 文件 + app/ 包）
        _web_candidates = list((app_py, main_py))
        # app/ 包目录：如果 app.py 不存在但 app/ 目录有 __init__.py，也作为候选
        for _pkg in ("app", "application"):
            _pkg_init = os.path.join(workspace_dir, _pkg, "__init__.py")
            if os.path.isfile(_pkg_init) and not os.path.isfile(os.path.join(workspace_dir, f"{_pkg}.py")):
                _web_candidates.append(_pkg_init)

        for py_file in _web_candidates:
            if not os.path.isfile(py_file):
                continue
            try:
                with open(py_file, encoding="utf-8") as _fp:
                    content = _fp.read(4096)
            except OSError:
                continue

            # GUI 框架检测优先于 CLI 判断，避免把游戏/桌面应用误识别为 CLI 工具
            if _GUI_FRAMEWORK_RE.search(content):
                return ProjectType.GUI_APP, "", 0

            if re.search(r"(Flask|FastAPI|Bottle|Tornado|Sanic)", content):
                # 包目录用目录名作为模块名（flask --app app），文件用文件名去 .py
                if os.path.basename(py_file) == "__init__.py":
                    module_name = os.path.basename(os.path.dirname(py_file))
                else:
                    module_name = os.path.splitext(os.path.basename(py_file))[0]
                fname = f"{module_name}.py" if os.path.basename(py_file) != "__init__.py" else module_name
                if "FastAPI" in content:
                    port = _find_free_port()
                    return ProjectType.WEB_BACKEND, f"python -m uvicorn {module_name}:app --host 0.0.0.0 --port {port} --reload", port
                port = _find_free_port()
                return ProjectType.WEB_BACKEND, f"flask --app {module_name} run --host 0.0.0.0 --port {port} --debug", port

            if re.search(r"(argparse|click|typer|sys\.argv)", content):
                _fe_dirs = {"frontend", "client", "web", "ui"}
                _be_dirs = {"backend", "server", "api"}
                try:
                    _subs = set(os.listdir(workspace_dir))
                except OSError:
                    _subs = set()
                if not (_subs & _fe_dirs and _subs & _be_dirs):
                    return ProjectType.CLI_TOOL, f"python {os.path.basename(py_file)} --help", 0

        # 5) Monorepo: frontend/backend 分目录结构（在扫描根 .py 文件之前检测，避免辅助脚本误判）
        monorepo_result = ProjectTypeDetector._detect_monorepo(workspace_dir)
        if monorepo_result:
            return monorepo_result

        # 6) 扫描根目录所有 .py 文件，检测 Web 框架或 CLI 入口
        # 排除辅助/验证脚本：test_*.py / verify_*.py / check_*.py / setup.py
        try:
            root_py_files = sorted(
                f for f in os.listdir(workspace_dir)
                if f.endswith(".py") and f not in ("app.py", "main.py", "conftest.py")
                and not f.startswith("test_") and not f.startswith("verify_")
                and not f.startswith("check_") and f != "setup.py"
            )
        except OSError:
            root_py_files = []
        for fname in root_py_files:
            fpath = os.path.join(workspace_dir, fname)
            if not os.path.isfile(fpath):
                continue
            try:
                with open(fpath, encoding="utf-8") as _fp:
                    content = _fp.read(4096)
            except OSError:
                continue
            if _GUI_FRAMEWORK_RE.search(content):
                return ProjectType.GUI_APP, "", 0
            if re.search(r"(Flask|FastAPI|Bottle|Tornado|Sanic)", content):
                module_name = os.path.splitext(fname)[0]
                if "FastAPI" in content:
                    port = _find_free_port()
                    return ProjectType.WEB_BACKEND, f"python -m uvicorn {module_name}:app --host 0.0.0.0 --port {port} --reload", port
                port = _find_free_port()
                has_run = re.search(r"\.run\s*\(", content)
                if has_run:
                    return ProjectType.WEB_BACKEND, f"python {fname}", port
                return ProjectType.WEB_BACKEND, f"flask --app {module_name} run --host 0.0.0.0 --port {port} --debug", port
            if re.search(r"(argparse|click|typer|sys\.argv)", content):
                return ProjectType.CLI_TOOL, f"python {fname} --help", 0
            if re.search(r'if\s+__name__\s*==\s*["\']__main__["\']', content):
                # 含 .run() 调用时可能是间接引用 web 框架（如 from app import create_app）
                run_match = re.search(r"\.run\s*\(", content)
                if run_match:
                    is_web = False
                    # 层 1：requirements.txt 显式列出 web 框架
                    if os.path.isfile(req_txt):
                        try:
                            with open(req_txt, encoding="utf-8") as _rp:
                                _req_content = _rp.read(2048).lower()
                            if any(kw in _req_content for kw in ("flask", "fastapi", "django", "uvicorn", "sanic")):
                                is_web = True
                        except OSError:
                            pass
                    # 层 2：.run() 参数含 web 特征（debug=/host=/port=）
                    if not is_web and re.search(r"\.run\s*\([^)]*(?:debug|host|port)\s*=", content):
                        is_web = True
                    # 层 3：工作区其他 .py 文件直接导入 web 框架
                    if not is_web:
                        is_web = ProjectTypeDetector._workspace_has_web_framework(workspace_dir, exclude=fname)
                    if is_web:
                        port = _find_free_port()
                        return ProjectType.WEB_BACKEND, f"python {fname}", port
                return ProjectType.CLI_TOOL, f"python {fname} --help", 0

        # 7) 有 requirements.txt 但未匹配上面的规则 → 检查依赖推断类型
        if os.path.isfile(req_txt):
            try:
                with open(req_txt, encoding="utf-8") as _fp:
                    content = _fp.read(2048)
                if any(kw in content.lower() for kw in ("pygame", "arcade", "pyglet", "kivy", "tkinter")):
                    return ProjectType.GUI_APP, "", 0
                if any(kw in content.lower() for kw in ("click", "typer", "argparse")):
                    return ProjectType.CLI_TOOL, "python main.py --help", 0
                if any(kw in content.lower() for kw in ("flask", "fastapi", "django", "uvicorn")):
                    return ProjectType.WEB_BACKEND, "python app.py", 5000
            except OSError:
                pass

        # 7.5) 有 pyproject.toml
        if os.path.isfile(pyproject):
            return ProjectType.LIBRARY, "", 0

        # 8) Go 项目 — go.mod 或独立 .go 文件
        go_mod = os.path.join(workspace_dir, "go.mod")
        main_go = os.path.join(workspace_dir, "main.go")
        cmd_dir = os.path.join(workspace_dir, "cmd")
        if os.path.isfile(go_mod):
            try:
                with open(go_mod, encoding="utf-8") as _fp:
                    content = _fp.read(4096)
                for fw in ("gin-gonic/gin", "labstack/echo", "gofiber/fiber"):
                    if fw in content:
                        return ProjectType.WEB_BACKEND, "go run .", 8080
                if os.path.isfile(main_go) or os.path.isdir(cmd_dir):
                    return ProjectType.CLI_TOOL, "go run .", 0
                return ProjectType.LIBRARY, "", 0
            except OSError:
                pass
        elif os.path.isfile(main_go):
            return ProjectType.CLI_TOOL, "go run .", 0
        elif os.path.isdir(cmd_dir) and any(
            f.endswith(".go") for f in os.listdir(cmd_dir) if os.path.isfile(os.path.join(cmd_dir, f))
        ):
            return ProjectType.CLI_TOOL, "go run ./cmd/...", 0
        else:
            try:
                has_go = any(f.endswith(".go") for f in os.listdir(workspace_dir)
                            if os.path.isfile(os.path.join(workspace_dir, f)))
                if has_go:
                    return ProjectType.CLI_TOOL, "go run .", 0
            except OSError:
                pass

        # 9) 兜底：有 .py 文件但未匹配特定框架/CLI 模式，视为简单脚本
        all_py = [f for f in (["app.py", "main.py"] + root_py_files)
                  if os.path.isfile(os.path.join(workspace_dir, f))]
        if all_py:
            fname = all_py[0]
            try:
                with open(os.path.join(workspace_dir, fname), encoding="utf-8") as _fp:
                    _content = _fp.read(4096)
                if re.search(r"(argparse|click|typer|sys\.argv)", _content):
                    return ProjectType.CLI_TOOL, f"python {fname} --help", 0
            except OSError:
                pass
            return ProjectType.CLI_TOOL, f"python {fname}", 0

        return ProjectType.UNKNOWN, "", 0

    @staticmethod
    def _workspace_has_web_framework(workspace_dir: str, exclude: str = "") -> bool:
        """扫描工作区根目录 .py 文件和常见包目录，判断是否有 Web 框架"""
        _fw_re = re.compile(r"(Flask|FastAPI|Bottle|Tornado|Sanic)")

        # 1) 根目录 .py 文件
        try:
            py_files = [f for f in os.listdir(workspace_dir)
                        if f.endswith(".py") and f != exclude]
        except OSError:
            py_files = []
        for f in py_files:
            fpath = os.path.join(workspace_dir, f)
            if not os.path.isfile(fpath):
                continue
            try:
                with open(fpath, encoding="utf-8") as fp:
                    src = fp.read(4096)
            except OSError:
                continue
            if _fw_re.search(src):
                return True

        # 2) 常见包目录的 __init__.py / app.py / main.py
        for pkg in ("app", "application", "src", "server", "api"):
            pkg_dir = os.path.join(workspace_dir, pkg)
            if not os.path.isdir(pkg_dir):
                continue
            for entry in ("__init__.py", "app.py", "main.py"):
                fpath = os.path.join(pkg_dir, entry)
                if not os.path.isfile(fpath):
                    continue
                try:
                    with open(fpath, encoding="utf-8") as fp:
                        src = fp.read(4096)
                except OSError:
                    continue
                if _fw_re.search(src):
                    return True

        return False

    @staticmethod
    def _detect_monorepo(workspace_dir: str) -> tuple[ProjectType, str, int] | None:
        """检测 frontend/backend 子目录分离的 monorepo 结构"""
        frontend_dirs = ("frontend", "client", "web", "ui")
        backend_dirs = ("backend", "server", "api")

        fe_dir = fe_cmd = None
        fe_port = 0
        for name in frontend_dirs:
            d = os.path.join(workspace_dir, name)
            pkg = os.path.join(d, "package.json")
            idx = os.path.join(d, "index.html")
            if os.path.isfile(pkg):
                try:
                    with open(pkg, encoding="utf-8") as f:
                        data = json.load(f)
                    scripts = data.get("scripts", {})
                    if "dev" in scripts:
                        fe_dir, fe_cmd, fe_port = name, f"cd {name} && npm run dev", 5173
                    elif "start" in scripts:
                        fe_dir, fe_cmd, fe_port = name, f"cd {name} && npm start", 3000
                except (json.JSONDecodeError, OSError):
                    pass
                if fe_dir:
                    break
            elif os.path.isfile(idx):
                port = _find_free_port()
                fe_dir, fe_cmd, fe_port = name, f"cd {name} && python -m http.server {port}", port
                break

        be_dir = be_cmd = None
        for name in backend_dirs:
            d = os.path.join(workspace_dir, name)
            if not os.path.isdir(d):
                continue
            # 检测候选入口：根级 + 一级子目录（如 backend/app/main.py）
            py_candidates = [
                (os.path.join(d, py), py)
                for py in ("main.py", "app.py")
            ]
            try:
                for subdir in os.listdir(d):
                    sd = os.path.join(d, subdir)
                    if os.path.isdir(sd):
                        for py in ("main.py", "app.py"):
                            py_candidates.append((os.path.join(sd, py), f"{subdir}/{py}"))
            except OSError:
                pass
            for fpath, rel in py_candidates:
                if not os.path.isfile(fpath):
                    continue
                try:
                    with open(fpath, encoding="utf-8") as _fp:
                        content = _fp.read(4096)
                except OSError:
                    continue
                if re.search(r"(Flask|FastAPI|Bottle|Tornado|Sanic)", content):
                    if "FastAPI" in content:
                        module_path = os.path.splitext(rel)[0].replace("/", ".")
                        be_dir = name
                        be_cmd = f"cd {name} && python -m uvicorn {module_path}:app --host 0.0.0.0 --port 8000"
                    else:
                        be_dir = name
                        be_cmd = f"cd {name} && python {rel}"
                    break
            manage = os.path.join(d, "manage.py")
            if not be_dir and os.path.isfile(manage):
                be_dir, be_cmd = name, f"cd {name} && python manage.py runserver 0.0.0.0:8000"
            # 回退：有 requirements.txt 含 fastapi/flask 也视为后端
            if not be_dir:
                req_f = os.path.join(d, "requirements.txt")
                if os.path.isfile(req_f):
                    try:
                        with open(req_f, encoding="utf-8") as _fp:
                            req_content = _fp.read(1024).lower()
                        if "fastapi" in req_content or "uvicorn" in req_content:
                            be_dir = name
                            be_cmd = f"cd {name} && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000"
                        elif "flask" in req_content:
                            be_dir = name
                            be_cmd = f"cd {name} && flask run --host 0.0.0.0 --port 5000"
                    except OSError:
                        pass
            if be_dir:
                break

        if fe_dir and be_dir:
            cmd = f"({be_cmd} &) && {fe_cmd}"
            return ProjectType.WEB_FULLSTACK, cmd, fe_port
        if fe_dir:
            return ProjectType.WEB_FRONTEND, fe_cmd, fe_port
        if be_dir:
            port = _find_free_port()
            return ProjectType.WEB_BACKEND, be_cmd, port

        return None


# 端口范围定义（对齐 OpenHands 分区策略）
SANDBOX_PORT_RANGE = (30000, 39999)     # 沙箱服务端口（Action Server 等）
APP_PORT_RANGE = (40000, 54999)         # 应用端口（Web 应用、数据库等）

_PORT_LOCK_DIR = "/tmp/autoc-port-locks"
_PORT_LOCK_FDS: dict = {}  # port → lock file descriptor
_PORT_LOCK_FDS_MUTEX = threading.Lock()


def find_free_port(start: int = 30000, end: int = 55000) -> int:
    """在专用高位端口范围内分配空闲端口，使用文件锁防止 TOCTOU 竞态

    lock_fd 存储在 _PORT_LOCK_FDS 中，由 release_port_lock() 正确释放。
    """
    import fcntl
    import random

    os.makedirs(_PORT_LOCK_DIR, exist_ok=True)
    candidates = random.sample(range(start, end), min(300, end - start))

    for port in candidates:
        lock_path = os.path.join(_PORT_LOCK_DIR, f"port-{port}.lock")
        lock_fd = None
        try:
            lock_fd = open(lock_path, "w")
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, IOError):
            if lock_fd:
                lock_fd.close()
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                with _PORT_LOCK_FDS_MUTEX:
                    _PORT_LOCK_FDS[port] = lock_fd
                return port
            except OSError:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                    lock_fd.close()
                except Exception:
                    pass
                continue

    raise RuntimeError(f"无法在 {start}-{end} 范围内找到空闲端口")


def release_port_lock(port: int):
    """释放端口文件锁 — 解锁 → 关闭 fd → 删除文件"""
    import fcntl

    with _PORT_LOCK_FDS_MUTEX:
        lock_fd = _PORT_LOCK_FDS.pop(port, None)
    if lock_fd:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()
        except Exception:
            pass
    lock_path = os.path.join(_PORT_LOCK_DIR, f"port-{port}.lock")
    try:
        os.remove(lock_path)
    except OSError:
        pass


class PreviewManager:
    """管理生成项目的预览生命周期。

    支持三种运行模式:
    - local: 在宿主机直接启动子进程
    - docker: 在 DockerSandbox 容器内启动
    - cloud: 通过 E2B / Daytona 云沙箱启动
    """

    def __init__(self, workspace_dir: str, on_event=None):
        self.workspace_dir = os.path.abspath(workspace_dir)
        self.on_event = on_event or (lambda e: None)
        self._process: Optional[subprocess.Popen] = None
        self._log_file = None
        self._preview_info: Optional[PreviewInfo] = None

    @property
    def preview_info(self) -> Optional[PreviewInfo]:
        return self._preview_info

    def _emit(self, **data):
        self.on_event({"type": "preview_ready", "agent": "system", "data": data})

    # ==================== 检测 ====================

    def detect_project(self) -> tuple[ProjectType, str, int]:
        return ProjectTypeDetector.detect(self.workspace_dir)

    # ==================== 本地预览 ====================

    def start_local(self, command: str = "", port: int = 0, **_kw) -> PreviewInfo:
        """在本地直接启动 dev server 预览"""
        project_type, detected_cmd, detected_port = self.detect_project()

        if not command:
            command = detected_cmd
        if not port:
            port = detected_port or find_free_port()

        framework = self._detect_framework(command)

        if not command:
            info = PreviewInfo(
                available=False,
                project_type=project_type,
                framework=framework,
                message="未检测到可运行的项目类型",
            )
            self._preview_info = info
            return info

        # 需要先装依赖
        self._install_deps_if_needed()

        logger.info(f"[预览] 本地启动: {command} (端口 {port})")
        log_path = os.path.join(self.workspace_dir, ".autoc", "preview.log")
        try:
            env = {**os.environ, "PORT": str(port)}
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            self._log_file = open(log_path, "w")
            self._process = subprocess.Popen(
                command,
                shell=True,
                cwd=self.workspace_dir,
                stdout=self._log_file,
                stderr=subprocess.STDOUT,
                env=env,
            )
        except Exception as e:
            info = PreviewInfo(
                available=False,
                project_type=project_type,
                framework=framework,
                message=f"启动失败: {e}",
            )
            self._preview_info = info
            return info

        # 等待端口就绪
        if port > 0 and self._wait_for_port(port):
            url = f"http://localhost:{port}"

            # 端口可达性验证：确认 HTTP 响应正常
            reachable = self._check_http_reachable(url)
            if not reachable:
                logger.warning(f"端口 {port} 已就绪但 HTTP 不可达，可能被其他进程占用")

            info = PreviewInfo(
                available=True,
                project_type=project_type,
                url=url,
                host="localhost",
                port=port,
                command=command,
                pid=str(self._process.pid),
                runtime="local",
                framework=framework,
                message=f"本地预览已启动: {url}" if reachable else f"预览已启动但可能存在端口冲突: {url}",
            )
            self._preview_info = info
            self._emit(
                preview_url=url, port=port, command=command,
                project_type=project_type.value, runtime="local",
                framework=framework,
            )
            return info

        # 预期端口未就绪 → 从日志检测实际端口
        actual_port = port
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                log_content = f.read(4096)
            framework = self._refine_framework_from_logs(log_content, framework)
            actual = self._detect_actual_port_from_logs(log_content)
            if actual and actual[1] != port:
                actual_port = actual[1]
                logger.info(f"[预览] 日志检测到实际端口: {actual_port}（预期 {port}）")
                if self._wait_for_port(actual_port, retries=10, interval=0.5):
                    url = f"http://localhost:{actual_port}"
                    info = PreviewInfo(
                        available=True,
                        project_type=project_type,
                        url=url,
                        host="localhost",
                        port=actual_port,
                        command=command,
                        pid=str(self._process.pid),
                        runtime="local",
                        framework=framework,
                        message=f"本地预览已启动: {url}",
                    )
                    self._preview_info = info
                    self._emit(
                        preview_url=url, port=actual_port, command=command,
                        project_type=project_type.value, runtime="local",
                        framework=framework,
                    )
                    return info
        except Exception:
            pass

        info = PreviewInfo(
            available=False,
            project_type=project_type,
            command=command,
            port=actual_port,
            runtime="local",
            framework=framework,
            message="Dev server 启动超时，端口未就绪",
        )
        self._preview_info = info
        return info

    # ==================== Docker 预览 ====================

    # Docker 预览可回退的常用端口（优先级从高到低）
    _FALLBACK_PORTS = [8000, 8080, 5000, 3000, 5173, 8888]

    def start_docker(self, sandbox, command: str = "", port: int = 0,
                     **_kw) -> PreviewInfo:
        """在 Docker 沙箱内启动 dev server 预览"""
        project_type, detected_cmd, detected_port = self.detect_project()

        if not command:
            command = detected_cmd
        container_port = port or detected_port or 8000

        if not command:
            info = PreviewInfo(
                available=False,
                project_type=project_type,
                runtime="docker",
                message="未检测到可运行的项目类型",
            )
            self._preview_info = info
            return info

        # 先确保容器就绪，同步已有端口映射（避免后续计算用到空列表）
        sandbox._ensure_container()

        needs_mapping = not any(
            cp == container_port for _, cp in sandbox.port_mappings
        )
        if needs_mapping:
            if sandbox._container_id:
                # 容器已运行，无法动态添加端口映射 → 回退到已有的预映射端口
                fallback = self._pick_premapped_port(sandbox, container_port)
                if fallback:
                    old_port, container_port = container_port, fallback
                    command = self._rewrite_port_in_command(command, old_port, container_port)
                    logger.info(f"[预览] 端口 {old_port} 未预映射，回退到 {container_port}")
                    needs_mapping = False
                else:
                    info = PreviewInfo(
                        available=False,
                        project_type=project_type,
                        runtime="docker",
                        message="容器已运行且无可用的预映射端口",
                    )
                    self._preview_info = info
                    return info
            else:
                host_port = find_free_port()
                sandbox.add_port_mapping(host_port, container_port)

        if not needs_mapping:
            host_port = next(
                hp for hp, cp in sandbox.port_mappings if cp == container_port
            )

        # 安装依赖
        self._install_deps_in_sandbox(sandbox)

        # 启动前清理容器内残留进程，避免端口冲突
        # 容器复用时旧 dev server 可能仍在运行（detach 后进程保活，或重复点击启动预览）
        # 第一层：按进程名全量清理（覆盖 fullstack 多端口场景）
        sandbox.kill_user_processes()
        # 第二层：精确释放目标端口（覆盖非标准进程名，如 Go/Rust/Java 二进制）
        # fuser(psmisc) 优先，回退到 ss(iproute2)+sed
        sandbox._exec_in_container(
            f"fuser -k {container_port}/tcp 2>/dev/null || "
            f"ss -tlnp 'sport = :{container_port}' 2>/dev/null "
            f"| sed -n 's/.*pid=\\([0-9]*\\).*/\\1/p' "
            f"| xargs -r kill 2>/dev/null; "
            f"sleep 0.3; true",
            timeout=5,
        )

        # 向 vite.config.ts/js 注入 host: '0.0.0.0'（防御层）
        # CLI --host 参数可能因 concurrently/npm workspace 包装被丢弃，直接改配置文件最可靠
        self._inject_vite_host_config(sandbox)

        # Docker 容器内需要绑定 0.0.0.0 才能通过端口映射访问
        command = self._patch_host_binding(command)

        # 在容器内启动后台进程
        framework = self._detect_framework(command)
        pid = sandbox.execute_background(command)
        if pid.startswith("["):
            info = PreviewInfo(
                available=False,
                project_type=project_type,
                runtime="docker",
                framework=framework,
                message=f"容器内启动失败: {pid}",
            )
            self._preview_info = info
            return info

        # 等 dev server 输出初始日志，从中检测实际端口和绑定地址
        time.sleep(2)
        bg_log = sandbox.get_background_log(30)
        framework = self._refine_framework_from_logs(bg_log, framework)
        actual = self._detect_actual_port_from_logs(bg_log)
        if actual:
            actual_host, actual_port = actual
            logger.info(
                f"[预览] 日志检测到实际端口: {actual_host}:{actual_port}（预期 {container_port}）"
            )
            self._fix_port_mismatch_in_container(
                sandbox, container_port, actual_host, actual_port,
            )

        # sandbox 操作可能触发端口重新映射，从最新状态读取 host_port
        host_port = next(
            (hp for hp, cp in sandbox.port_mappings if cp == container_port),
            host_port,
        )

        # 等待容器内 dev server 端口就绪（socat 转发后检测 container_port）
        if sandbox.check_port_ready(container_port):
            url = f"http://localhost:{host_port}"
            info = PreviewInfo(
                available=True,
                project_type=project_type,
                url=url,
                host="localhost",
                port=host_port,
                command=command,
                pid=pid,
                runtime="docker",
                framework=framework,
                message=f"Docker 预览已启动: {url}",
            )
            self._preview_info = info
            self._emit(
                preview_url=url, port=host_port, command=command,
                project_type=project_type.value, runtime="docker",
                framework=framework,
            )
            return info

        bg_log = sandbox.get_background_log(20)
        info = PreviewInfo(
            available=False,
            project_type=project_type,
            command=command,
            port=container_port,
            runtime="docker",
            framework=framework,
            message=f"Dev server 启动超时\n{bg_log}",
        )
        self._preview_info = info
        return info

    # ==================== 云沙箱预览 ====================

    def start_cloud(self, runtime, command: str = "", port: int = 0) -> PreviewInfo:
        """通过云沙箱 (E2B / Daytona) 启动预览

        runtime: CloudRuntime 实例（需实现 execute / get_preview_url）
        """
        project_type, detected_cmd, detected_port = self.detect_project()

        if not command:
            command = detected_cmd
        if not port:
            port = detected_port or 8000

        framework = self._detect_framework(command)

        if not command:
            info = PreviewInfo(
                available=False,
                project_type=project_type,
                runtime="cloud",
                framework=framework,
                message="未检测到可运行的项目类型",
            )
            self._preview_info = info
            return info

        try:
            runtime.install_deps(self.workspace_dir)
            pid = runtime.execute_background(command, port)
            preview_url = runtime.get_preview_url(port)

            info = PreviewInfo(
                available=True,
                project_type=project_type,
                url=preview_url,
                port=port,
                command=command,
                pid=str(pid),
                runtime="cloud",
                framework=framework,
                message=f"云端预览已启动: {preview_url}",
            )
            self._preview_info = info
            self._emit(
                preview_url=preview_url, port=port, command=command,
                project_type=project_type.value, runtime="cloud",
                framework=framework,
            )
            return info
        except Exception as e:
            info = PreviewInfo(
                available=False,
                project_type=project_type,
                runtime="cloud",
                framework=framework,
                message=f"云沙箱启动失败: {e}",
            )
            self._preview_info = info
            return info

    # ==================== CLI 工具试运行 ====================

    def run_cli_demo(self, command: str = "", sandbox=None) -> PreviewInfo:
        """对 CLI 工具执行一次示范运行，捕获输出（在 Docker 沙箱内）"""
        project_type, detected_cmd, _ = self.detect_project()
        if not command:
            command = detected_cmd

        if not command:
            return PreviewInfo(available=False, project_type=project_type, message="未检测到 CLI 入口")

        if not sandbox or not sandbox.is_available:
            return PreviewInfo(
                available=False, project_type=project_type, runtime="docker",
                message="Docker 沙箱不可用，无法执行 CLI 试运行",
            )

        # 清理容器内残留进程：Dev 阶段可能启动过 dev server 仍占端口
        try:
            sandbox.kill_user_processes()
            for _cp in (3000, 5000, 5173, 8000, 8080):
                sandbox._exec_in_container(
                    f"fuser -k {_cp}/tcp 2>/dev/null; true", timeout=3,
                )
        except Exception:
            pass

        logger.info(f"[预览] CLI 试运行（沙箱）: {command}")
        output = sandbox.execute(command, timeout=30)

        info = PreviewInfo(
            available=True,
            project_type=project_type,
            command=command,
            runtime="docker",
            message=output,
        )
        self._preview_info = info
        self._emit(
            preview_output=output, command=command,
            project_type=project_type.value, runtime=info.runtime,
        )
        return info

    # ==================== 工具方法 ====================

    # 从 dev server 启动日志中提取实际 host:port 的正则模式
    _LOG_PORT_PATTERNS = [
        # Flask/Werkzeug: " * Running on http://127.0.0.1:5000"
        re.compile(r"Running on\s+(?:https?://)?([\w.]+):(\d+)"),
        # Uvicorn (FastAPI): "Uvicorn running on http://0.0.0.0:8000"
        re.compile(r"Uvicorn running on\s+(?:https?://)?([\w.]+):(\d+)"),
        # Django: "Starting development server at http://0.0.0.0:8000/"
        re.compile(r"development server at\s+(?:https?://)?([\w.]+):(\d+)"),
        # Vite: "  ➜  Local:   http://localhost:5173/"
        re.compile(r"Local:\s+(?:https?://)?([\w.]+):(\d+)"),
        # Go/Gin/Echo/Fiber: "Listening and serving HTTP on :8080"
        re.compile(r"(?:serving|listening)\s+(?:\w+\s+)?on\s+(?:https?://)?([\w.]*):(\d+)", re.IGNORECASE),
    ]

    @staticmethod
    def _detect_actual_port_from_logs(log_text: str) -> tuple[str, int] | None:
        """从 dev server 启动日志中解析实际监听的 (host, port)"""
        for pat in PreviewManager._LOG_PORT_PATTERNS:
            m = pat.search(log_text)
            if m:
                return m.group(1), int(m.group(2))
        # 兜底: "listening on port 3000" / "Server started on port 8080"
        m = re.search(r"(?:listening|started)\s+on\s+(?:port\s+)?:?(\d+)", log_text, re.IGNORECASE)
        if m:
            return "", int(m.group(1))
        return None

    @staticmethod
    def _detect_framework(command: str) -> str:
        """从启动命令推断 Web 框架名"""
        cmd = command.lower()
        if "flask" in cmd:
            return "flask"
        if "uvicorn" in cmd:
            return "fastapi"
        if "manage.py" in cmd and "runserver" in cmd:
            return "django"
        if "vite" in cmd or "vue" in cmd:
            return "vite"
        if any(kw in cmd for kw in ("npm", "npx", "node ", "next", "nuxt")):
            return "node"
        if "http.server" in cmd:
            return "static"
        if "go run" in cmd:
            return "go"
        return ""

    @staticmethod
    def _refine_framework_from_logs(log_text: str, current: str) -> str:
        """日志中含框架指纹时修正 framework（覆盖 python app.py 无法从命令推断的场景）"""
        if current:
            return current
        if "Serving Flask app" in log_text or "Running on" in log_text:
            return "flask"
        if "Uvicorn running on" in log_text:
            return "fastapi"
        if "development server" in log_text and "django" in log_text.lower():
            return "django"
        return current

    def _fix_port_mismatch_in_container(
        self, sandbox, container_port: int, actual_host: str, actual_port: int,
    ) -> bool:
        """容器内实际端口/绑定地址与预期不符时，用 socat 转发修复。

        成功建立转发返回 True，无需转发或失败返回 False。
        """
        port_mismatch = actual_port != container_port
        host_mismatch = actual_host in ("127.0.0.1", "localhost")

        if not port_mismatch and not host_mismatch:
            return False

        if port_mismatch:
            logger.warning(
                f"[预览] 端口不匹配: 预期 {container_port}, 实际 {actual_port}"
            )
        if host_mismatch:
            logger.warning(
                f"[预览] 绑定 {actual_host}, Docker 需要 0.0.0.0"
            )

        # 确保 socat 可用
        sandbox._exec_in_container(
            "which socat >/dev/null 2>&1 || "
            "(apt-get update -qq && apt-get install -y -qq socat 2>/dev/null || "
            "apk add --no-cache socat 2>/dev/null) || true",
            timeout=30,
        )

        target = f"127.0.0.1:{actual_port}"
        if port_mismatch:
            # 端口不同：安全绑定 0.0.0.0:container_port
            socat_cmd = (
                f"socat TCP-LISTEN:{container_port},fork,reuseaddr "
                f"TCP:{target}"
            )
        else:
            # 端口相同但绑定 127.0.0.1：绑定到容器的非回环 IP
            socat_cmd = (
                f"BIND_IP=$(hostname -i 2>/dev/null | awk '{{print $1}}'); "
                f"socat TCP-LISTEN:{container_port},fork,reuseaddr,bind=$BIND_IP "
                f"TCP:{target}"
            )

        rc, out = sandbox._exec_in_container(f"({socat_cmd}) &", timeout=5)
        if rc == 0:
            logger.info(
                f"[预览] socat 转发: :{container_port} → {target}"
            )
            time.sleep(0.5)
            return True
        else:
            logger.warning(f"[预览] socat 启动失败: {out}")
            return False

    @classmethod
    def _pick_premapped_port(cls, sandbox, excluded_port: int = 0) -> int | None:
        """从沙箱已有的预映射端口中选一个可用的应用端口"""
        mapped_container_ports = {cp for _, cp in sandbox.port_mappings}
        for p in cls._FALLBACK_PORTS:
            if p != excluded_port and p in mapped_container_ports:
                return p
        return None

    @staticmethod
    def _rewrite_port_in_command(command: str, old_port: int, new_port: int) -> str:
        """将命令中的端口号替换为新端口"""
        return command.replace(str(old_port), str(new_port))

    @staticmethod
    def _patch_host_binding(command: str) -> str:
        """Docker 容器内 Node dev server 默认绑定 localhost/::1，需改为 0.0.0.0。

        只对 npm run dev / npx vite 等 Node 命令添加 --host，
        不影响已有 --host 的 Python 命令（如 uvicorn）。
        按长度降序排列，避免 "npm run dev" 误匹配 "npm run dev:frontend"。
        """
        # 降序匹配：优先匹配更长的 token，避免子串误匹配
        for token in ("npm run dev:frontend", "npm run dev:client", "npm run dev", "npx vite"):
            idx = command.find(token)
            if idx == -1:
                continue
            # 确保 token 后不是 ":" 或字母数字（即不是 npm run dev:backend 这类子命令）
            end_idx = idx + len(token)
            if end_idx < len(command) and command[end_idx] in (":", "_"):
                continue
            after = command[end_idx:]
            if "--host" in after.split("&&")[0]:
                continue
            command = command[:end_idx] + " -- --host 0.0.0.0" + command[end_idx:]
            break
        return command

    def _inject_vite_host_config(self, sandbox) -> bool:
        """向容器内 vite.config.ts/js 注入 server.host: '0.0.0.0'。

        Docker 端口转发到达的是容器 eth0，Vite 默认只监听 ::1/127.0.0.1。
        CLI --host 参数在 concurrently/npm workspace 包装下可能被丢弃，
        直接修改配置文件是最稳健的防御手段。
        已有 host 配置时跳过，避免重复注入。
        """
        patch_script = (
            "import re, os, sys\n"
            "dirs = ['frontend', 'client', 'web', 'ui', '']\n"
            "for d in dirs:\n"
            "    for ext in ['ts', 'js', 'mts', 'mjs']:\n"
            "        p = f'/workspace/{d}/vite.config.{ext}' if d else '/workspace/vite.config.' + ext\n"
            "        if not os.path.isfile(p): continue\n"
            "        c = open(p).read()\n"
            "        if 'host:' in c or '0.0.0.0' in c:\n"
            "            print('SKIP:' + p); sys.exit(0)\n"
            "        if 'server:' in c:\n"
            "            c = re.sub(r'(server\\s*:\\s*\\{)', r\"\\1\\n    host: '0.0.0.0',\", c)\n"
            "        else:\n"
            "            c = c.replace('defineConfig({', \"defineConfig({\\n  server: { host: '0.0.0.0' },\")\n"
            "        open(p, 'w').write(c)\n"
            "        print('PATCHED:' + p); sys.exit(0)\n"
            "print('NOT_FOUND')\n"
        )
        try:
            sandbox.execute(
                f"cat > /tmp/_vite_host_patch.py << 'PYEOF'\n{patch_script}\nPYEOF",
                timeout=5,
            )
            result = sandbox.execute("python3 /tmp/_vite_host_patch.py", timeout=10)
            if "PATCHED" in result:
                logger.info(f"[预览] Vite host 配置已注入: {result.strip()}")
                return True
            logger.debug(f"[预览] Vite host 注入结果: {result.strip()}")
        except Exception as e:
            logger.warning(f"[预览] Vite host 注入失败（非致命）: {e}")
        return False

    def _install_deps_if_needed(self):
        """本地安装依赖（通过技术栈适配器确定命令）"""
        try:
            from autoc.stacks._registry import parse_project_context
            ctx = parse_project_context(self.workspace_dir)
            if ctx.install_command:
                logger.info(f"[预览] 安装依赖: {ctx.install_command}")
                subprocess.run(ctx.install_command, shell=True, cwd=self.workspace_dir,
                               capture_output=True, timeout=120)
                return
        except Exception:
            pass
        # 回退：原有逻辑
        pkg_json = os.path.join(self.workspace_dir, "package.json")
        node_modules = os.path.join(self.workspace_dir, "node_modules")
        req_txt = os.path.join(self.workspace_dir, "requirements.txt")
        if os.path.isfile(pkg_json) and not os.path.isdir(node_modules):
            subprocess.run("npm install", shell=True, cwd=self.workspace_dir,
                           capture_output=True, timeout=120)
        if os.path.isfile(req_txt):
            subprocess.run("pip install -r requirements.txt", shell=True,
                           cwd=self.workspace_dir, capture_output=True, timeout=120)

    def _install_deps_in_sandbox(self, sandbox):
        """在 Docker 沙箱内安装依赖（支持 monorepo 子目录）"""
        try:
            from autoc.stacks._registry import parse_project_context
            ctx = parse_project_context(self.workspace_dir)
            if ctx.install_command:
                sandbox.execute(f"{ctx.install_command} 2>&1", timeout=120)
                return
        except Exception:
            pass

        installed_any = False

        # 根目录
        pkg_json = os.path.join(self.workspace_dir, "package.json")
        req_txt = os.path.join(self.workspace_dir, "requirements.txt")
        if os.path.isfile(pkg_json):
            sandbox.execute("npm install 2>&1", timeout=120)
            installed_any = True
        if os.path.isfile(req_txt):
            sandbox.execute("pip install -r requirements.txt 2>&1", timeout=120)
            installed_any = True

        # monorepo 子目录（frontend/backend/client/server 等）
        for subdir in ("frontend", "client", "web", "ui", "backend", "server", "api"):
            sub_path = os.path.join(self.workspace_dir, subdir)
            sub_pkg = os.path.join(sub_path, "package.json")
            sub_req = os.path.join(sub_path, "requirements.txt")
            if os.path.isfile(sub_pkg):
                sandbox.execute(f"cd {subdir} && npm install 2>&1", timeout=120)
                installed_any = True
            if os.path.isfile(sub_req):
                sandbox.execute(f"cd {subdir} && pip install -r requirements.txt 2>&1", timeout=120)
                installed_any = True
            elif os.path.isdir(sub_path):
                pkgs = self._detect_missing_pip_packages(sub_path)
                if pkgs:
                    sandbox.execute(f"pip install {' '.join(pkgs)} 2>&1", timeout=120)
                    installed_any = True

        if not installed_any:
            pkgs = self._detect_missing_pip_packages()
            if pkgs:
                sandbox.execute(f"pip install {' '.join(pkgs)} 2>&1", timeout=120)

    def _detect_missing_pip_packages(self, scan_dir: str = "") -> list[str]:
        """无 requirements.txt 时，从 Python 文件的 import 推断需要安装的第三方包"""
        import re as _re
        import sys
        target_dir = scan_dir or self.workspace_dir
        STDLIB_WHITELIST = getattr(sys, 'stdlib_module_names', set()) | {
            # 兜底：Python < 3.10 的常用模块
            'os', 'sys', 'io', 're', 'json', 'math', 'time', 'datetime',
            'pathlib', 'typing', 'collections', 'functools', 'itertools',
            'asyncio', 'threading', 'multiprocessing', 'subprocess',
            'socket', 'http', 'urllib', 'email', 'html', 'xml',
            'logging', 'unittest', 'argparse', 'configparser',
            'hashlib', 'hmac', 'secrets', 'base64', 'binascii',
            'struct', 'array', 'queue', 'heapq', 'bisect',
            'contextlib', 'abc', 'dataclasses', 'enum', 'warnings',
            'traceback', 'inspect', 'ast', 'dis', 'importlib',
            'pkgutil', 'platform', 'signal', 'gc', 'weakref',
            'copy', 'pprint', 'textwrap', 'string', 'decimal',
            'fractions', 'statistics', 'random', 'operator',
            'codecs', 'unicodedata', 'locale', 'gettext',
            'tempfile', 'shutil', 'glob', 'fnmatch', 'stat',
            'fileinput', 'linecache', 'pickle', 'shelve', 'sqlite3',
            'csv', 'zipfile', 'tarfile', 'gzip', 'bz2', 'lzma',
            'concurrent', 'ctypes', 'types', 'builtins',
            'uuid', 'io', 'math',
        }
        IMPORT_TO_PKG = {
            "flask": "Flask", "flask_sqlalchemy": "Flask-SQLAlchemy",
            "flask_cors": "Flask-CORS", "fastapi": "fastapi",
            "uvicorn": "uvicorn", "sqlalchemy": "SQLAlchemy",
            "requests": "requests", "pydantic": "pydantic",
            "PIL": "Pillow", "cv2": "opencv-python",
            "bs4": "beautifulsoup4", "dotenv": "python-dotenv",
            "yaml": "PyYAML", "jwt": "PyJWT",
        }
        COMPANION_PKGS = {"fastapi": ["uvicorn"]}

        local_modules = {
            os.path.splitext(f)[0] for f in os.listdir(target_dir)
            if f.endswith(".py")
        }

        found = set()
        for fname in os.listdir(target_dir):
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(target_dir, fname)
            try:
                with open(fpath, encoding="utf-8") as _fp:
                    content = _fp.read(4096)
            except OSError:
                continue
            for m in _re.findall(r"^\s*(?:from|import)\s+([\w]+)", content, _re.MULTILINE):
                mod = m.split(".")[0]
                if mod in STDLIB_WHITELIST or mod in local_modules:
                    continue
                pkg = IMPORT_TO_PKG.get(mod, mod)
                found.add(pkg)
                for companion in COMPANION_PKGS.get(mod, []):
                    found.add(companion)
        return sorted(found)

    def _wait_for_port(self, port: int, retries: int = 20, interval: float = 0.5) -> bool:
        for _ in range(retries):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.connect(("127.0.0.1", port))
                    return True
                except (ConnectionRefusedError, OSError):
                    time.sleep(interval)
        return False

    @staticmethod
    def _check_http_reachable(url: str, timeout: float = 3.0) -> bool:
        """验证 URL 是否返回有效 HTTP 响应（排除端口被非 HTTP 服务占用的情况）"""
        import urllib.request
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status < 500
        except Exception:
            return False

    def stop(self):
        """终止本地预览进程"""
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None
        if self._log_file:
            try:
                self._log_file.close()
            except Exception:
                pass
            self._log_file = None
        self._preview_info = None

    def __del__(self):
        # 析构器不保证执行时机，请优先显式调用 stop()
        try:
            self.stop()
        except Exception:
            pass
