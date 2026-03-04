"""技术栈注册表 — 自动扫描 autoc/stacks/ 下所有适配器"""

import importlib
import logging
import os
import pkgutil
from typing import Optional

from autoc.stacks import StackAdapter, ProjectContext

logger = logging.getLogger("autoc.stacks.registry")

_adapters: list[type[StackAdapter]] = []
_initialized = False


def _discover():
    """自动扫描 autoc/stacks/ 下所有模块，注册 StackAdapter 子类"""
    global _adapters, _initialized
    if _initialized:
        return
    package_dir = os.path.dirname(os.path.abspath(__file__))
    for _, module_name, _ in pkgutil.iter_modules([package_dir]):
        if module_name.startswith("_"):
            continue
        try:
            mod = importlib.import_module(f"autoc.stacks.{module_name}")
            for attr_name in dir(mod):
                attr = getattr(mod, attr_name)
                if (isinstance(attr, type)
                        and issubclass(attr, StackAdapter)
                        and attr is not StackAdapter):
                    _adapters.append(attr)
        except Exception as e:
            logger.warning(f"加载技术栈适配器 {module_name} 失败: {e}")
    _adapters.sort(key=lambda a: a.priority())
    _initialized = True


def detect_stack(workspace_dir: str) -> tuple[Optional[StackAdapter], Optional[str]]:
    """探测工作区技术栈，返回 (adapter_instance, manifest_path)"""
    _discover()
    for adapter_cls in _adapters:
        manifest = adapter_cls.detect(workspace_dir)
        if manifest:
            return adapter_cls(), manifest
    return None, None


def parse_project_context(workspace_dir: str) -> ProjectContext:
    """顶层 API：解析项目上下文"""
    adapter, manifest = detect_stack(workspace_dir)
    if adapter and manifest:
        ctx = adapter.parse(manifest, workspace_dir)
    else:
        ctx = ProjectContext()

    ctx.has_dockerfile = os.path.isfile(os.path.join(workspace_dir, "Dockerfile"))
    _parse_env_example(workspace_dir, ctx)
    return ctx


def get_hidden_dirs(workspace_dir: str) -> set[str]:
    """获取当前项目应隐藏的目录集合"""
    adapter, _ = detect_stack(workspace_dir)
    base = {".git", ".svn", ".hg", ".DS_Store"}
    if adapter:
        base |= adapter.hidden_dirs()
    return base


def get_noread_files(workspace_dir: str) -> set[str]:
    """获取 Agent 不应读取的文件名集合"""
    adapter, _ = detect_stack(workspace_dir)
    return adapter.noread_files() if adapter else set()


def get_config_files(workspace_dir: str) -> set[str]:
    """获取配置文件名（read 时追加提醒）"""
    common = {
        "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
        ".env.example", ".env.template",
    }
    adapter, _ = detect_stack(workspace_dir)
    if adapter:
        common |= adapter.config_files()
    return common


def get_coding_guidelines(workspace_dir: str) -> str:
    """获取当前技术栈的编码规范"""
    adapter, _ = detect_stack(workspace_dir)
    return adapter.coding_guidelines() if adapter else ""


def get_testing_guidelines(workspace_dir: str) -> str:
    """获取当前技术栈的测试规范"""
    adapter, _ = detect_stack(workspace_dir)
    return adapter.testing_guidelines() if adapter else ""


def get_test_command(workspace_dir: str) -> str:
    """获取当前技术栈的测试命令，回退到 pytest"""
    adapter, manifest = detect_stack(workspace_dir)
    if adapter and manifest:
        ctx = adapter.parse(manifest, workspace_dir)
        if ctx.test_command:
            return ctx.test_command
    return "python -m pytest tests/ -x --tb=line -q 2>&1"


def get_all_complexity_indicators() -> dict[str, list[str]]:
    """合并所有已注册技术栈的复杂度指标"""
    _discover()
    result: dict[str, list[str]] = {"complex": [], "medium": []}
    for adapter_cls in _adapters:
        indicators = adapter_cls.complexity_indicators()
        result["complex"].extend(indicators.get("complex", []))
        result["medium"].extend(indicators.get("medium", []))
    return result


def _parse_env_example(workspace_dir: str, ctx: ProjectContext):
    for env_file in (".env.example", ".env.template", ".env.sample"):
        env_path = os.path.join(workspace_dir, env_file)
        if os.path.isfile(env_path):
            ctx.has_env_example = True
            try:
                with open(env_path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if "=" in line and not line.startswith("#"):
                            ctx.env_vars.append(line.split("=")[0].strip())
            except OSError:
                pass
            break
