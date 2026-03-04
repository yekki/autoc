"""AutoC 配置加载与基础设施

提供日志配置、配置文件解析等基础设施函数。
Web Server (server.py) 使用这些函数。

注意: Orchestrator 构建逻辑已迁移到 autoc/app.py (Application Factory)。
"""

import os
import sys
import logging
from pathlib import Path

import yaml
from rich.console import Console

console = Console()

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def setup_logging(level: str = "INFO", log_file: str | None = None):
    """配置日志系统"""
    log_level = getattr(logging, level.upper(), logging.INFO)

    handlers = [logging.StreamHandler(sys.stderr)]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
    )

    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("markdown_it").setLevel(logging.WARNING)


def resolve_config_path(config_path: str) -> str:
    """将配置文件路径解析为绝对路径，默认相对于项目根目录"""
    p = Path(config_path)
    if p.is_absolute():
        return str(p)
    candidate = PROJECT_ROOT / p
    if candidate.exists():
        return str(candidate)
    return config_path


def _deep_merge(base: dict, override: dict) -> dict:
    """深度合并两个 dict（override 优先）"""
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def load_config(config_path: str = "config/config.yaml",
                workspace_dir: str = "") -> dict:
    """加载配置文件，并合并项目级 .autoc-project.yaml

    参考 Ralph 的 .ralphrc 设计：
    - 全局 config/config.yaml 提供默认值
    - 项目目录下 .autoc-project.yaml 可覆盖部分配置
    - 优先级: .autoc-project.yaml > config/config.yaml
    """
    resolved = resolve_config_path(config_path)
    if not os.path.exists(resolved):
        console.print(f"[yellow]配置文件不存在: {resolved}，使用默认配置[/yellow]")
        config = {}
    else:
        with open(resolved, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

    # 合并项目级配置
    project_config = load_project_config(workspace_dir)
    if project_config:
        config = _deep_merge(config, project_config)
        logging.getLogger("autoc.config").info("已合并项目级配置 .autoc-project.yaml")

    return config


def load_project_config(workspace_dir: str = "") -> dict:
    """加载项目级 .autoc-project.yaml（类似 Ralph 的 .ralphrc）

    搜索路径:
    1. workspace_dir/.autoc-project.yaml
    2. 当前工作目录/.autoc-project.yaml
    """
    candidates = []
    if workspace_dir:
        candidates.append(Path(workspace_dir) / ".autoc-project.yaml")
    candidates.append(Path.cwd() / ".autoc-project.yaml")

    for p in candidates:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                logging.getLogger("autoc.config").info(f"已加载项目配置: {p}")
                return data
            except Exception as e:
                logging.getLogger("autoc.config").warning(f"项目配置解析失败 ({p}): {e}")
    return {}


