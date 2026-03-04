"""VenvManager — Python 虚拟环境生命周期管理

策略：
  - 默认使用全局共享 venv (~/.autoc/venv/)，所有项目共用，避免冗余
  - 项目创建时可通过 use_project_venv=True 启用独立 .venv，写入元数据后续自动沿用
  - ShellExecutor 通过 get_env() / get_pip() 使用正确的 Python 路径
  - 始终用 python3 -m venv 创建 venv，规避 pyenv 版本不匹配问题
"""

import logging
import os
import subprocess
import sys

logger = logging.getLogger("autoc.venv_manager")

# 全局共享 venv 的默认位置
GLOBAL_VENV_DIR = os.path.expanduser("~/.autoc/venv")


class VenvManager:
    """Python 虚拟环境管理器

    用法:
        # 全局 venv（默认）
        vm = VenvManager(workspace_dir)
        vm.ensure_ready()
        env = vm.get_env()   # 注入了 venv 的环境变量，传给 subprocess

        # 项目独立 venv
        vm = VenvManager(workspace_dir, use_project_venv=True)
        vm.ensure_ready()
    """

    def __init__(self, workspace_dir: str, use_project_venv: bool = False,
                 global_venv_path: str = ""):
        self.workspace_dir = os.path.abspath(workspace_dir)
        self.use_project_venv = use_project_venv
        self._project_venv = os.path.join(self.workspace_dir, ".venv")
        self._global_venv = global_venv_path or GLOBAL_VENV_DIR

    @property
    def venv_dir(self) -> str:
        """返回当前应使用的 venv 目录（优先级：项目 .venv > 全局 venv）"""
        if self.use_project_venv:
            # 项目 venv 优先，但若尚未创建则暂时回退全局
            if os.path.isdir(self._project_venv):
                return self._project_venv
        return self._global_venv

    @property
    def venv_bin(self) -> str:
        return os.path.join(self.venv_dir, "bin")

    def ensure_ready(self) -> bool:
        """确保目标 venv 存在且可用，不存在或损坏时自动重建。

        Returns:
            True 表示 venv 就绪，False 表示创建失败（会降级到系统 Python）
        """
        target = self._project_venv if self.use_project_venv else self._global_venv
        if os.path.isdir(target) and self._is_valid(target):
            logger.debug(f"venv 已就绪: {target}")
            return True

        logger.info(f"正在创建 Python venv: {target}")
        return self._create_venv(target)

    def get_env(self) -> dict:
        """返回注入了 venv 的环境变量字典，供 subprocess 使用。

        - 将 venv/bin 加到 PATH 最前面，覆盖 pyenv shim
        - 设置 VIRTUAL_ENV 供工具识别
        - 移除 PYENV_VERSION 避免干扰
        """
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        venv = self.venv_dir

        if os.path.isdir(venv):
            env["PATH"] = self.venv_bin + os.pathsep + env.get("PATH", "")
            env["VIRTUAL_ENV"] = venv
            env.pop("PYENV_VERSION", None)
        else:
            # venv 不存在时的 fallback：尝试找到系统 python3 目录
            logger.warning(f"venv 目录不存在: {venv}，尝试回退到系统 python3")
            self._inject_system_python3(env)

        return env

    def get_python(self) -> str:
        """返回 venv 中 python 可执行文件的绝对路径"""
        candidate = os.path.join(self.venv_bin, "python3")
        if os.path.isfile(candidate):
            return candidate
        return os.path.join(self.venv_bin, "python")

    def get_pip(self) -> str:
        """返回 venv 中 pip 可执行文件的绝对路径"""
        candidate = os.path.join(self.venv_bin, "pip3")
        if os.path.isfile(candidate):
            return candidate
        return os.path.join(self.venv_bin, "pip")

    def summary(self) -> str:
        """返回当前 venv 配置摘要，用于日志和 UI 展示"""
        mode = "项目独立 venv" if self.use_project_venv else "全局共享 venv"
        return f"{mode} → {self.venv_dir}"

    # ==================== 内部方法 ====================

    def _create_venv(self, path: str) -> bool:
        """用 python3 -m venv 创建虚拟环境，规避 pyenv 版本问题"""
        os.makedirs(os.path.dirname(path), exist_ok=True)

        # 找到一个可用的 python3（跳过 pyenv shim）
        python3 = self._find_system_python3()
        if not python3:
            logger.error("未找到可用的 python3，无法创建 venv")
            return False

        try:
            result = subprocess.run(
                [python3, "-m", "venv", path],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode == 0:
                logger.info(f"venv 创建成功: {path}（使用 {python3}）")
                # 升级 pip 避免旧版本问题
                self._upgrade_pip(path)
                return True
            else:
                logger.error(f"venv 创建失败 (code={result.returncode}): {result.stderr[:300]}")
                return False
        except subprocess.TimeoutExpired:
            logger.error("venv 创建超时")
            return False
        except Exception as e:
            logger.error(f"venv 创建异常: {e}")
            return False

    def _upgrade_pip(self, venv_path: str):
        """在新创建的 venv 中升级 pip"""
        pip = os.path.join(venv_path, "bin", "pip3")
        if not os.path.isfile(pip):
            pip = os.path.join(venv_path, "bin", "pip")
        try:
            subprocess.run(
                [pip, "install", "--upgrade", "pip", "-q"],
                capture_output=True, text=True, timeout=60,
            )
        except Exception:
            pass  # pip 升级失败不阻断流程

    def _is_valid(self, venv_path: str) -> bool:
        """检查 venv 是否有效（bin/python3 或 bin/python 存在且可执行）"""
        for name in ("python3", "python"):
            candidate = os.path.join(venv_path, "bin", name)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return True
        return False

    @staticmethod
    def _find_system_python3() -> str:
        """找到一个真正可用的 python3（跳过 pyenv shim 指向不存在版本的情况）"""
        import shutil

        # 优先检查 pyenv 是否配置了有效版本
        pyenv_root = os.environ.get("PYENV_ROOT", os.path.expanduser("~/.pyenv"))
        for version_file in (
            os.path.expanduser("~/.python-version"),
        ):
            if os.path.exists(version_file):
                try:
                    with open(version_file) as f:
                        ver = f.read().strip()
                    ver_python = os.path.join(pyenv_root, "versions", ver, "bin", "python3")
                    if os.path.isfile(ver_python):
                        return ver_python
                except OSError:
                    pass
                break  # 只检查一次

        # 在常见目录中直接查找 python3（绕过 pyenv shim）
        search_dirs = [
            "/opt/homebrew/bin",          # macOS Apple Silicon Homebrew
            "/usr/local/bin",             # macOS Intel Homebrew / Linux
            "/usr/bin",                   # 系统 Python
        ]
        for directory in search_dirs:
            for name in ("python3.13", "python3.12", "python3.11", "python3.10", "python3"):
                candidate = os.path.join(directory, name)
                if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                    return candidate

        # 最后回退：shutil.which（可能仍是 pyenv shim，但聊胜于无）
        found = shutil.which("python3") or shutil.which("python")
        return found or ""

    @staticmethod
    def _inject_system_python3(env: dict):
        """当 venv 不可用时，将系统 python3 目录注入 PATH 前面"""
        search_dirs = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"]
        for directory in search_dirs:
            for name in ("python3.13", "python3.12", "python3.11", "python3.10", "python3"):
                if os.path.isfile(os.path.join(directory, name)):
                    env["PATH"] = directory + os.pathsep + env.get("PATH", "")
                    env.pop("PYENV_VERSION", None)
                    return
