"""
AutoC Web 界面
==============
通过浏览器使用 AutoC 全自动开发系统。

启动方式:
    python -m autoc.server
    python -m autoc.server --port 8080
    python -m autoc.server --host 0.0.0.0 --port 9000
"""

import asyncio
import logging
import os
import threading
import time
import uuid
from contextlib import asynccontextmanager

import click
import uvicorn
from fastapi import FastAPI, HTTPException, Request, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from autoc.config import load_config, setup_logging, PROJECT_ROOT
from autoc.app import build_orchestrator
from autoc.core.runtime.session_registry import SessionRegistry
from autoc.exceptions import AutoCError
from autoc.server.event_enricher import enrich_event

logger = logging.getLogger("autoc.web")

STALE_CHECK_INTERVAL = 300  # 5 分钟


def _reset_stale_states():
    """扫描所有项目，将卡在活跃态但无活跃会话的僵死项目标记为 ABORTED。

    触发时机：服务器启动 + 定期巡检。
    原理：服务器刚启动时不可能有活线程，所有 active 状态项目都是上次崩溃的孤儿。
    """
    try:
        from autoc.core.project.manager import ProjectManager
        from autoc.core.project.models import ProjectStatus

        active_values = {s.value for s in ProjectStatus.active_statuses()}
        cfg = load_config("config/config.yaml")
        workspace_root = cfg.get("workspace", {}).get("output_dir", os.path.join(PROJECT_ROOT, "workspace"))
        if not os.path.isdir(workspace_root):
            return
        projects = ProjectManager.list_all_projects(workspace_root)

        running_workspaces = set()
        try:
            with sessions_lock:
                items = list(sessions.items())  # 快照，避免迭代期间 dict 变更
            for _sid, s in items:
                if s.get("status") == "running" and s.get("workspace_dir"):
                    running_workspaces.add(os.path.abspath(s["workspace_dir"]))
        except Exception:
            pass

        for p in projects:
            if p.get("status") not in active_values:
                continue
            project_path = p.get("path") or os.path.join(workspace_root, p.get("folder", p["name"]))
            if os.path.abspath(project_path) in running_workspaces:
                continue
            try:
                pm = ProjectManager(project_path)
                pm.update_status(ProjectStatus.ABORTED, force=True)
                logger.info(f"Stale 清理: 项目 '{p['name']}' 从 {p['status']} → aborted")
            except Exception as e:
                logger.warning(f"Stale 清理: 项目 '{p['name']}' 状态重置失败: {e}")
    except Exception as e:
        logger.warning(f"Stale 状态清理失败: {e}")


async def _periodic_stale_check():
    """后台定期检测 stale 项目状态"""
    while True:
        await asyncio.sleep(STALE_CHECK_INTERVAL)
        try:
            _reset_stale_states()
        except Exception as e:
            logger.warning(f"定期 Stale 检测失败: {e}")


@asynccontextmanager
async def lifespan(app_):
    global _main_loop
    _main_loop = asyncio.get_running_loop()
    _reset_stale_states()
    task = asyncio.create_task(_periodic_stale_check())
    yield
    task.cancel()


app = FastAPI(title="AutoC Web", description="全自动开发系统 Web 界面", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AutoCError)
async def autoc_error_handler(request: Request, exc: AutoCError):
    """统一处理 AutoC 业务异常，返回标准化 JSON 响应"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": str(exc),
            "error_type": type(exc).__name__,
            "detail": exc.detail if hasattr(exc, "detail") else "",
        },
    )


@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception):
    """兜底处理未预期异常，避免泄露内部堆栈"""
    logger.exception(f"未捕获异常: {request.method} {request.url.path}")
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": "服务器内部错误",
            "error_type": "InternalServerError",
            "detail": str(exc) if logger.isEnabledFor(logging.DEBUG) else "",
        },
    )


# ==================== 共享状态 ====================

sessions: dict = {}
# sessions dict 被 asyncio 事件循环和多个执行线程并发读写，需加锁保护写操作
sessions_lock = threading.Lock()

registry = SessionRegistry()

# asyncio 主事件循环引用：在 lifespan 启动时捕获，供后台线程通过 call_soon_threadsafe 使用
_main_loop: asyncio.AbstractEventLoop | None = None

BASE_DIR = PROJECT_ROOT

router = APIRouter(prefix="/api/v1")


# ==================== DB 后台写入线程 ====================
# 所有 DB 写操作通过此队列投递到独立线程，确保 asyncio 事件循环零阻塞

import queue as _queue_mod

_db_write_queue: _queue_mod.Queue = _queue_mod.Queue(maxsize=4096)
# 计数器用独立 Lock 保护：_db_drop_count 可能被多个调用线程同时递增，
# _db_processed_count 虽然只有消费者线程写，但与读操作共享同一把锁保持一致性。
_db_stats_lock = threading.Lock()
_db_drop_count: int = 0
_db_processed_count: int = 0


def _db_writer_loop():
    """后台线程：串行消费 DB 写任务，绝不阻塞 asyncio 事件循环"""
    global _db_processed_count
    while True:
        try:
            task = _db_write_queue.get()
            if task is None:
                break
            fn, args = task
            try:
                fn(*args)
                with _db_stats_lock:
                    _db_processed_count += 1
            except Exception as e:
                logger.debug("DB 后台写入失败: %s", e)
        except Exception:
            pass


_db_writer_thread = threading.Thread(target=_db_writer_loop, daemon=True, name="db-writer")
_db_writer_thread.start()


def _enqueue_db_write(fn, *args):
    """向 DB 写入队列投递任务（非阻塞，队列满则丢弃并计数）"""
    global _db_drop_count
    try:
        _db_write_queue.put_nowait((fn, args))
    except _queue_mod.Full:
        with _db_stats_lock:
            _db_drop_count += 1
            current_drops = _db_drop_count
        logger.warning("DB 写入队列已满，丢弃事件持久化（累计丢弃 %d 次）", current_drops)


def get_db_queue_stats() -> dict:
    """返回 DB 写入队列的运行时统计，供健康检查接口消费"""
    with _db_stats_lock:
        return {
            "queue_size": _db_write_queue.qsize(),
            "queue_max": 4096,
            "processed": _db_processed_count,
            "dropped": _db_drop_count,
        }


# ==================== 共享工具函数 ====================

def _extract_project_name(workspace_dir: str) -> str:
    """从 workspace_dir 路径提取项目名称（取最后一级目录名）"""
    if not workspace_dir:
        return ""
    return os.path.basename(workspace_dir.rstrip("/\\"))


def _find_project_path_safe(project_name: str) -> str | None:
    """安全查找项目路径，找不到返回 None（不抛异常）"""
    from autoc.core.project import ProjectManager
    cfg = load_config("config/config.yaml")
    workspace_root = cfg.get("workspace", {}).get("output_dir", "./workspace")
    return ProjectManager.find_project_by_name(project_name, workspace_root)


def _persist_has_events(sid: str):
    """DB 写入: 标记会话有事件"""
    registry.update(sid, has_events=1)


def _persist_done_status(sid: str, final_status: str, ended_at: float,
                         ws: str, pname: str):
    """DB 写入: 更新会话终态"""
    registry.update(sid, status=final_status, ended_at=ended_at,
                    workspace_dir=ws, project_name=pname)


def _persist_event(sid: str, seq: int, event: dict):
    """DB 写入: 持久化单条事件"""
    registry._db.save_event(sid, seq, event)


def _dispatch_event(sid: str, event: dict):
    """分发事件到会话的所有订阅者（零阻塞），DB 写入投递到后台线程。

    可从任意线程（包括 asyncio 事件循环外的后台线程）安全调用：
    - asyncio.Queue 的推送通过 call_soon_threadsafe 保证线程安全
    - session dict 的多字段更新在 sessions_lock 内完成
    """
    session = sessions.get(sid)
    if not session:
        return

    # enrich_event 是纯内存操作，在锁外执行降低持锁时间
    try:
        enrich_event(event)
    except Exception:
        pass

    with sessions_lock:
        # 防止 double-done：在同一把锁内完成状态检查 + 更新，消除两次独立加锁之间的 TOCTOU 窗口。
        # "stopped" 状态允许第一个 done 事件穿透（转为 "failed"），后续 done 事件被拦截。
        if event.get("type") == "done":
            current_status = sessions.get(sid, {}).get("status")
            if current_status not in ("running", "stopped"):
                logger.debug(f"[{sid}] 忽略重复 done 事件（当前状态: {current_status}）")
                return

        seq = len(session["events"])
        event["_seq"] = seq

        session["events"].append(event)

        if not session.get("_has_events_set") and event.get("type") not in ("heartbeat",):
            session["_has_events_set"] = True
            _enqueue_db_write(_persist_has_events, sid)

        if event.get("type") == "done":
            data = event.get("data") or {}
            # "stopped" 状态固定映射为 "failed"；"running" 状态按 success 字段决定
            if session.get("status") == "stopped":
                final_status = "failed"
            else:
                final_status = "completed" if data.get("success") else "failed"
            session["status"] = final_status
            session["ended_at"] = session.get("ended_at") or time.time()
            ws = session.get("workspace_dir", "")
            pname = session.get("project_name", "")
            if not pname and ws:
                pname = _extract_project_name(ws)
                session["project_name"] = pname
            _enqueue_db_write(_persist_done_status, sid, final_status,
                              session["ended_at"], ws, pname)

        subscribers_snapshot = list(session["subscribers"])

    _enqueue_db_write(_persist_event, sid, seq, event)

    # 推送给所有订阅者（asyncio.Queue 需通过 call_soon_threadsafe 跨线程安全调用）
    loop = _main_loop
    for q in subscribers_snapshot:
        try:
            if loop is not None and loop.is_running():
                loop.call_soon_threadsafe(q.put_nowait, event)
            else:
                q.put_nowait(event)
        except Exception:
            pass


_MAX_CONCURRENT_RUNS = 4


def _start_project_session(project_path: str, tag: str, task_fn, *, requirement: str = ""):
    """通用项目操作会话启动器。

    task_fn(orc) → done_data dict，在后台线程中执行。
    requirement: 完整的需求描述（用于会话记录），默认使用 tag。
    返回 session_id。
    """
    session_id = uuid.uuid4().hex[:8]
    req_label = requirement or tag

    def on_event(event):
        _dispatch_event(session_id, event)

    with sessions_lock:
        running_count = sum(1 for s in sessions.values() if s.get("status") == "running")
        if running_count >= _MAX_CONCURRENT_RUNS:
            raise HTTPException(
                status_code=429,
                detail=f"并发执行上限 {_MAX_CONCURRENT_RUNS}，请等待其他任务完成后再试",
            )
        sessions[session_id] = {
            "events": [],
            "subscribers": [],
            "status": "running",
            "started_at": time.time(),
            "ended_at": None,
            "workspace_dir": project_path,
            "requirement": req_label,
            "project_name": _extract_project_name(project_path),
        }

    registry.register(
        session_id, requirement=req_label, source="web",
        workspace_dir=project_path,
    )
    registry.update(session_id, project_name=_extract_project_name(project_path))

    def _run():
        orc = None
        try:
            cfg = load_config("config/config.yaml")
            orc = build_orchestrator(
                cfg,
                project_path=project_path,
                session_registry=registry,
                session_id=session_id,
                on_event=on_event,
            )
            done_data = task_fn(orc)
            if orc and hasattr(orc, "project_manager"):
                try:
                    done_data["version"] = getattr(orc, '_pending_version', None) or orc.project_manager.get_version()
                    done_data["requirement_type"] = getattr(orc, '_requirement_type', 'primary')
                except Exception:
                    pass
            # Orchestrator.finalize() 已发射 done 事件，Server 做 fallback：
            # 仅在 session 尚未结束时补发（幂等），加锁读取防止竞态
            with sessions_lock:
                _session_status = sessions.get(session_id, {}).get("status")
            if _session_status == "running":
                _dispatch_event(session_id, {
                    "type": "done", "agent": "system", "data": done_data,
                })
        except Exception as e:
            logger.exception(f"[{tag}] 失败: {e}")
            try:
                from autoc.core.project.models import ProjectStatus
                if orc and hasattr(orc, "project_manager") and orc.project_manager.exists():
                    orc.project_manager.update_status(ProjectStatus.ABORTED, force=True)
            except Exception:
                pass
            _dispatch_event(session_id, {
                "type": "error", "agent": "system",
                "data": {"message": str(e)},
            })
            exc_done = {"success": False, "failure_reason": str(e)}
            if orc:
                try:
                    exc_done["version"] = getattr(orc, '_pending_version', None) or orc.project_manager.get_version()
                    exc_done["requirement_type"] = getattr(orc, '_requirement_type', 'primary')
                    all_tasks = list(orc.memory.tasks.values())
                    if all_tasks:
                        exc_done["tasks_total"] = len(all_tasks)
                        exc_done["tasks_verified"] = sum(1 for t in all_tasks if t.passes)
                        exc_done["tasks"] = [
                            {"id": t.id, "title": t.title,
                             "status": t.status.value if hasattr(t.status, 'value') else str(t.status),
                             "passes": t.passes,
                             "error": t.error if hasattr(t, 'error') and t.error else ""}
                            for t in all_tasks
                        ]
                except Exception:
                    pass
            _dispatch_event(session_id, {
                "type": "done", "agent": "system",
                "data": exc_done,
            })

    threading.Thread(target=_run, daemon=True).start()
    return session_id


# ==================== 注册路由模块 ====================

import autoc.server.routes_config  # noqa: E402, F401
import autoc.server.routes_projects  # noqa: E402, F401
import autoc.server.routes_execution  # noqa: E402, F401
import autoc.server.routes_preview  # noqa: E402, F401
import autoc.server.routes_tools  # noqa: E402, F401
import autoc.server.routes_terminal  # noqa: E402, F401
import autoc.server.routes_benchmark  # noqa: E402, F401

app.include_router(router)

import autoc.server.compat  # noqa: E402, F401


# ==================== Server 启动 ====================

@click.command()
@click.option("--host", default="127.0.0.1", help="监听地址")
@click.option("--port", "-p", default=8080, type=int, help="监听端口")
@click.option("--reload", is_flag=True, help="开发模式 (自动重载)")
def main(host: str, port: int, reload: bool):
    """启动 AutoC Web 界面"""
    setup_logging("INFO")

    print()
    print("  ╔═══════════════════════════════════════╗")
    print("  ║                                       ║")
    print("  ║   🤖  AutoC Web - 全自动开发系统      ║")
    print("  ║                                       ║")
    url = f"http://{host}:{port}"
    print(f"  ║   🌐 {url:<29s}  ║")
    print("  ║                                       ║")
    print("  ╚═══════════════════════════════════════╝")
    print()

    uvicorn.run(
        "autoc.server:app" if reload else app,
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )
