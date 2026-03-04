"""Docker 沙箱执行器 - 参考 OpenHands 的安全隔离设计

提供两种执行模式:
1. Docker 沙箱模式 (推荐): 命令在 Docker 容器内执行，完全隔离
2. 本地模式 (回退): 与原有 ShellExecutor 行为一致

设计理念:
- 参考 OpenHands/OpenDevin 的 Docker Sandbox 设计
- 命令在隔离容器中执行，宿主机不受影响
- 工作区目录挂载到容器内，支持文件读写
- 自动管理容器生命周期
- 端口映射支持 Web 应用预览
- 后台进程支持 dev server 等长运行服务
"""

import logging
import os
import re
import shlex
import shutil
import subprocess
import time
from typing import Optional

logger = logging.getLogger("autoc.tools.sandbox")

DEFAULT_SANDBOX_IMAGE = "nikolaik/python-nodejs:python3.12-nodejs22"


class DockerSandbox:
    """
    Docker 沙箱执行环境 — 一项目一容器模型

    容器生命周期与项目绑定（而非 session）：
    - 首次执行时创建，后续 session（resume/retry/fix）复用同一容器
    - 容器内安装的依赖、数据库状态在 session 间保留
    - 仅在用户启动新需求或显式调用 destroy() 时才销毁重建
    - Orchestrator 对象销毁时只断开引用，不销毁容器
    """

    def __init__(
        self,
        workspace_dir: str,
        image: str = DEFAULT_SANDBOX_IMAGE,
        container_name: str = "",
        network: str = "bridge",
        memory_limit: str = "2g",
        cpu_limit: float = 2.0,
        port_mappings: list[tuple[int, int]] | None = None,
        sandbox_mode: str = "project",
        project_name: str = "",
    ):
        self.workspace_dir = os.path.abspath(workspace_dir)
        self.image = image
        self.sandbox_mode = sandbox_mode
        self.project_name = project_name
        if container_name:
            self.container_name = container_name
        elif project_name:
            from autoc.core.project.manager import slugify_project_name
            self.container_name = f"autoc-sandbox-{slugify_project_name(project_name)}"
        else:
            self.container_name = "autoc-sandbox"
        self.network = network
        self.memory_limit = memory_limit
        self.cpu_limit = cpu_limit
        self.port_mappings = port_mappings or []
        self._container_id: Optional[str] = None
        self._available: Optional[bool] = None
        self._bg_pids: list[str] = []
        self._bg_logs: dict[str, str] = {}  # PID → 日志文件路径
        self._missing_tools: list[str] = []
        self._action_client = None  # ActionClient（持久 bash 通道）

    def add_port_mapping(self, host_port: int, container_port: int):
        """添加端口映射。如果容器已有该映射则跳过。容器已运行时不可添加新映射（安全策略）。"""
        for hp, cp in self.port_mappings:
            if cp == container_port:
                logger.info(f"端口 {container_port} 已映射到 {hp}，跳过")
                return
        if self._container_id:
            raise RuntimeError(
                f"容器已运行，无法添加新端口映射 {host_port}→{container_port}。"
                "沙箱容器仅能随项目删除时重建。请使用预映射端口（3000/5000/8000/8080）或删除项目后重新创建。"
            )
        self.port_mappings.append((host_port, container_port))

    @property
    def is_available(self) -> bool:
        """检查 Docker 是否可用"""
        if self._available is None:
            self._available = shutil.which("docker") is not None
            if self._available:
                try:
                    result = subprocess.run(
                        ["docker", "info"],
                        capture_output=True, text=True, timeout=10,
                    )
                    self._available = result.returncode == 0
                except Exception:
                    self._available = False

            if not self._available:
                logger.warning("Docker 不可用")
            else:
                logger.info(f"Docker 沙箱已就绪，镜像: {self.image}")
        return self._available

    @property
    def status(self) -> str:
        """沙箱运行状态：running / stopped / no_container / unavailable"""
        if not self.is_available:
            return "unavailable"
        if not self._container_id:
            return "no_container"
        try:
            result = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Status}}", self._container_id],
                capture_output=True, text=True, timeout=5,
            )
            return result.stdout.strip() if result.returncode == 0 else "unknown"
        except Exception:
            return "unknown"

    def health_check(self) -> dict:
        """综合健康检查：返回容器状态、资源使用、端口可达性"""
        info: dict = {"status": self.status, "container_id": self._container_id, "image": self.image}
        if self._container_id and self.status == "running":
            try:
                result = subprocess.run(
                    ["docker", "exec", self._container_id, "echo", "ok"],
                    capture_output=True, text=True, timeout=5,
                )
                info["exec_ok"] = result.returncode == 0
            except Exception:
                info["exec_ok"] = False
            info["port_mappings"] = [(h, c) for h, c in self.port_mappings]
        return info

    def _image_exists(self) -> bool:
        """检查本地是否已有所需镜像"""
        try:
            r = subprocess.run(
                ["docker", "image", "inspect", self.image],
                capture_output=True, text=True, timeout=10,
            )
            return r.returncode == 0
        except Exception:
            return False

    def _pull_image(self) -> bool:
        """拉取 Docker 镜像，返回是否成功"""
        logger.info(f"本地未找到镜像 {self.image}，正在自动拉取...")
        try:
            r = subprocess.run(
                ["docker", "pull", self.image],
                capture_output=True, text=True, timeout=300,
            )
            if r.returncode == 0:
                logger.info(f"镜像 {self.image} 拉取成功")
                return True
            logger.error(f"镜像拉取失败: {r.stderr.strip()}")
            return False
        except subprocess.TimeoutExpired:
            logger.error(f"镜像拉取超时 (300s): {self.image}")
            return False
        except Exception as e:
            logger.error(f"镜像拉取异常: {e}")
            return False

    def ensure_ready(self, on_progress=None) -> None:
        """确保 Docker 沙箱完全可用（Docker 守护进程 + 镜像就绪）。

        Args:
            on_progress: 可选回调 (step, message, percent) 用于报告进度

        不可用时直接抛 RuntimeError，禁止回退到本地模式。
        """
        _cb = on_progress or (lambda *_: None)

        _cb("docker_check", "检查 Docker 环境...", 10)
        if not self.is_available:
            raise RuntimeError(
                "Docker 不可用，无法启动沙箱。"
                "请确保 Docker Desktop 已启动且 `docker info` 正常。"
            )
        _cb("docker_ok", "Docker 环境正常", 30)

        _cb("image_check", f"检查镜像 {self.image}...", 40)
        if not self._image_exists():
            _cb("image_pull", f"正在拉取镜像 {self.image}（首次可能需要几分钟）...", 50)
            if not self._pull_image():
                raise RuntimeError(
                    f"Docker 镜像 {self.image} 不存在且自动拉取失败。"
                    f"请手动执行: docker pull {self.image}"
                )
            _cb("image_ready", "镜像就绪", 80)
        else:
            _cb("image_ready", "镜像已存在", 80)

        _cb("sandbox_ready", "沙箱环境准备完成", 100)

    # 预映射端口（容器侧）：Web 框架 + 数据库 + 缓存常用端口
    @staticmethod
    def _common_ports() -> list[int]:
        from autoc.tools.schemas import ACTION_SERVER_DEFAULT_PORT
        return [
            3000, 4200, 5000, 5173, 8000, 8080, 8888,  # Web 框架
            5432, 3306, 27017, 6379,                      # PostgreSQL/MySQL/MongoDB/Redis
            ACTION_SERVER_DEFAULT_PORT,                    # Action Server
        ]

    def _ensure_container(self):
        """确保容器正在运行，优先复用同名已有容器。安全策略：不删除已有容器，仅随项目删除时清理。"""
        # 1) 当前引用还活着？
        if self._container_id:
            result = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Running}}", self._container_id],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and "true" in result.stdout.lower():
                return

        # 2) 同名容器是否已存在？复用或启动（不删除）
        reused = self._try_reuse_existing()
        if reused:
            return

        # 3) 容器不存在，创建新的（不执行 rm -f）
        self._create_container()

    def _try_reuse_existing(self) -> bool:
        """尝试复用同名已有容器（运行中或已停止），返回是否成功。

        镜像匹配时直接复用；镜像不匹配时销毁旧容器并返回 False，
        由调用方 _create_container 用新镜像重建（工作区数据在 volume mount 上不受影响）。
        """
        result = subprocess.run(
            ["docker", "inspect", "-f",
             "{{.State.Running}} {{.Id}} {{.Config.Image}}",
             self.container_name],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return False

        parts = result.stdout.strip().split()
        if len(parts) < 3:
            return False

        is_running = parts[0].lower() == "true"
        container_id = parts[1][:12]
        container_image = parts[2]

        if container_image != self.image:
            logger.warning(
                f"容器镜像已变更 ({container_image} → {self.image})，"
                "销毁旧容器并重建"
            )
            try:
                subprocess.run(
                    ["docker", "rm", "-f", self.container_name],
                    capture_output=True, text=True, timeout=15,
                )
            except Exception as e:
                logger.warning(f"销毁旧容器失败: {e}")
            return False

        if not is_running:
            r = subprocess.run(
                ["docker", "start", self.container_name],
                capture_output=True, text=True, timeout=15,
            )
            if r.returncode != 0:
                raise RuntimeError(f"启动已停止容器失败: {r.stderr.strip()}")

        self._container_id = container_id
        self._sync_port_mappings()
        logger.info(f"复用已有容器: {self.container_name} ({container_id})")
        return True

    def _sync_port_mappings(self):
        """从运行中容器同步端口映射，与构造参数合并（容器实际映射优先）"""
        result = subprocess.run(
            ["docker", "port", self.container_name],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return
        existing: dict[int, int] = {}
        for line in result.stdout.strip().splitlines():
            try:
                container_part, host_part = line.split(" -> ")
                container_port = int(container_part.split("/")[0])
                host_port = int(host_part.split(":")[-1])
                existing[container_port] = host_port
            except (ValueError, IndexError):
                continue
        # 构造参数中的端口如果容器里已有则用容器的映射，否则保留（需要 add_port_mapping 后续处理）
        merged: dict[int, int] = {}
        for hp, cp in self.port_mappings:
            if cp in existing:
                merged[cp] = existing[cp]
            else:
                merged[cp] = hp
        for cp, hp in existing.items():
            if cp not in merged:
                merged[cp] = hp
        self.port_mappings = sorted((hp, cp) for cp, hp in merged.items())

    def _create_container(self):
        """创建新容器，预映射常见端口"""
        from autoc.core.runtime.preview import find_free_port

        pre_mapped: list[tuple[int, int]] = list(self.port_mappings)
        pre_mapped_container_ports = {cp for _, cp in pre_mapped}
        for cp in self._common_ports():
            if cp not in pre_mapped_container_ports:
                try:
                    hp = find_free_port()
                    pre_mapped.append((hp, cp))
                except Exception:
                    pass
        self.port_mappings = pre_mapped

        cmd = [
            "docker", "run", "-d",
            "--name", self.container_name,
            "-v", f"{self.workspace_dir}:/workspace",
            "-w", "/workspace",
            "--memory", self.memory_limit,
            f"--cpus={self.cpu_limit}",
            "--network", self.network,
        ]

        for host_port, container_port in self.port_mappings:
            # 绑定到 127.0.0.1，防止端口暴露到所有网络接口
            cmd.extend(["-p", f"127.0.0.1:{host_port}:{container_port}"])

        cmd.extend([
            "--security-opt", "no-new-privileges",
            "--cap-drop", "ALL",
            "--cap-add", "CHOWN",
            "--cap-add", "DAC_OVERRIDE",
            "--cap-add", "FOWNER",
            "--cap-add", "SETGID",
            "--cap-add", "SETUID",
            "--cap-add", "NET_BIND_SERVICE",
            self.image,
            "tail", "-f", "/dev/null",
        ])

        logger.info(f"创建 Docker 沙箱容器: {self.image}")
        if self.port_mappings:
            ports_str = ", ".join(f"{h}→{c}" for h, c in self.port_mappings)
            logger.info(f"端口映射: {ports_str}")

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        if result.returncode != 0:
            raise RuntimeError(f"启动 Docker 容器失败: {result.stderr}")

        self._container_id = result.stdout.strip()[:12]
        logger.info(f"沙箱容器已启动: {self._container_id}")

        self._install_base_tools()

        from autoc.core.infra.cn_mirror import use_cn_mirror
        if use_cn_mirror():
            self._configure_cn_mirrors()

        self._start_action_server()

    _REQUIRED_PACKAGES = "git curl"
    _OPTIONAL_PACKAGES = "procps psmisc"
    _INSTALL_MAX_RETRIES = 2

    def _install_base_tools(self):
        """安装基础工具，带重试和验证。

        必需工具（git/curl）安装失败会重试；
        可选工具（procps）仅尝试一次，失败仅警告不阻塞。
        安装失败的工具名记录到 self._missing_tools，供 Agent 层感知。
        """
        self._missing_tools = []

        all_packages = f"{self._REQUIRED_PACKAGES} {self._OPTIONAL_PACKAGES}"
        required_set = set(self._REQUIRED_PACKAGES.split())

        # 快速检查：如果工具已存在（预构建镜像），直接跳过
        needed = []
        for tool in all_packages.split():
            rc, _ = self._exec_in_container(f"which {tool}", timeout=5)
            if rc != 0:
                needed.append(tool)
        if not needed:
            logger.info("基础工具已就绪（跳过 apt-get）")
            return

        needed_required = [t for t in needed if t in required_set]
        needed_optional = [t for t in needed if t not in required_set]

        # 先安装必需工具（带重试）
        apt_updated = False
        if needed_required:
            self._apt_install_with_retry(needed_required)
            apt_updated = True

        # 再安装可选工具（仅一次，失败仅警告）
        if needed_optional:
            self._apt_install_optional(needed_optional, apt_updated=apt_updated)

        # 最终检查
        for tool in all_packages.split():
            rc, _ = self._exec_in_container(f"which {tool}", timeout=5)
            if rc != 0:
                self._missing_tools.append(tool)
                if tool in required_set:
                    logger.error(f"必需工具不可用: {tool}")
                else:
                    logger.info(f"可选工具不可用（不影响功能）: {tool}")

        if self._missing_tools:
            required_missing = [t for t in self._missing_tools if t in required_set]
            if required_missing:
                logger.error(f"必需工具安装失败: {required_missing}")
            else:
                logger.info("必需工具全部就绪，可选工具部分缺失（不影响功能）")

    def _apt_install_with_retry(self, packages: list[str]):
        """安装必需包，带重试"""
        pkgs = " ".join(packages)
        for attempt in range(1, self._INSTALL_MAX_RETRIES + 1):
            rc_update, out_update = self._exec_in_container(
                "apt-get update -qq 2>&1", timeout=60,
            )
            if rc_update != 0:
                self._exec_in_container(
                    "kill -9 $(pgrep -f '[a]pt-get') 2>/dev/null; "
                    "rm -f /var/lib/dpkg/lock-frontend /var/lib/dpkg/lock "
                    "/var/lib/apt/lists/lock /var/cache/apt/archives/lock 2>/dev/null",
                    timeout=10,
                )
                logger.warning(
                    f"apt-get update 失败 (第 {attempt} 次): {out_update[-300:]}"
                )
                time.sleep(2 * attempt)
                continue

            rc_install, out_install = self._exec_in_container(
                f"DEBIAN_FRONTEND=noninteractive apt-get install -y -qq {pkgs} 2>&1",
                timeout=90,
            )
            if rc_install != 0:
                self._exec_in_container(
                    "kill -9 $(pgrep -f '[a]pt-get') 2>/dev/null; "
                    "rm -f /var/lib/dpkg/lock-frontend /var/lib/dpkg/lock "
                    "/var/lib/apt/lists/lock /var/cache/apt/archives/lock 2>/dev/null",
                    timeout=10,
                )
                logger.warning(
                    f"apt-get install 失败 (第 {attempt} 次): {out_install[-300:]}"
                )
                time.sleep(2 * attempt)
                continue

            missing = [t for t in packages
                       if self._exec_in_container(f"which {t}", timeout=5)[0] != 0]
            if not missing:
                logger.info(f"必需工具安装成功 (第 {attempt} 次)")
                return

            logger.warning(f"安装后验证失败 (第 {attempt} 次)，缺失: {missing}")
            time.sleep(2 * attempt)

    def _apt_install_optional(self, packages: list[str],
                              apt_updated: bool = False):
        """安装可选包，仅一次尝试，失败仅警告"""
        if not apt_updated:
            self._exec_in_container("apt-get update -qq 2>&1", timeout=30)
        pkgs = " ".join(packages)
        rc, out = self._exec_in_container(
            f"DEBIAN_FRONTEND=noninteractive apt-get install -y -qq {pkgs} 2>&1",
            timeout=30,
        )
        if rc != 0:
            logger.info(f"可选工具 {packages} 安装跳过（不影响核心功能）")

    @property
    def missing_tools(self) -> list[str]:
        """返回安装失败的工具列表（空列表表示全部就绪）"""
        return list(self._missing_tools)

    def _configure_cn_mirrors(self):
        """配置容器内 pip/npm 使用中国镜像源，加速依赖安装"""
        from autoc.core.infra.cn_mirror import PIP_INDEX_URL, PIP_TRUSTED_HOST, NPM_REGISTRY, GO_PROXY

        configured = []

        # pip（检查容器内是否有 pip）
        rc, _ = self._exec_in_container("which pip 2>/dev/null", timeout=5)
        if rc == 0:
            self._exec_in_container(
                f'mkdir -p /etc/pip && printf "[global]\\nindex-url = {PIP_INDEX_URL}\\ntrusted-host = {PIP_TRUSTED_HOST}\\n" > /etc/pip/pip.conf',
                timeout=10,
            )
            configured.append("pip")

        # npm（检查容器内是否有 npm）
        rc, _ = self._exec_in_container("which npm 2>/dev/null", timeout=5)
        if rc == 0:
            self._exec_in_container(
                f'echo "registry={NPM_REGISTRY}" > /root/.npmrc',
                timeout=10,
            )
            configured.append("npm")

        # go（检查容器内是否有 go）
        rc, _ = self._exec_in_container("which go 2>/dev/null", timeout=5)
        if rc == 0:
            self._exec_in_container(
                f"go env -w GOPROXY={GO_PROXY}",
                timeout=10,
            )
            configured.append("go")

        if configured:
            logger.info(f"已配置中国区镜像源: {', '.join(configured)}")

    # ── Action Execution Server（容器内持久 bash） ──

    def _start_action_server(self):
        """注入并启动容器内的 Action Server，建立持久 bash 通道"""
        from autoc.tools.schemas import ACTION_SERVER_DEFAULT_PORT

        if not self._container_id:
            return

        import importlib.resources
        import tempfile
        try:
            server_src = importlib.resources.files("autoc.core.runtime").joinpath("action_server.py")
            server_code = server_src.read_text(encoding="utf-8")
        except Exception as e:
            logger.debug(f"读取 action_server.py 失败: {e}")
            return

        # 用 docker cp 注入（比 tee 更安全，不回显内容到 stdout）
        tmp_file = None
        try:
            tmp_file = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False)
            tmp_file.write(server_code)
            tmp_file.close()
            proc = subprocess.run(
                ["docker", "cp", tmp_file.name, f"{self._container_id}:/tmp/action_server.py"],
                capture_output=True, timeout=10,
            )
            if proc.returncode != 0:
                logger.warning(f"注入 action_server.py 失败: {proc.stderr[:200]}")
                return
        except Exception as e:
            logger.warning(f"注入 action_server.py 异常: {e}")
            return
        finally:
            if tmp_file:
                try:
                    os.remove(tmp_file.name)
                except OSError:
                    pass

        port = ACTION_SERVER_DEFAULT_PORT
        try:
            subprocess.run(
                ["docker", "exec", "-d", self._container_id,
                 "python3", "/tmp/action_server.py", "--port", str(port)],
                capture_output=True, timeout=10,
            )
        except Exception as e:
            logger.warning(f"启动 Action Server 失败: {e}")
            return

        from autoc.core.runtime.action_client import ActionClient
        host_port = port
        for hp, cp in self.port_mappings:
            if cp == port:
                host_port = hp
                break

        client = ActionClient(host="127.0.0.1", port=host_port)
        if client.wait_until_ready(max_wait=15):
            self._action_client = client
            logger.info(f"Action Server 已启动 (port={host_port})")
        else:
            logger.warning("Action Server 未在 15s 内就绪，降级为 docker exec 模式")

    @property
    def action_client(self):
        """返回 ActionClient 实例（未启用时返回 None）"""
        return self._action_client

    _EXEC_MAX_RETRIES = 3
    _EXEC_RETRY_KEYWORDS = (
        "resource temporarily unavailable",
        "device or resource busy",
        "text file busy",
        "cannot allocate memory",
        "no space left on device",
        "too many open files",
        "interrupted system call",
        "operation timed out",
    )

    def _exec_in_container(self, command: str, timeout: int = 60) -> tuple[int, str]:
        """在容器中执行命令（优先使用 Action Server，降级为 docker exec）"""
        if not self._container_id:
            return -1, "[错误] 未连接到容器"

        # 持久 bash 通道：cd/export 等状态自动保持
        if self._action_client:
            try:
                return self._action_client.execute(command, timeout=timeout)
            except Exception as e:
                logger.debug(f"Action Server 调用失败，降级 docker exec: {e}")

        cmd = [
            "docker", "exec",
            "-w", "/workspace",
            self._container_id,
            "bash", "-c", command,
        ]
        last_output = ""
        for attempt in range(self._EXEC_MAX_RETRIES):
            proc = None
            try:
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                )
                try:
                    stdout, stderr = proc.communicate(timeout=timeout)
                except subprocess.TimeoutExpired:
                    # 超时后主动杀掉 docker exec 子进程，防止容器内进程僵留
                    proc.kill()
                    try:
                        proc.communicate(timeout=5)
                    except Exception:
                        pass
                    # 尝试清理容器内可能残留的进程
                    try:
                        _kill_pattern = re.escape(command[:40])
                        subprocess.run(
                            ["docker", "exec", self._container_id, "bash", "-c",
                             f"pkill -f {shlex.quote(_kill_pattern)} 2>/dev/null || true"],
                            capture_output=True, timeout=5,
                        )
                    except Exception:
                        pass
                    return -1, f"[超时] 命令执行超过 {timeout} 秒"

                output = ""
                if stdout:
                    output += stdout
                if stderr:
                    output += f"\n[stderr]\n{stderr}" if output else stderr
                last_output = output.strip()

                if proc.returncode != 0 and any(
                    kw in last_output.lower() for kw in self._EXEC_RETRY_KEYWORDS
                ):
                    import time as _time
                    delay = (2 ** attempt)
                    logger.warning(
                        f"Bash session busy (attempt {attempt + 1}/{self._EXEC_MAX_RETRIES})，"
                        f"{delay}s 后重试"
                    )
                    _time.sleep(delay)
                    continue

                return proc.returncode, last_output
            except Exception as e:
                if proc is not None:
                    try:
                        proc.kill()
                        proc.communicate(timeout=2)
                    except Exception:
                        pass
                logger.debug(f"_exec_in_container 异常 (attempt {attempt + 1}): {e}")
                last_output = str(e)
        return -1, f"[重试耗尽] 命令执行失败: {last_output[:200]}"

    def execute(self, command: str, timeout: int = 60) -> str:
        """在 Docker 沙箱内执行命令"""
        try:
            self._ensure_container()
        except Exception as e:
            logger.error(f"沙箱容器启动失败: {e}")
            return f"[沙箱错误] 容器启动失败: {e}"

        logger.debug(f"[沙箱] 执行命令: {command}")
        returncode, output = self._exec_in_container(command, timeout=timeout)

        if returncode != 0 and returncode != -1:
            output = f"[退出码: {returncode}]\n{output}"

        if len(output) > 10000:
            output = output[:5000] + "\n\n... (输出过长，已截断) ...\n\n" + output[-3000:]

        return output if output else "(无输出)"

    _SETUP_SCRIPT_PATHS = (".autoc/setup.sh", ".openhands/setup.sh", "setup.sh")
    _setup_done: bool = False

    def run_setup_script(self, timeout: int = 120) -> str | None:
        """检测并执行项目初始化脚本（.autoc/setup.sh 等），仅首次调用执行"""
        if self._setup_done:
            return None
        self._setup_done = True

        for script_path in self._SETUP_SCRIPT_PATHS:
            returncode, check = self._exec_in_container(f"test -f {script_path} && echo EXISTS", timeout=5)
            if "EXISTS" in check:
                logger.info(f"发现项目初始化脚本: {script_path}，开始执行...")
                returncode, output = self._exec_in_container(
                    f"chmod +x {script_path} && bash {script_path}", timeout=timeout,
                )
                if returncode == 0:
                    logger.info(f"项目初始化脚本执行成功: {script_path}")
                else:
                    logger.warning(f"项目初始化脚本执行失败 (exit={returncode}): {output[:200]}")
                return output
        return None

    def execute_background(self, command: str) -> str:
        """在容器内启动后台进程（如 dev server），不阻塞。

        Returns:
            容器内进程的 PID（字符串），或错误信息。
        """
        try:
            self._ensure_container()
        except Exception as e:
            return f"[沙箱错误] 容器启动失败: {e}"

        # 每个后台进程使用独立日志文件（按时间戳命名），避免多个进程覆盖同一日志
        # 格式：PID:LOG_PATH（两字段以冒号分隔输出，便于解析）
        bg_cmd = (
            f"_LOG=/tmp/bg_autoc_$(date +%s%N).log; "
            f"nohup bash -c {shlex.quote(command)} > \"$_LOG\" 2>&1 & "
            f"_PID=$!; echo \"$_PID:$_LOG\""
        )
        logger.info(f"[沙箱] 启动后台进程: {command}")
        returncode, output = self._exec_in_container(bg_cmd, timeout=10)

        if returncode == 0 and ":" in output.strip():
            parts = output.strip().split(":", 1)
            pid = parts[0].strip()
            log_path = parts[1].strip() if len(parts) > 1 else "/tmp/bg_autoc_unknown.log"
            if pid.isdigit():
                self._bg_pids.append(pid)
                self._bg_logs[pid] = log_path
                logger.info(f"[沙箱] 后台进程已启动, PID={pid}, log={log_path}")
                return pid

        return f"[错误] 启动后台进程失败: {output}"

    def check_port_ready(self, port: int, retries: int = 15, interval: float = 1.0) -> bool:
        """轮询检测容器内端口是否就绪（同时检查 IPv4 和 IPv6）"""
        check_cmd = (
            f"bash -c 'echo > /dev/tcp/127.0.0.1/{port} 2>/dev/null "
            f"|| echo > /dev/tcp/::1/{port} 2>/dev/null "
            f"|| echo > /dev/tcp/0.0.0.0/{port} 2>/dev/null'"
        )
        for i in range(retries):
            rc, _ = self._exec_in_container(check_cmd, timeout=3)
            if rc == 0:
                logger.info(f"[沙箱] 端口 {port} 已就绪 (第 {i+1} 次检测)")
                return True
            time.sleep(interval)
        logger.warning(f"[沙箱] 端口 {port} 在 {retries} 次检测后仍未就绪")
        return False

    def get_background_log(self, tail: int = 50, pid: str = "") -> str:
        """获取后台进程的日志输出。

        Args:
            tail: 读取的尾部行数
            pid: 可选，指定 PID 读取对应日志；不传则读取最新后台进程的日志
        """
        if pid and pid in self._bg_logs:
            log_path = self._bg_logs[pid]
        elif self._bg_pids:
            # 读取最近启动的后台进程日志
            latest_pid = self._bg_pids[-1]
            log_path = self._bg_logs.get(latest_pid, "/tmp/bg_server.log")
        else:
            log_path = "/tmp/bg_server.log"
        _, output = self._exec_in_container(f"tail -n {tail} {log_path} 2>/dev/null")
        return output

    def stop_background_processes(self):
        """终止所有已跟踪的后台进程（仅当前 session 内启动的）"""
        if self._container_id and self._bg_pids:
            for pid in self._bg_pids:
                self._exec_in_container(f"kill {pid} 2>/dev/null || true", timeout=5)
        self._bg_pids.clear()
        self._bg_logs.clear()

    def kill_user_processes(self):
        """终止容器内所有用户启动的进程（保留 tail -f /dev/null 守护进程和 Action Server）"""
        if not self._container_id:
            return
        # 逐进程检查，跳过 action_server，避免误杀持久 bash 通道
        self._exec_in_container(
            "for pid in $(pgrep -f 'python|flask|uvicorn|node|npm' 2>/dev/null); do "
            "  cmd=$(cat /proc/$pid/cmdline 2>/dev/null | tr '\\0' ' '); "
            "  echo \"$cmd\" | grep -q 'action_server' || kill $pid 2>/dev/null; "
            "done; true",
            timeout=5,
        )
        self._bg_pids.clear()

    def install_requirements(self, requirements_file: str = "requirements.txt") -> str:
        """安装项目依赖"""
        return self.execute(f"pip install -r {requirements_file} 2>&1", timeout=120)

    def detach(self):
        """断开与容器的引用，不杀进程、不销毁容器。

        容器和其中的进程（包括预览 server）继续运行，
        供后续 session 的 _try_reuse_existing 复用。

        注意：保留 port_mappings，确保 destroy() 在 detach 后仍能正确释放端口文件锁。
        """
        if self._container_id:
            logger.info(f"断开容器引用: {self._container_id}（容器及进程保留运行）")
        self._container_id = None
        self._bg_pids.clear()
        self._bg_logs.clear()
        # port_mappings 故意保留：destroy() 需要它来 release_port_lock

    def destroy(self):
        """显式销毁容器（仅在启动新需求或用户手动清理时调用）。

        先按 _container_id 删，如果没有则按 container_name 删，
        确保即使 detach 后仍能正确清理。同时释放端口文件锁。
        """
        self.stop_background_processes()
        # 释放端口文件锁
        try:
            from autoc.core.runtime.preview import release_port_lock
            for host_port, _ in self.port_mappings:
                release_port_lock(host_port)
        except Exception:
            pass

        target = self._container_id or self.container_name
        try:
            subprocess.run(
                ["docker", "rm", "-f", target],
                capture_output=True, text=True, timeout=10,
            )
            logger.info(f"沙箱容器已销毁: {target}")
        except Exception as e:
            logger.warning(f"销毁容器失败: {e}")
        self._container_id = None

    def __del__(self):
        try:
            self.detach()
        except Exception:
            pass
