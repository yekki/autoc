"""Application Factory — 统一的 Orchestrator 构建入口

Web Server 通过此模块构建 Orchestrator。

用法:
    from autoc.app import build_orchestrator
    orchestrator = build_orchestrator(config, ...)
"""

import os
import logging

from autoc.config import PROJECT_ROOT
from autoc.tools.sandbox import DEFAULT_SANDBOX_IMAGE

logger = logging.getLogger("autoc.app")


def _resolve_llm_config(config: dict):
    """
    从 config/models.json (ModelConfigManager) 解析 LLM 配置。

    Returns:
        (LLMConfig, bool) — LLM 配置对象 和 是否成功
    """
    from autoc.core.llm.model_config import ModelConfigManager

    mcm = ModelConfigManager(PROJECT_ROOT)

    coder_llm = mcm.build_llm_config_for_agent("coder")
    if not coder_llm or not coder_llm.api_key:
        return None, False

    llm_config = coder_llm
    for agent_name in ("coder", "critique", "helper", "planner"):
        agent_llm = mcm.build_llm_config_for_agent(agent_name)
        if agent_llm:
            config.setdefault("agents", {}).setdefault(agent_name, {})
            config["agents"][agent_name]["preset"] = agent_llm.preset
            config["agents"][agent_name]["model"] = agent_llm.model
            if agent_llm.api_key != llm_config.api_key:
                config["agents"][agent_name]["api_key"] = agent_llm.api_key
            if agent_llm.base_url != llm_config.base_url:
                config["agents"][agent_name]["base_url"] = agent_llm.base_url

    adv = mcm.get_advanced()
    config.setdefault("orchestrator", {})["max_rounds"] = adv.get("max_rounds", 3)
    return llm_config, True


def build_orchestrator(
    config: dict,
    project_path: str | None = None,
    session_registry=None,
    session_id: str = "",
    on_event=None,
):
    """根据配置构建编排器 (Application Factory)

    所有命令强制在 Docker 沙箱内执行。

    Args:
        config: 从 config.yaml 加载的配置字典
        project_path: 工作区路径
        session_registry: 会话注册表实例
        session_id: 会话 ID
        on_event: 事件回调（Web SSE 使用）

    Returns:
        Orchestrator 实例

    Raises:
        autoc.exceptions.ConfigError: API Key 缺失时抛出
    """
    from autoc.core.orchestrator import Orchestrator
    from autoc.exceptions import ConfigError

    llm_config, ok = _resolve_llm_config(config)

    if not ok or llm_config is None:
        raise ConfigError(
            "未设置 API Key",
            detail="请在 Web 界面右上角设置按钮中配置模型和 API Key",
        )

    orchestrator_config = config.get("orchestrator", {})
    workspace_config = config.get("workspace", {})
    features_config = config.get("features", {})

    workspace_dir = project_path or workspace_config.get("output_dir", "./workspace")

    # 从 models.json 读取 general_settings（enable_critique 等运行时开关）
    from autoc.core.llm.model_config import ModelConfigManager
    from autoc.config import PROJECT_ROOT
    mcm = ModelConfigManager(PROJECT_ROOT)
    gs = mcm.get_general_settings()

    orc = Orchestrator(
        llm_config=llm_config,
        workspace_dir=workspace_dir,
        max_rounds=orchestrator_config.get("max_rounds", 3),
        auto_fix=orchestrator_config.get("auto_fix", True),
        agent_configs=config.get("agents", {}),
        on_event=on_event,
        enable_checkpoint=orchestrator_config.get("enable_checkpoint", False),
        checkpoint_dir=orchestrator_config.get("checkpoint_dir", ".autoc_state"),
        context_limit=orchestrator_config.get("context_limit", 60000),
        enable_git=features_config.get("git", True),
        sandbox_image=features_config.get("sandbox_image", DEFAULT_SANDBOX_IMAGE),
        enable_experience=features_config.get("experience", True),
        experience_dir=features_config.get("experience_dir", ".autoc_experience"),
        enable_code_quality=features_config.get("code_quality", True),
        enable_parallel=features_config.get("parallel", True),
        max_parallel_tasks=features_config.get("max_parallel_tasks", 3),
        enable_progress_tracking=features_config.get("progress_tracking", True),
        single_task_mode=features_config.get("single_task", False),
        session_registry=session_registry,
        session_id=session_id,
        refiner_config=config.get("refiner", {}),
        preview_config=config.get("preview", {}),
        use_project_venv=False,
        global_venv_path="",
        enable_critique=gs.get("enable_critique", False),
        enable_plan_approval=features_config.get("plan_approval", False),
    )

    return orc


def resolve_workspace_dir(
    config: dict,
    project_name: str = "",
    project_path: str | None = None,
) -> str:
    """根据配置和参数解析实际工作区路径

    Args:
        config: 配置字典
        project_name: 项目名称（多项目模式）
        project_path: 直接指定的项目路径（增量开发）

    Returns:
        绝对路径字符串
    """
    if project_path:
        return os.path.abspath(project_path)

    workspace_cfg = config.get("workspace", {})
    workspace_root = workspace_cfg.get("output_dir", "./workspace")
    isolation_mode = workspace_cfg.get("isolation_mode", "multi")

    if isolation_mode == "multi":
        if project_name:
            from autoc.core.project import ProjectManager
            # 先查找已有项目的真实路径（display name 与文件夹名可能不同）
            existing_path = ProjectManager.find_project_by_name(project_name, workspace_root)
            if existing_path:
                return existing_path
            # 未找到则视为新项目，用 slug 化名称作为文件夹名（避免中文路径）
            from autoc.core.project.manager import slugify_project_name
            folder = slugify_project_name(project_name)
            return os.path.join(workspace_root, folder)
        else:
            from autoc.core.project import generate_project_name
            default_template = workspace_cfg.get(
                "default_project_name", "project-{date}-{random}"
            )
            auto_name = generate_project_name(default_template)
            return os.path.join(workspace_root, auto_name)
    else:
        return workspace_root
