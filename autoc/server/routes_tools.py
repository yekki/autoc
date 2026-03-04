"""工具路由：部署生成、文档生成、经验洞察、PRD 导入、快捷/修复模式"""

import asyncio
import logging
import os
import tempfile

from fastapi import Request
from fastapi.responses import JSONResponse

from autoc.server import router, _start_project_session, _find_project_path_safe
from autoc.config import load_config, PROJECT_ROOT

logger = logging.getLogger("autoc.web")


# ==================== 部署生成 ====================

@router.post("/projects/{project_name}/deploy")
async def deploy_project_api(project_name: str, request: Request):
    """一键生成部署文件 (Dockerfile / docker-compose / 平台配置)"""
    project_path = _find_project_path_safe(project_name)
    if not project_path:
        return JSONResponse(status_code=404, content={"error": "项目不存在"})

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    platform = body.get("platform", "docker")
    port = body.get("port", 8000)
    name = body.get("name", project_name)

    if platform not in ("docker", "vercel", "railway"):
        return JSONResponse(status_code=400, content={"error": "不支持的部署平台"})

    from autoc.core.runtime.deploy import export_deploy_files
    try:
        created = export_deploy_files(project_path, project_name=name,
                                      platform=platform, port=port)
        return {
            "success": True,
            "files": created,
            "platform": platform,
            "message": f"已生成 {len(created)} 个部署文件" if created else "所有部署文件已存在",
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# ==================== 文档生成 ====================

@router.post("/projects/{project_name}/docs")
async def generate_docs_api(project_name: str):
    """自动生成项目文档 (README + API 文档)"""
    project_path = _find_project_path_safe(project_name)
    if not project_path:
        return JSONResponse(status_code=404, content={"error": "项目不存在"})

    from autoc.core.doc_generator import generate_readme, generate_and_save
    try:
        readme_path = generate_and_save(project_path)
        if readme_path:
            with open(readme_path, "r", encoding="utf-8") as f:
                content = f.read()
            return {
                "success": True,
                "path": "README.md",
                "content": content,
                "message": "文档已生成",
            }
        else:
            existing_path = os.path.join(project_path, "README.md")
            content = ""
            if os.path.exists(existing_path):
                with open(existing_path, "r", encoding="utf-8") as f:
                    content = f.read()
            return {
                "success": True,
                "path": "README.md",
                "content": content,
                "message": "已有手写 README.md，跳过自动生成",
                "skipped": True,
            }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# ==================== 经验洞察 ====================

@router.get("/insights")
async def get_insights(requirement: str = ""):
    """查看历史经验洞察和技术栈推荐"""
    from autoc.core.analysis.experience import ExperienceStore

    store = ExperienceStore()

    if requirement:
        experiences = store.get_relevant_experiences(requirement, top_k=5)
        recommendation = store.get_tech_recommendation(requirement)
    else:
        experiences = store.get_relevant_experiences("", top_k=10)
        recommendation = ""

    avg_tokens = store.get_avg_tokens_for_type(requirement or "")

    return {
        "experiences": experiences,
        "recommendation": recommendation,
        "avg_tokens": avg_tokens,
        "total_count": len(experiences),
    }


# ==================== PRD 导入 ====================

@router.post("/import-prd")
async def import_prd_api(request: Request):
    """从 PRD 内容导入并创建项目（接受 JSON body 中的文本内容）"""
    data = await request.json()
    content = data.get("content", "").strip()
    filename = data.get("filename", "prd.md")
    project_name = data.get("project_name", "")

    if not content:
        return JSONResponse(status_code=400, content={"error": "内容不能为空"})

    try:
        from autoc.core.project.prd_import import import_prd, detect_format, build_import_prompt
        from autoc.core.llm import LLMClient, LLMConfig
        from autoc.app import _resolve_llm_config

        cfg = load_config("config/config.yaml")
        llm_config, ok = _resolve_llm_config(cfg)
        if not ok or llm_config is None:
            return JSONResponse(status_code=400, content={
                "error": "未配置 LLM，请先在设置中配置模型",
            })

        # 写入临时文件供 import_prd 使用
        ext = os.path.splitext(filename)[1] or ".md"
        with tempfile.NamedTemporaryFile(mode="w", suffix=ext, delete=False, encoding="utf-8") as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            llm = LLMClient(llm_config)
            plan_data = await asyncio.to_thread(
                import_prd, tmp_path, llm, project_name=project_name,
            )
        finally:
            os.unlink(tmp_path)

        pname = plan_data.get("project_name", project_name or "imported-project")
        tasks = plan_data.get("tasks", [])
        tech_stack = plan_data.get("tech_stack", [])
        description = plan_data.get("description", "")

        # 创建项目
        from autoc.core.project.manager import slugify_project_name
        workspace_root = cfg.get("workspace", {}).get("output_dir", "./workspace")
        folder = slugify_project_name(pname)
        project_path = os.path.abspath(os.path.join(workspace_root, folder))
        os.makedirs(project_path, exist_ok=True)

        from autoc.core.project import ProjectManager
        from autoc.core.project.progress import ProgressTracker

        pm = ProjectManager(project_path)
        if not pm.exists():
            pm.init(name=pname, description=description, tech_stack=tech_stack)

        tracker = ProgressTracker(project_path)
        tracker.save_tasks(tasks)

        from autoc.core.project.state import StateManager
        state_mgr = StateManager(project_path)
        state_mgr.import_from_tasks(
            tasks, project_name=pname, tech_stack=tech_stack,
            description=description, requirement=description,
        )

        return {
            "success": True,
            "project_name": pname,
            "folder": folder,
            "description": description,
            "tech_stack": tech_stack,
            "tasks": tasks,
            "task_count": len(tasks),
        }

    except Exception as e:
        logger.error(f"PRD 导入失败: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


# ==================== 快捷模式 ====================

@router.post("/quick")
async def quick_mode_api(request: Request):
    """快捷模式 — 跳过 PM，直接 Dev → 可选 Test"""
    data = await request.json()
    requirement = data.get("requirement", "").strip()
    project_name = data.get("project_name", "")
    no_test = data.get("no_test", False)

    if not requirement:
        return JSONResponse(status_code=400, content={"error": "需求描述不能为空"})
    if not project_name:
        return JSONResponse(status_code=400, content={"error": "请指定项目"})

    project_path = _find_project_path_safe(project_name)
    if not project_path:
        return JSONResponse(status_code=404, content={"error": "项目不存在"})

    def _task(orc):
        result = orc.run(requirement, incremental=True)
        return {
            "success": result.get("success", False),
            **{k: result[k] for k in (
                "tasks_completed", "tasks_total", "tasks_verified",
                "tests_passed", "tests_total", "bugs_open",
                "total_tokens", "elapsed_seconds", "files",
            ) if k in result},
        }

    sid = _start_project_session(project_path, f"[quick] {requirement[:50]}", _task)
    return {"session_id": sid, "message": f"快捷模式已启动: {project_name}"}


# ==================== 修复模式 ====================

@router.post("/fix")
async def fix_mode_api(request: Request):
    """修复模式 — 定向修复 Bug，跳过 PM 和 Dev"""
    data = await request.json()
    description = data.get("description", "").strip()
    project_name = data.get("project_name", "")

    if not description:
        return JSONResponse(status_code=400, content={"error": "Bug 描述不能为空"})
    if not project_name:
        return JSONResponse(status_code=400, content={"error": "请指定项目"})

    project_path = _find_project_path_safe(project_name)
    if not project_path:
        return JSONResponse(status_code=404, content={"error": "项目不存在"})

    def _task(orc):
        from autoc.core.project.models import BugReport
        bug = BugReport(
            id="web-fix-1", title=description[:100],
            description=description, severity="high",
        )
        orc.memory.add_bug_report(bug)

        result = orc.quick_fix_bugs(bugs_data=[{
            "id": "web-fix-1", "title": description[:100],
            "description": description, "severity": "high",
        }])
        return {
            "success": result.get("fixed", 0) > 0,
            "fixed": result.get("fixed", 0),
            "total": result.get("total", 0),
            "files": result.get("files", []),
        }

    sid = _start_project_session(project_path, f"[fix] {description[:50]}", _task)
    return {"session_id": sid, "message": f"修复模式已启动: {project_name}"}
