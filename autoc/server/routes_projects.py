"""项目管理路由：CRUD、恢复执行、快修、修订、里程碑"""

import os
import logging
import subprocess
from datetime import datetime

from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse

from autoc.server import router, sessions, sessions_lock, registry, _start_project_session
from autoc.config import load_config
from autoc.core.project.progress import ProgressTracker
from autoc.core.project import ProjectManager
from autoc.core.project.models import ProjectStatus
from autoc.core.project.manager import slugify_project_name

logger = logging.getLogger("autoc.web")


def _cleanup_project_container(project_name: str):
    """删除项目关联的 Docker 沙箱容器和预览引用"""
    container_name = f"autoc-sandbox-{slugify_project_name(project_name)}"
    try:
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            capture_output=True, text=True, timeout=15,
        )
        logger.info(f"已清理容器: {container_name}")
    except Exception as e:
        logger.debug(f"清理容器 {container_name} 失败（可能不存在）: {e}")

    from autoc.server.routes_preview import _preview_sandboxes, _preview_sandboxes_lock
    with _preview_sandboxes_lock:
        _preview_sandboxes.pop(project_name, None)


def _iso_to_unix(iso_str: str, offset_seconds: float = 0) -> float:
    """ISO 时间戳转 Unix 秒，可选减去偏移量（用于推算开始时间）"""
    if not iso_str:
        return 0
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.timestamp() - offset_seconds
    except Exception:
        return 0


# 各操作允许的项目状态（白名单）
_ALLOWED_STATUSES: dict[str, set[str]] = {
    "resume":      {"incomplete", "aborted", "completed"},
    "quick-fix":   {"incomplete", "aborted"},
    "revise":      {"idle", "incomplete", "aborted", "completed"},
    "redefine":    {"incomplete", "aborted", "completed"},
    "add-feature": {"incomplete", "aborted", "completed"},
}


def _require_status(project_path: str, operation: str) -> JSONResponse | None:
    """校验项目当前状态是否允许执行 operation，同时拒绝并发操作。

    返回 None 表示通过；返回 JSONResponse 表示应直接返回给客户端。
    """
    pm = ProjectManager(project_path)
    meta = pm.load()
    status = meta.status if meta else "idle"

    allowed = _ALLOWED_STATUSES.get(operation, set())
    if status not in allowed:
        active = ProjectStatus.active_statuses()
        if status in {s.value for s in active}:
            msg = f"项目正在执行中（{status}），请等待完成或终止后再操作"
            code = 409
        else:
            msg = f"当前状态 [{status}] 不支持 [{operation}] 操作"
            code = 400
        return JSONResponse(status_code=code, content={"error": msg})

    abs_project = os.path.abspath(project_path)
    with sessions_lock:
        running_sids = [
            sid for sid, s in sessions.items()
            if s.get("status") == "running"
            and os.path.abspath(s.get("workspace_dir", "")) == abs_project
        ]
    if running_sids:
        return JSONResponse(status_code=409, content={
            "error": "项目存在运行中的会话，请等待完成后再操作",
            "running_sessions": running_sids,
        })

    return None


def _find_project_path(project_name: str) -> str:
    """查找项目路径，找不到则抛出 404"""
    cfg = load_config("config/config.yaml")
    workspace_root = cfg.get("workspace", {}).get("output_dir", "./workspace")
    project_path = ProjectManager.find_project_by_name(project_name, workspace_root)
    if not project_path:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project_path


# ==================== 项目 CRUD ====================

@router.get("/projects")
async def list_all_projects(detail: bool = False):
    """列出所有项目，detail=true 时附带每个项目的任务列表"""
    cfg = load_config("config/config.yaml")
    workspace_root = cfg.get("workspace", {}).get("output_dir", "./workspace")
    projects = ProjectManager.list_all_projects(workspace_root)

    if detail:
        for proj in projects:
            pt = ProgressTracker(proj["path"])
            tasks = pt.load_tasks()
            proj["tasks_detail"] = [
                {"id": t.get("id"), "title": t.get("title"), "passes": t.get("passes", False)}
                for t in tasks
            ]

    return projects


@router.get("/projects/{project_name}")
async def get_project_info(project_name: str):
    """获取项目详情"""
    project_path = _find_project_path(project_name)

    pm = ProjectManager(project_path)
    metadata = pm.load()
    if not metadata:
        raise HTTPException(status_code=404, detail="无法加载项目元数据")

    pt = ProgressTracker(project_path)
    tasks = pt.load_tasks()
    dev_sessions = pm._load_sessions_raw()

    SKIP_EXTS = {".db", ".db-shm", ".db-wal", ".pyc"}
    SKIP_NAMES = {
        ".autoc.db", "autoc-progress.txt", "autoc-tasks.json", "project-plan.json",
        ".gitignore", ".DS_Store",
    }
    SKIP_DIRS = {"__pycache__", "node_modules", ".autoc"}
    workspace_files = []
    try:
        for root, dirs, files_in_dir in os.walk(project_path):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
            for fname in files_in_dir:
                if fname in SKIP_NAMES:
                    continue
                if os.path.splitext(fname)[1] in SKIP_EXTS:
                    continue
                abs_path = os.path.join(root, fname)
                rel_path = os.path.relpath(abs_path, project_path)
                workspace_files.append(rel_path)
    except Exception:
        pass

    ai_assist_stats = None
    try:
        ai_assist_stats = pm.get_ai_assist_stats()
    except Exception:
        pass

    plan_md = ""
    plan_file = os.path.join(project_path, "PLAN.md")
    if os.path.isfile(plan_file):
        try:
            with open(plan_file, "r", encoding="utf-8") as f:
                plan_md = f.read().strip()
        except Exception:
            pass

    folder = os.path.basename(project_path)

    return {
        "metadata": {
            "name": metadata.name,
            "folder": folder,
            "description": metadata.description,
            "status": metadata.status,
            "version": metadata.version,
            "created_at": metadata.created_at,
            "updated_at": metadata.updated_at,
            "tech_stack": metadata.tech_stack,
            "total_tasks": metadata.total_tasks,
            "completed_tasks": metadata.completed_tasks,
            "verified_tasks": metadata.verified_tasks,
            "total_tokens": getattr(metadata, "total_tokens", 0),
            "ai_assist_tokens": getattr(metadata, "ai_assist_tokens", 0),
            "git_enabled": metadata.git_enabled,
            "use_project_venv": metadata.use_project_venv,
            "single_task": metadata.single_task,
            "milestones": metadata.milestones,
        },
        "tasks": tasks,
        "dev_sessions": dev_sessions,
        "ai_assist_stats": ai_assist_stats,
        "project_plan": None,
        "plan_md": plan_md,
        "workspace_files": workspace_files,
        "pending_tasks": pm.get_pending_tasks(),
    }


@router.get("/projects/{project_name}/versions")
async def get_project_versions(project_name: str):
    """获取项目版本快照列表（时序区数据源），无快照时从现有数据构造 fallback"""
    project_path = _find_project_path(project_name)
    pm = ProjectManager(project_path)
    try:
        snapshots = pm.get_version_snapshots()
    except Exception:
        snapshots = []

    if not snapshots:
        try:
            metadata = pm.load()
            pt = ProgressTracker(project_path)
            tasks = pt.load_tasks()
            sessions = pm._load_sessions_raw()
            if metadata and (tasks or sessions):
                total_tokens = sum(s.get("total_tokens", 0) for s in sessions)
                elapsed = sum(s.get("elapsed_seconds", 0) for s in sessions)
                verified = sum(1 for t in tasks if t.get("passes"))
                snapshots = [{
                    "version": metadata.version or "1.0.0",
                    "requirement_type": "primary",
                    "requirement": metadata.description or "",
                    "tech_stack": metadata.tech_stack or [],
                    "tasks": [{"id": t.get("id", ""), "title": t.get("title", ""),
                               "status": t.get("status", ""), "passes": bool(t.get("passes"))}
                              for t in tasks],
                    "bugs_fixed": [],
                    "success": verified == len(tasks) and len(tasks) > 0,
                    "total_tokens": total_tokens,
                    "elapsed_seconds": elapsed,
                    "started_at": _iso_to_unix(sessions[0].get("timestamp", ""), elapsed) if sessions else 0,
                    "ended_at": _iso_to_unix(sessions[0].get("timestamp", "")) if sessions else 0,
                    "session_count": len(sessions),
                    "created_at": metadata.created_at or "",
                }]
        except Exception:
            pass

    return {"versions": snapshots}


@router.post("/projects")
async def init_project_api(request: Request):
    """初始化新项目"""
    from autoc.core.project import validate_project_name

    data = await request.json()
    name = data.get("name", "").strip()
    folder = data.get("folder", "").strip() or name
    description = data.get("description", "")
    tech_stack = data.get("tech_stack", [])
    git_enabled = data.get("git_enabled", True)
    single_task = bool(data.get("single_task", False))

    if not name:
        return JSONResponse(status_code=400, content={"error": "项目名称不能为空"})
    if not validate_project_name(folder):
        return JSONResponse(
            status_code=400,
            content={"error": "文件夹名不合法，请使用字母、数字、下划线或连字符"},
        )

    cfg = load_config("config/config.yaml")
    workspace_root = cfg.get("workspace", {}).get("output_dir", "./workspace")
    project_path = os.path.abspath(os.path.join(workspace_root, folder))

    pm = ProjectManager(project_path)
    if pm.exists():
        return JSONResponse(status_code=409, content={"error": f"项目已存在: {name}"})

    try:
        metadata = pm.init(
            name=name,
            description=description or "",
            tech_stack=tech_stack or [],
            git_enabled=git_enabled,
            use_project_venv=False,
            single_task=single_task,
        )

        return {
            "success": True,
            "project": {
                "name": metadata.name,
                "folder": folder,
                "description": metadata.description,
                "path": metadata.project_path,
                "tech_stack": metadata.tech_stack,
                "git_enabled": metadata.git_enabled,
                "use_project_venv": metadata.use_project_venv,
                "single_task": metadata.single_task,
            },
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.patch("/projects/{project_name}")
async def update_project_api(project_name: str, request: Request):
    """编辑项目元数据（描述、技术栈）"""
    data = await request.json()
    project_path = _find_project_path(project_name)

    pm = ProjectManager(project_path)
    metadata = pm.load()
    if not metadata:
        raise HTTPException(status_code=404, detail="项目元数据不存在")

    old_name = metadata.name
    if "name" in data:
        new_name = data["name"].strip()
        if new_name:
            metadata.name = new_name
    if "description" in data:
        metadata.description = data["description"]
    if "tech_stack" in data:
        metadata.tech_stack = data["tech_stack"]
    if "git_enabled" in data:
        metadata.git_enabled = bool(data["git_enabled"])
    if "single_task" in data:
        metadata.single_task = bool(data["single_task"])

    metadata.updated_at = datetime.now().isoformat()
    pm.save(metadata)

    folder = os.path.basename(project_path)
    return {"success": True, "message": "项目已更新", "name": metadata.name, "folder": folder, "old_name": old_name}


@router.delete("/projects/{project_name}")
async def delete_project_api(project_name: str, request: Request):
    """删除项目（级联删除关联的所有会话记录）"""
    try:
        data = await request.json()
    except Exception:
        data = {}
    keep_files = data.get("keep_files", False)
    force = data.get("force", False)

    project_path = _find_project_path(project_name)

    # 阻止删除正在执行的项目（除非 force=True）
    if not force:
        abs_project = os.path.abspath(project_path)
        with sessions_lock:
            running_sids = [
                sid for sid, s in sessions.items()
                if s.get("status") == "running"
                and os.path.abspath(s.get("workspace_dir", "")) == abs_project
            ]
        if running_sids:
            return JSONResponse(status_code=409, content={
                "error": f"项目正在执行中（会话: {', '.join(running_sids)}），请先停止执行再删除",
                "running_sessions": running_sids,
            })

    pm = ProjectManager(project_path)
    metadata = pm.load()
    display_name = metadata.name if metadata else project_name

    _cleanup_project_container(project_name)

    removed_sids = registry.delete_by_workspace(project_path)
    with sessions_lock:
        for sid in removed_sids:
            sessions.pop(sid, None)

    if pm.delete(remove_files=not keep_files):
        return {
            "success": True,
            "message": f"项目已删除: {display_name}",
            "removed_sessions": len(removed_sids),
        }
    return JSONResponse(status_code=500, content={"error": "删除失败"})


@router.post("/projects/batch-delete")
async def batch_delete_projects_api(request: Request):
    """批量删除项目"""
    data = await request.json()
    names = data.get("names", [])
    if not names:
        raise HTTPException(status_code=400, detail="请提供要删除的项目名称列表")

    keep_files = data.get("keep_files", False)
    force = data.get("force", False)

    results = {"deleted": [], "failed": [], "skipped": []}

    for name in names:
        try:
            project_path = _find_project_path(name)
        except HTTPException:
            results["failed"].append({"name": name, "reason": "项目不存在"})
            continue

        if not force:
            abs_project = os.path.abspath(project_path)
            with sessions_lock:
                running_sids = [
                    sid for sid, s in sessions.items()
                    if s.get("status") == "running"
                    and os.path.abspath(s.get("workspace_dir", "")) == abs_project
                ]
            if running_sids:
                results["skipped"].append({"name": name, "reason": "项目正在执行中"})
                continue

        _cleanup_project_container(name)

        pm = ProjectManager(project_path)
        removed_sids = registry.delete_by_workspace(project_path)
        with sessions_lock:
            for sid in removed_sids:
                sessions.pop(sid, None)

        if pm.delete(remove_files=not keep_files):
            results["deleted"].append(name)
        else:
            results["failed"].append({"name": name, "reason": "删除失败"})

    return {
        "success": True,
        "deleted_count": len(results["deleted"]),
        **results,
    }


# ==================== 项目操作 ====================



@router.post("/projects/{project_name}/milestone")
async def add_milestone_api(project_name: str, request: Request):
    """为项目添加里程碑"""
    data = await request.json()
    title = data.get("title", "").strip()
    description = data.get("description", "")
    version = data.get("version", "")

    if not title:
        return JSONResponse(status_code=400, content={"error": "里程碑标题不能为空"})

    project_path = _find_project_path(project_name)

    pm = ProjectManager(project_path)
    pm.add_milestone(title, description, version)

    return {"success": True, "message": f"里程碑已添加: {title}"}


# ==================== 异步操作（恢复/重测/快修/修订） ====================

@router.post("/projects/{project_name}/resume")
async def resume_project_api(project_name: str):
    """从上次中断处恢复执行（跳过 PM，已有代码直接测试，未完成任务走 Dev→Test）"""
    project_path = _find_project_path(project_name)
    if err := _require_status(project_path, "resume"):
        return err

    def _task(orc):
        result = orc.resume()
        return {
            "success": result.get("success", False),
            **{k: result[k] for k in (
                "tasks_completed", "tasks_total",
                "elapsed_seconds", "total_tokens", "files",
            ) if k in result},
        }

    sid = _start_project_session(project_path, "resume", _task)
    return {"session_id": sid, "message": f"恢复执行已启动: {project_name}"}


@router.post("/projects/{project_name}/quick-fix")
async def quick_fix_bugs_api(project_name: str, request: Request):
    """快速修复指定 bug（不重跑完整测试循环）"""
    project_path = _find_project_path(project_name)
    if err := _require_status(project_path, "quick-fix"):
        return err

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    bug_ids = body.get("bug_ids")
    bug_titles = body.get("bug_titles")
    bugs_data = body.get("bugs")

    def _task(orc):
        result = orc.quick_fix_bugs(bug_ids=bug_ids, bug_titles=bug_titles, bugs_data=bugs_data)
        return {
            "success": result.get("success", False),
            "fixed": result.get("fixed", 0),
            "total": result.get("total", 0),
            "files": result.get("files", []),
        }

    sid = _start_project_session(project_path, "quick-fix", _task)
    return {"session_id": sid, "message": f"快速修复已启动: {project_name}"}


@router.post("/projects/{project_name}/revise")
async def revise_project_api(project_name: str, request: Request):
    """调整项目需求并重新执行（Git 回滚 + 任务重置 + Token 累计保留）"""
    project_path = _find_project_path(project_name)
    if err := _require_status(project_path, "revise"):
        return err

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    new_requirement = body.get("requirement", "").strip()
    if not new_requirement:
        return JSONResponse(status_code=400, content={"error": "需求内容不能为空"})
    clean_workspace = body.get("clean_workspace", True)

    def _task(orc):
        result = orc.redefine_project(new_requirement) if clean_workspace else orc.add_feature(new_requirement)
        return {
            "success": result.get("success", False),
            **{k: result[k] for k in (
                "tasks_completed", "tasks_total", "tasks_verified",
                "tests_passed", "tests_total", "bugs_open",
                "total_tokens", "elapsed_seconds", "files",
            ) if k in result},
        }

    sid = _start_project_session(
        project_path, "revise", _task,
        requirement=f"[revise] {new_requirement}",
    )
    return {"session_id": sid, "message": f"项目调整已启动: {project_name}"}


@router.post("/projects/{project_name}/redefine")
async def redefine_project_api(project_name: str, request: Request):
    """主需求变更：归档当前迭代 → 清空 → major bump → 全量重来"""
    project_path = _find_project_path(project_name)
    if err := _require_status(project_path, "redefine"):
        return err

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    new_requirement = body.get("requirement", "").strip()
    if not new_requirement:
        return JSONResponse(status_code=400, content={"error": "需求内容不能为空"})

    def _task(orc):
        result = orc.redefine_project(new_requirement)
        return {
            "success": result.get("success", False),
            **{k: result[k] for k in (
                "tasks_completed", "tasks_total", "tasks_verified",
                "tests_passed", "tests_total", "bugs_open",
                "total_tokens", "elapsed_seconds", "files",
            ) if k in result},
        }

    sid = _start_project_session(
        project_path, "redefine", _task,
        requirement=new_requirement,
    )
    return {"session_id": sid, "message": f"主需求变更已启动: {project_name}"}


@router.post("/projects/{project_name}/add-feature")
async def add_feature_api(project_name: str, request: Request):
    """次级需求：保留已有代码 → 增量规划 → append → minor bump"""
    project_path = _find_project_path(project_name)
    if err := _require_status(project_path, "add-feature"):
        return err

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    feature = body.get("requirement", body.get("feature", "")).strip()
    if not feature:
        return JSONResponse(status_code=400, content={"error": "功能描述不能为空"})

    def _task(orc):
        result = orc.add_feature(feature)
        return {
            "success": result.get("success", False),
            **{k: result[k] for k in (
                "tasks_completed", "tasks_total", "tasks_verified",
                "tests_passed", "tests_total", "bugs_open",
                "total_tokens", "elapsed_seconds", "files",
            ) if k in result},
        }

    sid = _start_project_session(
        project_path, "add-feature", _task,
        requirement=f"[add-feature] {feature}",
    )
    return {"session_id": sid, "message": f"追加功能已启动: {project_name}"}


# ==================== 文件读写 ====================

@router.put("/projects/{project_name}/file")
async def write_project_file(project_name: str, request: Request):
    """写入项目工作区内的单个文件（路径越界自动拒绝）"""
    project_path = _find_project_path(project_name)

    data = await request.json()
    rel_path: str = data.get("path", "").strip()
    content: str = data.get("content", "")

    if not rel_path:
        return JSONResponse(status_code=400, content={"error": "path 不能为空"})

    # 安全校验：确保目标路径在项目目录内，禁止路径穿越（含 symlink 防御）
    abs_project = os.path.realpath(project_path)
    abs_target = os.path.realpath(os.path.join(abs_project, rel_path))
    if not abs_target.startswith(abs_project + os.sep) and abs_target != abs_project:
        return JSONResponse(status_code=403, content={"error": "路径越界，拒绝写入"})

    # 禁止写入 AutoC 内部文件
    basename = os.path.basename(rel_path)
    PROTECTED = {"autoc.db", ".autoc.db", "autoc-progress.txt", "autoc-tasks.json", "project-plan.json"}
    if basename in PROTECTED or rel_path.startswith(".autoc"):
        return JSONResponse(status_code=403, content={"error": "禁止修改 AutoC 内部文件"})

    try:
        os.makedirs(os.path.dirname(abs_target), exist_ok=True)
        with open(abs_target, "w", encoding="utf-8") as f:
            f.write(content)
        return {"success": True, "path": rel_path, "bytes": len(content.encode())}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
