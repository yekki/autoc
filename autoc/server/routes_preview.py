"""预览、项目状态、沙箱路由"""

import logging
import os
import shutil
import subprocess
import threading

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from autoc.server import router, sessions, sessions_lock, _dispatch_event
from autoc.config import load_config
from autoc.core.project import ProjectManager
from autoc.core.project.manager import slugify_project_name

logger = logging.getLogger("autoc.web")


# ==================== 预览 ====================

@router.get("/preview/{session_id}")
async def get_preview_info(session_id: str):
    """获取会话的预览信息"""
    with sessions_lock:
        session = sessions.get(session_id)
        if not session:
            return JSONResponse(status_code=404, content={"error": "会话不存在"})
        events_snapshot = list(session.get("events", []))

    for evt in reversed(events_snapshot):
        if evt.get("type") == "preview_ready":
            return evt.get("data", {})

    return {"available": False, "message": "预览尚未启动"}


@router.post("/preview/{session_id}/stop")
async def stop_preview(session_id: str):
    """终止预览进程"""
    with sessions_lock:
        session = sessions.get(session_id)
        if not session:
            return JSONResponse(status_code=404, content={"error": "会话不存在"})

    _dispatch_event(session_id, {
        "type": "preview_stopped",
        "agent": "system",
        "data": {"message": "预览已停止"},
    })
    return {"success": True}


_preview_sandboxes: dict[str, "DockerSandbox"] = {}
_preview_sandboxes_lock = threading.Lock()


def _detect_from_git(project_path: str):
    """当工作目录无代码文件时，从 git 历史推断项目类型"""
    import re
    try:
        r = subprocess.run(
            ["git", "ls-tree", "-r", "HEAD", "--name-only"],
            cwd=project_path, capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0:
            return None
        files = [f for f in r.stdout.strip().splitlines()
                 if not f.startswith(".")]
    except Exception:
        return None

    if not files:
        return None

    has_pkg_json = "package.json" in files
    # 排除辅助/验证脚本，避免误判为 cli_tool
    py_files = [
        f for f in files
        if f.endswith(".py") and "/" not in f
        and not f.startswith("test_") and not f.startswith("verify_")
        and not f.startswith("check_") and f not in ("setup.py", "conftest.py")
    ]

    # Monorepo 检测：frontend/backend 子目录共存 → web_fullstack（先于 .py 扫描）
    frontend_dirs = {"frontend", "client", "web", "ui"}
    backend_dirs = {"backend", "server", "api"}
    git_dirs = {f.split("/")[0] for f in files if "/" in f}
    has_frontend = bool(git_dirs & frontend_dirs)
    has_backend = bool(git_dirs & backend_dirs)
    if has_frontend and has_backend:
        fe_name = next(d for d in ("frontend", "client", "web", "ui") if d in git_dirs)
        fe_pkg = f"{fe_name}/package.json"
        if fe_pkg in files:
            try:
                r = subprocess.run(
                    ["git", "show", f"HEAD:{fe_pkg}"],
                    cwd=project_path, capture_output=True, text=True, timeout=5,
                )
                if r.returncode == 0:
                    import json as _json
                    scripts = _json.loads(r.stdout).get("scripts", {})
                    cmd = f"cd {fe_name} && npm run dev" if "dev" in scripts else f"cd {fe_name} && npm start"
                    return ("web_fullstack", cmd, 5173)
            except Exception:
                pass
        return ("web_fullstack", f"cd {fe_name} && npm run dev", 5173)

    if has_pkg_json:
        try:
            r = subprocess.run(
                ["git", "show", "HEAD:package.json"],
                cwd=project_path, capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0:
                import json
                pkg = json.loads(r.stdout)
                deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
                scripts = pkg.get("scripts", {})
                for fw in ("next", "nuxt", "@remix-run/dev"):
                    if fw in deps:
                        return ("web_fullstack", "npm run dev", 3000)
                if "dev" in scripts:
                    return ("web_frontend", "npm run dev", 5173)
                if "start" in scripts:
                    return ("web_frontend", "npm start", 3000)
                for fw in ("express", "fastify", "koa"):
                    if fw in deps:
                        cmd = "npm run dev" if "dev" in scripts else "npm start"
                        return ("web_backend", cmd, 3000)
        except Exception:
            pass

    go_files = [f for f in files if f.endswith(".go")]
    if go_files:
        if "go.mod" in files:
            try:
                r = subprocess.run(
                    ["git", "show", "HEAD:go.mod"],
                    cwd=project_path, capture_output=True, text=True, timeout=5,
                )
                if r.returncode == 0:
                    content = r.stdout
                    for fw in ("gin-gonic/gin", "labstack/echo", "gofiber/fiber"):
                        if fw in content:
                            return ("web_backend", "go run .", 8080)
            except Exception:
                pass
        has_main = "main.go" in files or any(
            f.startswith("cmd/") and f.endswith(".go") for f in files
        )
        if has_main:
            return ("cli_tool", "go run .", 0)

    if "index.html" in files:
        return ("web_frontend", "python -m http.server 8000", 8000)

    if "manage.py" in files:
        return ("web_fullstack", "python manage.py runserver 0.0.0.0:8000", 8000)

    simple_py_candidate = None
    for fname in ("app.py", "main.py", *py_files):
        if fname not in files:
            continue
        try:
            r = subprocess.run(
                ["git", "show", f"HEAD:{fname}"],
                cwd=project_path, capture_output=True, text=True, timeout=5,
            )
            if r.returncode != 0:
                continue
            content = r.stdout[:4096]
        except Exception:
            continue
        if re.search(r"(Flask|FastAPI|Bottle|Tornado|Sanic)", content):
            if "FastAPI" in content:
                module = os.path.splitext(fname)[0]
                return ("web_backend", f"python -m uvicorn {module}:app --host 0.0.0.0 --port 8000 --reload", 8000)
            return ("web_backend", f"python {fname}", 5000)
        if re.search(r"(argparse|click|typer|sys\.argv)", content):
            return ("cli_tool", f"python {fname} --help", 0)
        if re.search(r'if\s+__name__\s*==\s*["\']__main__["\']', content):
            return ("cli_tool", f"python {fname}", 0)
        if not simple_py_candidate and content.strip():
            simple_py_candidate = fname

    # 兜底：有 .py 文件但未匹配特定模式，视为简单脚本
    if simple_py_candidate:
        return ("cli_tool", f"python {simple_py_candidate}", 0)

    return None


def _read_readme_from_git(project_path: str) -> str:
    """从 git 历史读取 README"""
    for name in ("README.md", "readme.md", "README.txt", "README"):
        try:
            r = subprocess.run(
                ["git", "show", f"HEAD:{name}"],
                cwd=project_path, capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout[:4096]
        except Exception:
            pass
    return ""


@router.get("/projects/{project_name}/preview/detect")
async def detect_preview_type(project_name: str):
    """轻量级项目类型检测（不启动沙箱），用于预览 Tab 空状态展示"""
    config = load_config("config/config.yaml")
    workspace_root = os.path.abspath(config.get("workspace", {}).get("output_dir", "./workspace"))
    project_path = ProjectManager.find_project_by_name(project_name, workspace_root)
    if not project_path:
        return JSONResponse(status_code=404, content={"error": f"项目不存在: {project_name}"})

    from autoc.core.runtime.preview import ProjectTypeDetector, ProjectType

    project_type, command, port = ProjectTypeDetector.detect(project_path)

    # 回退 1：技术栈适配器
    if project_type in (ProjectType.UNKNOWN, ProjectType.LIBRARY):
        try:
            from autoc.stacks._registry import parse_project_context
            ctx = parse_project_context(project_path)
            if ctx.project_type in ("web_frontend", "web_fullstack", "web_backend"):
                command = ctx.start_command or command
                port = ctx.default_port or port
                project_type = ProjectType(ctx.project_type)
            elif ctx.project_type == "cli_tool":
                project_type = ProjectType.CLI_TOOL
                command = ctx.start_command or command
        except Exception:
            pass

    # 回退 2：从 git 历史推断（代码文件可能在 redefine 后被清理）
    if project_type in (ProjectType.UNKNOWN, ProjectType.LIBRARY):
        git_result = _detect_from_git(project_path)
        if git_result:
            pt_str, cmd, p = git_result
            project_type = ProjectType(pt_str)
            command = cmd
            port = p

    # 读取 README（优先磁盘，回退 git）
    readme = ""
    if project_type == ProjectType.CLI_TOOL:
        for name in ("README.md", "readme.md", "README.txt", "README"):
            readme_path = os.path.join(project_path, name)
            if os.path.isfile(readme_path):
                try:
                    with open(readme_path, encoding="utf-8") as f:
                        readme = f.read(4096)
                except OSError:
                    pass
                break
        if not readme:
            readme = _read_readme_from_git(project_path)

    return {
        "project_type": project_type.value,
        "command": command,
        "port": port,
        "readme": readme,
    }


def _restore_files_from_git(project_path: str):
    """当工作目录无代码文件时，从 git HEAD 恢复"""
    try:
        r = subprocess.run(
            ["git", "ls-tree", "-r", "HEAD", "--name-only"],
            cwd=project_path, capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0:
            return
        code_files = [f for f in r.stdout.strip().splitlines()
                      if not f.startswith(".autoc") and not f.startswith(".git")]
        if not code_files:
            return
        existing = [f for f in code_files if os.path.isfile(os.path.join(project_path, f))]
        if existing:
            return
        subprocess.run(
            ["git", "checkout", "HEAD", "--"] + code_files,
            cwd=project_path, capture_output=True, timeout=10,
        )
        logger.info(f"从 git 恢复 {len(code_files)} 个文件用于预览")
    except Exception as e:
        logger.warning(f"从 git 恢复文件失败: {e}")


@router.post("/projects/{project_name}/preview/start")
async def start_project_preview(project_name: str):
    """独立启动项目预览（不依赖执行会话）"""
    config = load_config("config/config.yaml")
    workspace_root = os.path.abspath(config.get("workspace", {}).get("output_dir", "./workspace"))
    project_path = ProjectManager.find_project_by_name(project_name, workspace_root)
    if not project_path:
        return JSONResponse(status_code=404, content={"error": f"项目不存在: {project_name}"})

    from autoc.core.runtime.preview import PreviewManager, ProjectType

    # 如果工作目录无代码文件，先从 git 恢复
    _restore_files_from_git(project_path)

    pm = PreviewManager(project_path)
    project_type, command, port = pm.detect_project()

    if project_type == ProjectType.UNKNOWN or project_type == ProjectType.LIBRARY:
        try:
            from autoc.stacks._registry import parse_project_context
            ctx = parse_project_context(project_path)
            if ctx.project_type in ("web_frontend", "web_fullstack", "web_backend"):
                command = ctx.start_command or command
                port = ctx.default_port or port
                if ctx.project_type == "web_frontend":
                    project_type = ProjectType.WEB_FRONTEND
                elif ctx.project_type == "web_backend":
                    project_type = ProjectType.WEB_BACKEND
                else:
                    project_type = ProjectType.WEB_FULLSTACK
        except Exception:
            pass

    # git 回退检测
    if project_type in (ProjectType.UNKNOWN, ProjectType.LIBRARY):
        git_result = _detect_from_git(project_path)
        if git_result:
            pt_str, cmd, p = git_result
            project_type = ProjectType(pt_str)
            command = cmd
            port = p

    if project_type == ProjectType.GUI_APP:
        return {
            "available": False,
            "project_type": ProjectType.GUI_APP.value,
            "message": "该项目使用了 GUI 框架（如 pygame/tkinter），需要图形显示环境，暂不支持容器内预览",
        }

    if project_type == ProjectType.UNKNOWN or project_type == ProjectType.LIBRARY:
        return {"available": False, "message": "无法检测项目类型，不支持预览"}

    try:
        # 启动前先清理上次残留的预览进程，防止同一容器内端口被旧进程占用
        with _preview_sandboxes_lock:
            old_sandbox = _preview_sandboxes.pop(project_name, None)
        if old_sandbox:
            try:
                old_sandbox.kill_user_processes()
            except Exception:
                pass

        from autoc.tools.sandbox import DockerSandbox
        sandbox = DockerSandbox(project_path, project_name=project_name)
        sandbox.ensure_ready()
        with _preview_sandboxes_lock:
            _preview_sandboxes[project_name] = sandbox

        if project_type == ProjectType.CLI_TOOL:
            info = pm.run_cli_demo(command, sandbox=sandbox)
        else:
            info = pm.start_docker(sandbox, command, port)

        result = {
            "available": info.available,
            "project_type": info.project_type.value,
            "url": info.url,
            "port": info.port,
            "command": info.command,
            "runtime": info.runtime,
            "message": info.message,
        }

        # 推送到活跃会话（如果有）
        with sessions_lock:
            snapshot = list(sessions.items())
        for sid, sess in snapshot:
            if sess.get("project_name") == project_name:
                _dispatch_event(sid, {
                    "type": "preview_ready",
                    "agent": "system",
                    "data": result,
                })
                break

        return result
    except Exception as e:
        logger.warning(f"手动启动预览失败: {e}")
        return {"available": False, "message": str(e)}


@router.post("/projects/{project_name}/preview/restart")
async def restart_project_preview(project_name: str):
    """重启项目预览服务（stop + start），用于 .env 变更后生效"""
    await stop_project_preview(project_name)
    return await start_project_preview(project_name)


@router.get("/projects/{project_name}/env")
async def get_project_env(project_name: str):
    """读取项目环境变量：合并 .env 当前值 + .env.example 声明的变量名"""
    config = load_config("config/config.yaml")
    workspace_root = os.path.abspath(config.get("workspace", {}).get("output_dir", "./workspace"))
    project_path = ProjectManager.find_project_by_name(project_name, workspace_root)
    if not project_path:
        return JSONResponse(status_code=404, content={"error": f"项目不存在: {project_name}"})

    env_vars: dict[str, str] = {}
    declared_keys: list[str] = []

    # 1) 从 .env.example / .env.template 获取声明的变量名
    for tpl in (".env.example", ".env.template", ".env.sample"):
        tpl_path = os.path.join(project_path, tpl)
        if os.path.isfile(tpl_path):
            try:
                with open(tpl_path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if "=" in line and not line.startswith("#"):
                            key = line.split("=", 1)[0].strip()
                            if key:
                                declared_keys.append(key)
                                env_vars.setdefault(key, "")
            except OSError:
                pass
            break

    # 2) 从 .env 读取实际值（覆盖声明的空值，并补充新 key）
    env_path = os.path.join(project_path, ".env")
    if os.path.isfile(env_path):
        try:
            with open(env_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        key, _, val = line.partition("=")
                        key = key.strip()
                        if key:
                            env_vars[key] = val.strip().strip('"').strip("'")
        except OSError:
            pass

    return {
        "env_vars": env_vars,
        "declared_keys": declared_keys,
        "has_env_file": os.path.isfile(os.path.join(project_path, ".env")),
    }


@router.put("/projects/{project_name}/env")
async def save_project_env(project_name: str, request: Request):
    """保存项目 .env 文件"""
    config = load_config("config/config.yaml")
    workspace_root = os.path.abspath(config.get("workspace", {}).get("output_dir", "./workspace"))
    project_path = ProjectManager.find_project_by_name(project_name, workspace_root)
    if not project_path:
        return JSONResponse(status_code=404, content={"error": f"项目不存在: {project_name}"})

    data = await request.json()
    env_vars: dict[str, str] = data.get("env_vars") or {}
    if not isinstance(env_vars, dict):
        return JSONResponse(status_code=400, content={"error": "env_vars 必须是对象"})

    lines = []
    for key, val in env_vars.items():
        key = key.strip()
        if not key:
            continue
        val = str(val).replace("\r", "")
        needs_quote = any(c in val for c in (' ', '"', "'", '#', '\n', '\\'))
        escaped = val.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')
        formatted = f'{key}="{escaped}"' if needs_quote else f"{key}={val}"
        lines.append(formatted)

    env_path = os.path.join(project_path, ".env")
    try:
        with open(env_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n" if lines else "")
        return {"success": True, "message": f"已保存 {len(env_vars)} 个环境变量"}
    except OSError as e:
        return JSONResponse(status_code=500, content={"error": f"写入失败: {e}"})


@router.post("/projects/{project_name}/preview/stop")
async def stop_project_preview(project_name: str):
    """停止项目预览（只停进程，不销毁容器）"""
    with _preview_sandboxes_lock:
        sandbox = _preview_sandboxes.pop(project_name, None)
    if sandbox:
        try:
            sandbox.kill_user_processes()
        except Exception:
            pass
    else:
        container_name = f"autoc-sandbox-{slugify_project_name(project_name)}"
        try:
            subprocess.run(
                ["docker", "exec", container_name, "bash", "-c",
                 "pkill -f 'python|flask|uvicorn|node|npm' 2>/dev/null || true"],
                capture_output=True, text=True, timeout=15,
            )
        except Exception:
            pass

    with sessions_lock:
        snapshot = list(sessions.items())
    for sid, sess in snapshot:
        if sess.get("project_name") == project_name:
            _dispatch_event(sid, {
                "type": "preview_stopped",
                "agent": "system",
                "data": {"message": "预览已停止"},
            })
            break
    return {"success": True, "message": "预览已停止"}


# ==================== 项目状态 ====================

@router.get("/project/status")
async def get_project_status(path: str = "."):
    """获取项目状态摘要"""
    config = load_config("config/config.yaml")
    workspace_root = os.path.realpath(os.path.abspath(
        config.get("workspace", {}).get("output_dir", "./workspace")
    ))
    project_path = os.path.realpath(os.path.abspath(path))
    if not project_path.startswith(workspace_root + os.sep) and project_path != workspace_root:
        raise HTTPException(status_code=403, detail="路径越界")
    pm = ProjectManager(project_path)

    if not pm.exists():
        return JSONResponse(status_code=404, content={"error": "项目不存在"})

    metadata = pm.load()
    if not metadata:
        return JSONResponse(status_code=500, content={"error": "加载项目元数据失败"})

    return {
        "name": metadata.name,
        "description": metadata.description,
        "status": metadata.status,
        "version": metadata.version,
        "tech_stack": metadata.tech_stack,
        "total_tasks": metadata.total_tasks,
        "completed_tasks": metadata.completed_tasks,
        "verified_tasks": metadata.verified_tasks,
        "sessions_count": len(metadata.sessions),
        "milestones_count": len(metadata.milestones),
        "created_at": metadata.created_at,
        "updated_at": metadata.updated_at,
        "total_tokens": getattr(metadata, "total_tokens", 0),
    }


# ==================== 沙箱 ====================

@router.get("/sandbox/status")
async def sandbox_status():
    """获取沙箱状态"""
    docker_ok = shutil.which("docker") is not None
    if docker_ok:
        try:
            r = subprocess.run(["docker", "info"], capture_output=True, timeout=5)
            docker_ok = r.returncode == 0
        except Exception:
            docker_ok = False

    containers = []
    if docker_ok:
        try:
            r = subprocess.run(
                ["docker", "ps", "--filter", "name=autoc-sandbox", "--format",
                 "{{.Names}}\t{{.Image}}\t{{.State}}\t{{.Ports}}"],
                capture_output=True, text=True, timeout=10,
            )
            for line in r.stdout.strip().splitlines():
                parts = line.split("\t")
                if len(parts) >= 3:
                    containers.append({
                        "name": parts[0], "image": parts[1],
                        "state": parts[2], "ports": parts[3] if len(parts) > 3 else "",
                    })
        except Exception:
            pass

    config = load_config("config/config.yaml")
    return {
        "docker_available": docker_ok,
        "sandbox_enabled": True,
        "sandbox_mode": config.get("features", {}).get("sandbox_mode", "project"),
        "containers": containers,
    }


@router.post("/sandbox/{name}/stop")
async def sandbox_stop(name: str):
    """沙箱容器仅能随项目删除时一并清理，此接口已禁用。"""
    if not name.startswith("autoc-sandbox"):
        raise HTTPException(status_code=400, detail="只能管理 autoc-sandbox 容器")
    raise HTTPException(
        status_code=403,
        detail="沙箱容器仅能随项目删除时一并清理。请删除对应项目后再操作。",
    )
