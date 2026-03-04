"""配置、模型、设置、会话列表、系统能力路由"""

import asyncio
import logging
import os
import shutil
import subprocess
import time

from fastapi import Request
from fastapi.responses import JSONResponse

from autoc.server import router, sessions, sessions_lock, registry, _extract_project_name, get_db_queue_stats
from autoc.config import load_config, PROJECT_ROOT, resolve_config_path
from autoc.core.llm import PROVIDERS
from autoc.core.llm.model_config import ModelConfigManager, test_model_connection

logger = logging.getLogger("autoc.web")


# ==================== 系统配置 ====================

@router.get("/config")
async def get_config():
    """获取当前配置信息（首页状态栏使用）"""
    mcm = ModelConfigManager(PROJECT_ROOT)
    active = mcm.get_active()
    has_any = mcm.has_active_config()

    coder_prov = active.get("coder", {}).get("provider", "")
    coder_model = active.get("coder", {}).get("model", "")
    display_name = ""
    if coder_prov:
        prov_info = PROVIDERS.get(coder_prov, {})
        display_name = prov_info.get("name", coder_prov)
        if coder_model:
            display_name += f" / {coder_model}"

    if not has_any:
        cfg = load_config("config/config.yaml")
        display_name = cfg.get("llm", {}).get("preset", "未配置")

    return {
        "display_name": display_name,
        "has_config": has_any,
        "has_api_key": has_any,
        "workspace": load_config("config/config.yaml").get("workspace", {}).get("output_dir", "./workspace"),
    }


# ==================== 模型配置 ====================

@router.get("/providers")
async def get_providers():
    """返回所有服务提供商及其模型列表"""
    result = []
    for pid, prov in PROVIDERS.items():
        result.append({
            "id": pid,
            "name": prov["name"],
            "base_url": prov["base_url"],
            "editable_url": prov["editable_url"],
            "models": prov["models"],
        })
    return result


@router.get("/model-config")
async def get_model_config():
    """获取当前模型配置（用于设置弹窗回显）"""
    mcm = ModelConfigManager(PROJECT_ROOT)
    _sync_cn_mirror_env(mcm)
    return mcm.to_api_response()


@router.put("/model-config")
async def save_model_config(request: Request):
    """保存模型配置（前端已测试通过后调用）"""
    data = await request.json()
    logger.debug(f"收到保存请求 credentials: {list(data.get('credentials', {}).keys())}")
    for pid, cd in data.get("credentials", {}).items():
        logger.debug(f"  provider={pid}, has_key={bool(cd.get('api_key'))}, models={cd.get('models', cd.get('model', '?'))}")
    try:
        mcm = ModelConfigManager(PROJECT_ROOT)

        for agent in ("coder", "critique", "helper"):
            agent_cfg = data.get("active", {}).get(agent, {})
            if agent_cfg.get("provider") and agent_cfg.get("model"):
                mcm.set_active(agent, agent_cfg["provider"], agent_cfg["model"])

        for provider_id, cred_data in data.get("credentials", {}).items():
            api_key = cred_data.get("api_key", "")
            base_url = cred_data.get("base_url", "")
            models = cred_data.get("models", [])
            if not models:
                single = cred_data.get("model", "")
                if single:
                    models = [single]
            models = [m for m in models if m and m != '_placeholder']
            if not api_key:
                api_key = mcm.get_api_key_for_provider(provider_id)
            logger.info(f"[DEBUG]   => provider={provider_id}, resolved_key={bool(api_key)}, models_to_save={models}")
            if api_key:
                if models:
                    for m in models:
                        mcm.save_credential(provider_id, api_key, m, base_url)
                else:
                    mcm.save_credential_key_only(provider_id, api_key, base_url)

        adv = data.get("advanced", {})
        if adv:
            mcm.set_advanced(**adv)

        gs = data.get("general_settings", {})
        if gs:
            mcm.set_general_settings(**gs)

        mcm.save()
        _sync_to_config_yaml(mcm)
        _sync_cn_mirror_env(mcm)

        return {"success": True}
    except Exception as e:
        logger.error(f"保存模型配置失败: {e}")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@router.post("/test-model")
async def test_model_api(request: Request):
    """测试模型连接（api_key 为空时自动使用已保存的凭证）"""
    data = await request.json()
    provider = data.get("provider", "")
    model = data.get("model", "")
    api_key = data.get("api_key", "")
    base_url = data.get("base_url", "")

    if not provider or not model:
        return JSONResponse(status_code=400, content={
            "success": False,
            "error": "provider 和 model 为必填",
        })

    if not api_key:
        mcm = ModelConfigManager(PROJECT_ROOT)
        api_key = mcm.get_api_key_for_provider(provider)
        if not api_key:
            return JSONResponse(status_code=400, content={
                "success": False,
                "error": "API Key 不能为空，且未找到已保存的凭证",
            })
        cred = mcm.get_credential(provider)
        if not base_url and cred.get("base_url"):
            base_url = cred["base_url"]

    result = await asyncio.to_thread(
        test_model_connection, provider, model, api_key, base_url
    )
    return result


def _sync_to_config_yaml(mcm: ModelConfigManager):
    """将 autoc-models.json 的激活配置同步到 config.yaml"""
    import yaml

    config_path = resolve_config_path("config/config.yaml")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}

        coder_active = mcm.get_active().get("coder", {})
        if coder_active.get("provider"):
            cfg.setdefault("llm", {})["preset"] = coder_active["provider"]
            if coder_active.get("model"):
                cfg["llm"]["model"] = coder_active["model"]

        adv = mcm.get_advanced()
        cfg.setdefault("llm", {})
        cfg["llm"]["temperature"] = adv.get("temperature", 0.7)
        cfg["llm"]["max_tokens"] = adv.get("max_tokens", 32768)
        cfg["llm"]["timeout"] = adv.get("timeout", 120)
        cfg.setdefault("orchestrator", {})["max_rounds"] = adv.get("max_rounds", 3)

        for agent in ("coder", "critique", "helper"):
            agent_active = mcm.get_active().get(agent, {})
            if agent_active.get("provider"):
                cfg.setdefault("agents", {}).setdefault(agent, {})
                cfg["agents"][agent]["preset"] = agent_active["provider"]
                if agent_active.get("model"):
                    cfg["agents"][agent]["model"] = agent_active["model"]

        # 原子写入：先写临时文件再 rename，防止写入中断损坏 config.yaml
        import tempfile
        dir_name = os.path.dirname(config_path)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=dir_name, delete=False, suffix=".tmp") as tf:
            yaml.dump(cfg, tf, default_flow_style=False, allow_unicode=True, sort_keys=False)
            tmp_path = tf.name
        os.replace(tmp_path, config_path)
    except Exception as e:
        logger.warning(f"同步 config.yaml 失败: {e}")


def _sync_cn_mirror_env(mcm: ModelConfigManager):
    """将 general_settings.use_cn_mirror 同步到环境变量，使 cn_mirror 模块即时生效"""
    gs = mcm.get_general_settings()
    if gs.get("use_cn_mirror"):
        os.environ["AUTOC_USE_CN_MIRROR"] = "1"
    else:
        os.environ.pop("AUTOC_USE_CN_MIRROR", None)


# ==================== 会话管理 ====================

@router.get("/sessions")
async def list_sessions():
    """列出所有会话（合并文件注册表 + 内存会话，按时间倒序）"""
    file_sessions = {s["session_id"]: s for s in registry.list_all()}
    result = []
    seen = set()

    with sessions_lock:
        sessions_snapshot = list(sessions.items())

    for sid, mem in sessions_snapshot:
        seen.add(sid)
        fs = file_sessions.get(sid, {})
        ws_dir = mem.get("workspace_dir", fs.get("workspace_dir", ""))
        pname = mem.get("project_name") or _extract_project_name(ws_dir)
        result.append({
            "session_id": sid,
            "requirement": mem.get("requirement", fs.get("requirement", "")),
            "project_name": pname,
            "status": mem.get("status", fs.get("status", "running")),
            "started_at": fs.get("started_at", mem.get("started_at", 0)),
            "ended_at": mem.get("ended_at", fs.get("ended_at")),
            "workspace_dir": ws_dir,
            "event_count": len(mem.get("events", [])),
            "source": fs.get("source", "web"),
            "has_events": True,
        })

    for sid, fs in file_sessions.items():
        if sid in seen:
            continue
        ws_dir = fs.get("workspace_dir", "")
        try:
            with registry._db.read() as _conn:
                db_event_count = _conn.execute(
                    "SELECT COUNT(*) FROM session_events WHERE session_id=?", (sid,)
                ).fetchone()[0]
        except Exception:
            db_event_count = 0
        result.append({
            "session_id": sid,
            "requirement": fs.get("requirement", ""),
            "project_name": _extract_project_name(ws_dir),
            "status": fs.get("status", "running"),
            "started_at": fs.get("started_at", 0),
            "ended_at": fs.get("ended_at"),
            "workspace_dir": ws_dir,
            "event_count": db_event_count,
            "source": fs.get("source", "cli"),
            "has_events": db_event_count > 0,
        })

    result.sort(key=lambda x: x["started_at"], reverse=True)
    return result


@router.delete("/sessions")
async def clear_sessions_api(request: Request):
    """清除会话记录"""
    data = await request.json() if (request.headers.get("content-type") or "").startswith("application/json") else {}
    only_finished = data.get("only_finished", True)

    removed = registry.clear(only_finished=only_finished)

    with sessions_lock:
        if only_finished:
            # 仅清理已结束的 session
            cleared_sids = [
                sid for sid, s in sessions.items()
                if s.get("status") != "running"
            ]
        else:
            # 清理所有 session（包括已结束和 running 的）
            cleared_sids = list(sessions.keys())
        for sid in cleared_sids:
            del sessions[sid]

    return {
        "success": True,
        "removed": len(cleared_sids),
        "message": f"已清除 {len(cleared_sids)} 条会话记录",
    }


@router.delete("/sessions/{session_id}")
async def delete_session_api(session_id: str):
    """删除单条会话记录"""
    with sessions_lock:
        mem_session = sessions.get(session_id)
        if mem_session and mem_session.get("status") == "running":
            return JSONResponse(status_code=400, content={"error": "无法删除运行中的会话"})
        removed_from_memory = session_id in sessions
        if removed_from_memory:
            del sessions[session_id]

    removed_from_registry = registry.delete(session_id)

    if not removed_from_registry and not removed_from_memory:
        return JSONResponse(status_code=404, content={"error": "会话不存在"})

    return {"success": True, "message": "会话已删除"}


# ==================== 系统能力 ====================

@router.get("/capabilities")
async def get_capabilities():
    """系统能力概览 — 内置工具 / Docker 沙箱状态"""
    cfg = load_config("config/config.yaml")
    features = cfg.get("features", {})

    # 内置工具（静态计算，与 tool_handlers.py 注册逻辑对齐）
    builtin_tools = [
        {"name": "read_file", "category": "file", "description": "读取文件内容"},
        {"name": "write_file", "category": "file", "description": "写入文件内容"},
        {"name": "create_directory", "category": "file", "description": "创建目录"},
        {"name": "list_files", "category": "file", "description": "列出目录文件"},
        {"name": "search_in_files", "category": "file", "description": "搜索文件内容"},
        {"name": "execute_command", "category": "shell", "description": "执行 Shell 命令（Docker 沙箱内）"},
    ]
    if features.get("git", True):
        builtin_tools.extend([
            {"name": "git_diff", "category": "git", "description": "查看 Git 差异"},
            {"name": "git_log", "category": "git", "description": "查看 Git 日志"},
            {"name": "git_status", "category": "git", "description": "查看 Git 状态"},
        ])
    if features.get("code_quality", True):
        builtin_tools.extend([
            {"name": "format_code", "category": "quality", "description": "格式化代码"},
            {"name": "lint_code", "category": "quality", "description": "代码 Lint 检查"},
        ])

    # Docker 可用性（轻量检测，复用 sandbox_status 逻辑）
    docker_available = shutil.which("docker") is not None
    if docker_available:
        try:
            r = subprocess.run(["docker", "info"], capture_output=True, timeout=5)
            docker_available = r.returncode == 0
        except Exception:
            docker_available = False

    # 就绪度评估
    mcm = ModelConfigManager(PROJECT_ROOT)
    has_model = mcm.has_active_config()
    all_ok = docker_available and has_model

    if all_ok:
        health = "healthy"
    elif has_model:
        health = "degraded"
    else:
        health = "unhealthy"

    return {
        "health": health,
        "tools": {
            "builtin": builtin_tools,
            "builtin_count": len(builtin_tools),
        },
        "docker": {
            "available": docker_available,
            "sandbox_mode": features.get("sandbox_mode", "project"),
        },
        "model_configured": has_model,
        "db_queue": get_db_queue_stats(),
    }
