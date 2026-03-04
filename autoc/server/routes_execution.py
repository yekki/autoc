"""执行路由：启动运行、SSE 事件流、终止会话、文件读取、需求优化、AI 辅助"""

import asyncio
import ctypes
import json
import logging
import os
import threading
import time
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse

from autoc.server import router, sessions, sessions_lock, registry, _dispatch_event
from autoc.config import load_config, PROJECT_ROOT
from autoc.app import build_orchestrator, resolve_workspace_dir
from autoc.core.project import ProjectManager
from autoc.core.project.models import ProjectStatus

logger = logging.getLogger("autoc.web")



# ==================== AI 辅助（描述润色 + 技术栈推荐） ====================

_AI_ASSIST_PROMPT = """\
你是一个软件项目规划专家。请根据项目信息完成以下任务。

## 项目信息
- 项目名称: {name}
{desc_section}

## 任务
{task_section}

## 可选技术栈（仅从中选择）
后端: Python, FastAPI, Flask, Django, Node.js, Express, Go, Java, Spring Boot, Rust
前端: React, Vue, HTML/CSS/JS, TypeScript, Next.js, Vite
数据库: SQLite, PostgreSQL, MySQL, MongoDB, Redis
工具: Docker, CLI, Bash, Jupyter

## 输出格式（严格 JSON，不要 markdown 代码块）
{output_format}
"""


def _build_ai_assist_prompt(name: str, description: str, action: str) -> str:
    desc_section = f"- 项目描述: {description}" if description else "- 项目描述: （无）"

    if action == "polish":
        task_section = (
            "请将用户的简短需求扩展为一段完整、清晰的软件需求描述。\n"
            "规则:\n"
            "1. 输出 100-300 字的中文描述\n"
            "2. 必须包含：核心功能点（3-5 个）、目标用户、关键交互方式\n"
            "3. 如果原始描述很短（如「开发一个五子棋」），要大幅扩展，补充具体功能细节\n"
            "4. 如果原始描述已较详细，则在其基础上润色、补充遗漏点\n"
            "5. 输出必须明显优于输入，不能原样返回\n"
            "6. 适合作为 AI 自动开发系统的输入，功能描述要具体可实现"
        )
        output_format = '{"description": "扩展润色后的完整需求描述"}'
    elif action == "recommend_tech":
        task_section = (
            "请根据项目需求推荐最合适的技术栈组合。\n"
            "分析步骤:\n"
            "1. 判断项目类型（Web应用/CLI工具/数据处理/游戏等）\n"
            "2. 判断是否需要前端、后端、数据库\n"
            "3. 从可选列表中选择 2-5 个最匹配的标签\n\n"
            "规则:\n"
            "- 输出的标签必须与可选列表中的值**完全一致**（区分大小写、含斜杠）\n"
            "- 例如前端三件套必须写 \"HTML/CSS/JS\"，不能拆开写\n"
            "- 优先选择轻量级方案（如 SQLite 优于 PostgreSQL、Flask 优于 Django）\n"
            "- 纯 Python 项目不需要前端技术栈\n"
            "- 游戏/GUI 类项目一般选 Python + HTML/CSS/JS 或纯 Python"
        )
        output_format = '{"tech_stack": ["Python", "HTML/CSS/JS"]}'
    else:
        task_section = (
            "请同时完成两件事:\n"
            "1. 为该项目生成/润色一段清晰专业的项目描述（80-200字，中文）\n"
            "2. 推荐 2-5 个最适合的技术栈标签（从可选列表中选择，值完全匹配）"
        )
        output_format = '{"description": "优化后的项目描述", "tech_stack": ["Python", "FastAPI"]}'

    return _AI_ASSIST_PROMPT.format(
        name=name,
        desc_section=desc_section,
        task_section=task_section,
        output_format=output_format,
    )


@router.post("/ai-assist")
async def ai_assist(request: Request):
    """AI 辅助：描述润色 / 技术栈推荐 / 两者兼得"""
    data = await request.json()
    action = data.get("action", "both")  # polish / recommend_tech / both
    project_name = data.get("project_name", "").strip()
    description = data.get("description", "").strip()

    if not project_name:
        return JSONResponse(status_code=400, content={"error": "项目名称不能为空"})

    try:
        from autoc.core.llm import LLMClient
        from autoc.core.llm.model_config import ModelConfigManager
        from autoc.core.analysis.refiner import RequirementRefiner

        mcm = ModelConfigManager(PROJECT_ROOT)
        assist_config = mcm.build_llm_config_for_agent("helper")

        if not assist_config or not assist_config.api_key:
            return JSONResponse(status_code=400, content={
                "error": "未配置辅助模型，请先在设置中为「辅助」分配模型",
            })

        assist_config.timeout = 45
        llm_client = LLMClient(assist_config)
        prompt = _build_ai_assist_prompt(project_name, description, action)

        max_tok = 1024 if action == "polish" else 512
        response = await asyncio.to_thread(
            llm_client.chat,
            messages=[
                {"role": "system", "content": "直接输出 JSON，不要解释。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=max_tok,
            response_format={"type": "json_object"},
        )

        raw_content = response.get("content", "") if isinstance(response, dict) else ""
        reasoning = response.get("reasoning_content", "") or ""
        # 推理模型可能把内容全放在 reasoning_content 而 content 为空
        if not raw_content.strip() and reasoning:
            raw_content = reasoning
        logger.info(f"AI 辅助 [{action}] content({len(raw_content)}字) reasoning({len(reasoning)}字): {raw_content[:200]}")
        result_data = RequirementRefiner._parse_json_response(raw_content) or {}

        # 回退：JSON 解析失败但有非空文本
        if not result_data and raw_content.strip():
            text = raw_content.strip()
            if action in ("polish", "both"):
                result_data["description"] = text
            logger.warning(f"AI 辅助 [{action}] JSON 解析失败，使用原始文本回退")

        logger.info(f"AI 辅助 [{action}] 解析结果: {list(result_data.keys())} — description 长度: {len(result_data.get('description', ''))}")

        tokens_used = {
            "total_tokens": llm_client.total_tokens,
            "prompt_tokens": llm_client.prompt_tokens,
            "completion_tokens": llm_client.completion_tokens,
        }

        result = {"tokens_used": tokens_used}
        if action in ("polish", "both") and "description" in result_data:
            result["description"] = result_data["description"]
        if action in ("recommend_tech", "both") and "tech_stack" in result_data:
            valid_tags = {
                "Python", "FastAPI", "Flask", "Django", "Node.js", "Express",
                "Go", "Java", "Spring Boot", "Rust",
                "React", "Vue", "HTML/CSS/JS", "TypeScript", "Next.js", "Vite",
                "SQLite", "PostgreSQL", "MySQL", "MongoDB", "Redis",
                "Docker", "CLI", "Bash", "Jupyter",
            }
            # 模糊匹配：LLM 可能输出 "HTML" / "CSS" / "JavaScript" 等变体
            _fuzzy_map = {
                "html": "HTML/CSS/JS", "css": "HTML/CSS/JS", "javascript": "HTML/CSS/JS",
                "js": "HTML/CSS/JS", "html/css": "HTML/CSS/JS",
                "node": "Node.js", "nodejs": "Node.js",
                "next": "Next.js", "nextjs": "Next.js",
                "ts": "TypeScript", "springboot": "Spring Boot",
                "spring": "Spring Boot", "pg": "PostgreSQL",
                "postgres": "PostgreSQL", "mongo": "MongoDB",
                "sqlite3": "SQLite",
            }
            raw_stack = result_data["tech_stack"]
            matched = []
            seen = set()
            for t in raw_stack:
                tag = t if t in valid_tags else _fuzzy_map.get(t.lower().replace(" ", ""))
                if tag and tag not in seen:
                    matched.append(tag)
                    seen.add(tag)
            result["tech_stack"] = matched[:6]
            logger.info(f"AI 辅助 [recommend_tech] 原始: {raw_stack} → 匹配: {matched}")

        # 持久化到项目 DB（项目已存在时）
        try:
            from autoc.server import _find_project_path_safe
            project_path = _find_project_path_safe(project_name)
            if project_path:
                pm = ProjectManager(project_path)
                pm.record_ai_assist(
                    action=action,
                    total_tokens=tokens_used["total_tokens"],
                    prompt_tokens=tokens_used["prompt_tokens"],
                    completion_tokens=tokens_used["completion_tokens"],
                )
        except Exception as db_err:
            logger.debug(f"AI 辅助 token 持久化跳过: {db_err}")

        return result

    except Exception as e:
        logger.error(f"AI 辅助失败: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


# ==================== 需求优化 ====================

@router.post("/refine")
async def refine_requirement(request: Request):
    """预处理需求: 质量评估 + 智能增强 + 澄清问题生成"""
    data = await request.json()
    requirement = data.get("requirement", "").strip()
    mode = data.get("mode", "enhance")
    workspace_dir = data.get("workspace_dir", "")
    project_name = data.get("project_name", "")
    if not requirement:
        return JSONResponse(status_code=400, content={"error": "需求不能为空"})

    try:
        from autoc.core.analysis.refiner import RequirementRefiner
        from autoc.core.llm import LLMConfig, LLMClient
        from autoc.app import _resolve_llm_config

        cfg = load_config("config/config.yaml")
        llm_config, ok = _resolve_llm_config(cfg)

        if not ok or llm_config is None:
            return JSONResponse(status_code=400, content={
                "error": "未配置 LLM，请先在设置中配置模型",
            })

        llm_client = LLMClient(llm_config)

        refiner_cfg = cfg.get("refiner", {})
        refiner = RequirementRefiner(
            llm_client=llm_client,
            mode="enhance",
            quality_threshold_high=refiner_cfg.get("quality_threshold_high", 0.7),
            quality_threshold_low=refiner_cfg.get("quality_threshold_low", 0.4),
        )

        quality = refiner.assess_quality(requirement)
        result = {
            "quality": {
                "score": quality.score,
                "level": quality.level,
                "issues": [i.model_dump() for i in quality.issues],
                "has_clear_goal": quality.has_clear_goal,
                "has_tech_context": quality.has_tech_context,
                "has_scope": quality.has_scope,
                "is_testable": quality.is_testable,
                "word_count": quality.word_count,
            },
        }

        if mode == "enhance":
            refined = await asyncio.to_thread(
                lambda: refiner.refine(requirement, workspace_dir),
            )
            result["refined"] = refined.refined
            result["enhancements"] = refined.enhancements
            result["scope"] = refined.scope
            result["tech_hints"] = refined.tech_hints
            result["suggested_split"] = refined.suggested_split
            result["quality_after"] = refined.quality_after
            result["skipped"] = refined.skipped

        elif mode == "clarify":
            clarification = await asyncio.to_thread(
                refiner.generate_clarification, requirement,
            )
            result["clarification"] = {
                "questions": clarification.questions,
                "defaults": clarification.defaults,
                "reason": clarification.reason,
            }

        return result

    except Exception as e:
        logger.error(f"需求优化失败: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.post("/refine/merge")
async def merge_clarification_api(request: Request):
    """合并用户的澄清回答到原始需求"""
    data = await request.json()
    requirement = data.get("requirement", "")
    questions = data.get("questions", [])
    answers = data.get("answers", [])

    if not requirement:
        return JSONResponse(status_code=400, content={"error": "需求不能为空"})

    from autoc.core.analysis.refiner import RequirementRefiner
    merged = RequirementRefiner.merge_clarification(
        requirement, questions, answers,
    )
    return {"merged": merged}


# ==================== 运行任务 ====================

@router.post("/run")
async def run_project(request: Request):
    """启动一个新的 AutoC 开发会话"""
    data = await request.json()
    requirement = data.get("requirement", "").strip()
    project_name = data.get("project_name", "")
    # 高级参数
    max_rounds = data.get("max_rounds")
    max_iterations = data.get("max_iterations")
    resume = data.get("resume", False)
    clean = data.get("clean", False)
    no_parallel = data.get("no_parallel", False)
    verbose = data.get("verbose", False)
    run_mode = data.get("mode", "full")  # full / quick / fix
    require_plan_approval = data.get("require_plan_approval", False)  # S-002

    if not requirement:
        return JSONResponse(status_code=400, content={"error": "请输入需求描述"})

    # 并发守卫：阻止同一项目重复执行
    if project_name:
        cfg = load_config("config/config.yaml")
        workspace_root = cfg.get("workspace", {}).get("output_dir", "./workspace")
        _proj_path = ProjectManager.find_project_by_name(project_name, workspace_root)
        if _proj_path:
            _pm = ProjectManager(_proj_path)
            _meta = _pm.load()
            if _meta and _meta.status in {s.value for s in ProjectStatus.active_statuses()}:
                _abs = os.path.abspath(_proj_path)
                with sessions_lock:
                    _running = [
                        sid for sid, s in sessions.items()
                        if s.get("status") == "running"
                        and os.path.abspath(s.get("workspace_dir", "")) == _abs
                    ]
                if _running:
                    return JSONResponse(status_code=409, content={
                        "error": f"项目 [{project_name}] 正在执行中，请等待完成或终止后再操作",
                        "running_sessions": _running,
                    })

    session_id = uuid.uuid4().hex[:8]
    loop = asyncio.get_running_loop()

    def on_event(event):
        _dispatch_event(session_id, event)

    def run_in_thread():
        _start_time = time.time()
        _workspace_dir = ""
        _phase = "init"
        _orchestrator = None

        def _fail(reason: str, phase: str = "", suggestions: list | None = None):
            """统一的失败处理：写 dev_session + 版本快照 + 发完整事件"""
            elapsed = time.time() - _start_time
            total_tokens = _orchestrator.total_tokens if _orchestrator else 0
            agent_tokens = None
            tasks_snapshot = []
            tasks_total = 0
            tasks_verified = 0
            if _orchestrator:
                try:
                    from autoc.core.orchestrator.lifecycle import collect_agent_tokens
                    agent_tokens = collect_agent_tokens(_orchestrator)
                except Exception:
                    pass
                try:
                    all_tasks = list(_orchestrator.memory.tasks.values())
                    tasks_total = len(all_tasks)
                    tasks_verified = sum(1 for t in all_tasks if t.passes)
                    tasks_snapshot = [
                        {"id": t.id, "title": t.title,
                         "status": t.status.value if hasattr(t.status, 'value') else str(t.status),
                         "passes": t.passes,
                         "error": t.error if hasattr(t, 'error') and t.error else "",
                         "tokens_used": getattr(t, 'tokens_used', 0),
                         "elapsed_seconds": getattr(t, 'elapsed_seconds', 0)}
                        for t in all_tasks
                    ]
                except Exception:
                    pass
            on_event({
                "type": "execution_failed", "agent": "system",
                "data": {
                    "failure_reason": reason,
                    "phase": phase or _phase,
                    "recovery_suggestions": suggestions or [],
                    "tasks_verified": tasks_verified, "tasks_total": tasks_total,
                },
            })
            on_event({
                "type": "done", "agent": "system",
                "data": {
                    "success": False,
                    "summary": reason,
                    "failure_reason": reason,
                    "phase": phase or _phase,
                    "recovery_suggestions": suggestions or [],
                    "tasks_completed": 0, "tasks_total": tasks_total,
                    "tasks_verified": tasks_verified,
                    "elapsed_seconds": elapsed,
                    "total_tokens": total_tokens,
                    "agent_tokens": agent_tokens,
                    "tasks": tasks_snapshot,
                },
            })
            if _workspace_dir:
                try:
                    pm = ProjectManager(_workspace_dir)
                    from autoc.core.project.models import ProjectStatus
                    if pm.exists():
                        pm.update_status(ProjectStatus.ABORTED, force=True)
                    pm.record_session(
                        session_id=session_id,
                        requirement=requirement[:200],
                        success=False,
                        tasks_completed=0, tasks_total=tasks_total,
                        elapsed_seconds=elapsed,
                        total_tokens=total_tokens,
                        agent_tokens=agent_tokens,
                        failure_reason=reason[:500],
                    )
                    ver = pm.get_version() if pm.exists() else "1.0.0"
                    pm.save_version_snapshot(
                        version=ver,
                        requirement_type=getattr(_orchestrator, '_requirement_type', 'primary') if _orchestrator else 'primary',
                        requirement=requirement[:2000],
                        tasks=tasks_snapshot,
                        success=False,
                        total_tokens=total_tokens,
                        elapsed_seconds=elapsed,
                        started_at=_start_time,
                        ended_at=time.time(),
                    )
                except Exception:
                    pass
            registry.update(
                session_id, status="failed",
                ended_at=time.time(),
                workspace_dir=_workspace_dir,
            )

        try:
            cfg = load_config("config/config.yaml")

            if max_rounds is not None:
                cfg.setdefault("orchestrator", {})["max_rounds"] = int(max_rounds)
            if max_iterations is not None:
                # 写入 agents.coder.max_iterations，供 facade._init_agents 读取生效
                cfg.setdefault("agents", {}).setdefault("coder", {})["max_iterations"] = int(max_iterations)
            if no_parallel:
                cfg.setdefault("features", {})["parallel"] = False
            if require_plan_approval:
                cfg.setdefault("features", {})["plan_approval"] = True
            if verbose:
                cfg.setdefault("logging", {})["level"] = "DEBUG"

            _workspace_dir = resolve_workspace_dir(cfg, project_name=project_name)

            try:
                from autoc.core.project import ProjectManager as _PM
                _pm = _PM(_workspace_dir)
                _meta = _pm.load()
                if _meta:
                    if not _meta.git_enabled:
                        cfg.setdefault("features", {})["git"] = False
                    if _meta.single_task:
                        cfg.setdefault("features", {})["single_task"] = True
            except Exception:
                pass

            _phase = "sandbox_init"
            try:
                orchestrator = build_orchestrator(
                    cfg,
                    project_path=_workspace_dir,
                    session_registry=registry,
                    session_id=session_id,
                    on_event=on_event,
                )
            except Exception as build_err:
                from autoc.exceptions import ConfigError
                if isinstance(build_err, ConfigError):
                    _fail(
                        "未设置 API Key，请在设置中配置模型",
                        phase="config",
                        suggestions=["在右上角设置中配置 API Key"],
                    )
                    return
                if isinstance(build_err, RuntimeError) and "Docker" in str(build_err):
                    _fail(
                        f"Docker 沙箱初始化失败: {build_err}",
                        phase="sandbox_init",
                        suggestions=["确保 Docker Desktop 已启动", "运行 docker info 检查状态", "点击「重新运行」再试一次"],
                    )
                    return
                raise

            _orchestrator = orchestrator
            _workspace_dir = orchestrator.file_ops.workspace_dir
            # P1: 同步 project_name 到 session 和 registry，确保历史记录可追溯
            _resolved_name = os.path.basename(_workspace_dir.rstrip("/\\")) if _workspace_dir else project_name
            with sessions_lock:
                if session_id in sessions:
                    sessions[session_id]["workspace_dir"] = _workspace_dir
                    sessions[session_id]["project_name"] = _resolved_name
            registry.update(
                session_id,
                workspace_dir=_workspace_dir,
                project_name=_resolved_name,
            )

            if run_mode == "fix":
                _phase = "fix"
                from autoc.core.project.models import BugReport
                bug = BugReport(
                    id="web-fix-1", title=requirement[:100],
                    description=requirement, severity="high",
                )
                orchestrator.memory.add_bug_report(bug)
                result = orchestrator.quick_fix_bugs(bugs_data=[{
                    "id": "web-fix-1", "title": requirement[:100],
                    "description": requirement, "severity": "high",
                }])
                on_event({"type": "done", "agent": "system", "data": result})
                return

            _phase = "running"
            is_incremental = orchestrator.project_manager.exists()

            result = orchestrator.run(
                requirement,
                incremental=is_incremental,
                resume=resume,
                clean=clean,
            )

        except SystemExit:
            if sessions.get(session_id, {}).get("stop_requested"):
                if _workspace_dir:
                    try:
                        pm = ProjectManager(_workspace_dir)
                        if pm.exists():
                            pm.update_status(ProjectStatus.INCOMPLETE, force=True)
                        pm.record_session(
                            session_id=session_id,
                            requirement=requirement[:200],
                            success=False,
                            tasks_completed=0, tasks_total=0,
                            elapsed_seconds=time.time() - _start_time,
                            total_tokens=_orchestrator.total_tokens if _orchestrator else 0,
                            failure_reason="用户手动终止",
                        )
                    except Exception:
                        pass
                registry.update(
                    session_id, status="stopped",
                    ended_at=time.time(),
                    workspace_dir=_workspace_dir,
                )
            else:
                _fail("执行被用户终止", phase="interrupted", suggestions=["点击「重新运行」重新执行"])
        except Exception as e:
            logger.exception("执行出错")
            _fail(
                str(e), phase=_phase,
                suggestions=["检查后端日志获取详细信息", "点击「重新运行」重新执行"],
            )

    _MAX_CONCURRENT_RUNS = 4

    # 将「并发检查 + session 注册 + thread 启动」合并为原子操作，消除 TOCTOU 窗口：
    # 若检查和创建分离，两个并发请求可同时通过检查后各自启动，突破上限。
    with sessions_lock:
        active_runs = sum(
            1 for s in sessions.values()
            if s.get("status") == "running" and s.get("thread") and s["thread"].is_alive()
        )
        if active_runs >= _MAX_CONCURRENT_RUNS:
            return JSONResponse(
                status_code=429,
                content={"error": f"当前已有 {active_runs} 个任务在运行，请等待完成后再试（上限 {_MAX_CONCURRENT_RUNS}）"},
            )
        sessions[session_id] = {
            "requirement": requirement,
            "project_name": project_name,
            "started_at": time.time(),
            "ended_at": None,
            "workspace_dir": "",
            "status": "running",
            "events": [],
            "subscribers": [],
            "stop_requested": False,
        }
        thread = threading.Thread(target=run_in_thread, daemon=True, name=f"autoc-exec-{session_id[:8]}")
        thread.start()
        sessions[session_id]["thread"] = thread

    registry.register(
        session_id, requirement=requirement[:500], source="web",
        workspace_dir="",
    )
    registry.update(session_id, project_name=project_name or "")

    return {"session_id": session_id}


# ==================== SSE 事件流 ====================

@router.get("/events/{session_id}")
async def stream_events(session_id: str):
    """SSE 端点 - 流式推送执行事件"""
    with sessions_lock:
        session = sessions.get(session_id)
    if not session:
        return JSONResponse(status_code=404, content={"error": "会话不存在"})

    queue = asyncio.Queue()

    async def event_generator():
        try:
            with sessions_lock:
                # 在锁内再次确认 session 仍存在，并原子追加订阅者 + 获取历史快照
                _session = sessions.get(session_id)
                if not _session:
                    return
                _session["subscribers"].append(queue)
                history = list(_session["events"])
            last_seq = -1
            for event in history:  # history 已在锁内快照
                last_seq = event.get("_seq", -1)
                yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
                if event.get("type") == "done":
                    return

            if session.get("status") != "running":
                return

            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30)
                    seq = event.get("_seq", -1)
                    if seq <= last_seq:
                        continue
                    last_seq = seq
                    yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
                    if event.get("type") == "done":
                        break
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
        finally:
            with sessions_lock:
                try:
                    session["subscribers"].remove(queue)
                except ValueError:
                    pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/sessions/{session_id}/events")
async def get_session_events(session_id: str):
    """获取会话的所有事件（非流式 JSON），用于历史回放"""
    # 初始化默认值，防止锁内代码分支未覆盖时出现 UnboundLocalError
    events_snapshot: list = []
    status = "unknown"
    project_name = ""
    requirement = ""
    with sessions_lock:
        session = sessions.get(session_id)
        if session:
            events_snapshot = list(session.get("events", []))
            status = session.get("status", "unknown")
            project_name = session.get("project_name", "")
            requirement = session.get("requirement", "")
    if session:
        events = [
            {k: v for k, v in e.items() if k != "_seq"}
            for e in events_snapshot
            if e.get("type") not in ("heartbeat",)
        ]
    else:
        events = registry._db.get_events(session_id)
        reg = registry.get(session_id) or {}
        status = reg.get("status", "unknown")
        project_name = reg.get("project_name", "")
        requirement = reg.get("requirement", "")
        if not events and status == "unknown":
            return JSONResponse(status_code=404, content={"error": "会话不存在"})

    return {
        "events": events,
        "status": status,
        "project_name": project_name,
        "requirement": requirement,
    }


# ==================== 终止会话 ====================

@router.post("/stop/{session_id}")
async def stop_session(session_id: str):
    """终止正在运行的会话"""
    ended_at = time.time()
    workspace = ""
    project_name = ""
    with sessions_lock:
        session = sessions.get(session_id)
        if not session:
            return JSONResponse(status_code=404, content={"error": "会话不存在"})
        if session.get("status") != "running":
            return JSONResponse(status_code=400, content={"error": "会话未在运行中"})
        session["stop_requested"] = True
        # 直接在锁内设置终态，防止执行线程的 done 事件与本接口的 done 竞争导致状态不一致
        session["status"] = "stopped"
        session["ended_at"] = ended_at
        workspace = session.get("workspace_dir", "")
        project_name = session.get("project_name", "")
        thread = session.get("thread")

    # 直接持久化终态到 DB（不依赖 _dispatch_event 的 done 路径，避免被双重保护逻辑拦截）
    registry.update(session_id, status="stopped", ended_at=ended_at,
                    workspace_dir=workspace, project_name=project_name)

    # 锁已释放后再发事件，避免 _dispatch_event 内部再次获取 sessions_lock 造成死锁
    _dispatch_event(session_id, {
        "type": "error", "agent": "system",
        "data": {"message": "用户手动终止了执行"},
    })
    _dispatch_event(session_id, {
        "type": "done", "agent": "system",
        "data": {"success": False, "summary": "用户终止"},
    })

    # 协作式取消：stop_requested 标志已在上方设置，等待编排器循环自检退出。
    # ctypes.PyThreadState_SetAsyncExc 作为最后的兜底（仅在 Python 层生效，
    # 不适用于阻塞在 C 扩展的线程），使用 try/except 防止其异常影响 API 响应。
    if thread and thread.is_alive():
        tid = thread.ident
        if tid:
            try:
                ctypes.pythonapi.PyThreadState_SetAsyncExc(
                    ctypes.c_ulong(tid), ctypes.py_object(SystemExit)
                )
            except Exception as exc:
                logger.warning(f"[stop_session] 注入 SystemExit 失败（线程将在下一检查点自行停止）: {exc}")

    return {"success": True, "message": "已发送终止请求"}


# ==================== 文件读取 ====================

@router.get("/projects/{project_name}/file")
async def get_project_file(project_name: str, path: str = ""):
    """通过项目名获取工作区文件内容（不依赖 session）"""
    cfg = load_config("config/config.yaml")
    workspace_root = cfg.get("workspace", {}).get("output_dir", "./workspace")

    project_path = ProjectManager.find_project_by_name(project_name, workspace_root)
    if not project_path:
        return JSONResponse(status_code=404, content={"error": "项目不存在"})

    full_path = os.path.realpath(os.path.join(project_path, path))
    _base = os.path.realpath(project_path).rstrip("/") + "/"
    if not (full_path + "/").startswith(_base):
        return JSONResponse(status_code=403, content={"error": "路径越界"})

    try:
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()
        return {"path": path, "content": content}
    except FileNotFoundError:
        return JSONResponse(status_code=404, content={"error": f"文件不存在: {path}"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/file/{session_id}")
async def get_file(session_id: str, path: str = ""):
    """获取工作区中的文件内容"""
    with sessions_lock:
        session = sessions.get(session_id)
        workspace = session.get("workspace_dir", "") if session else ""
    if not session:
        return JSONResponse(status_code=404, content={"error": "会话不存在"})
    if not workspace:
        return JSONResponse(status_code=400, content={"error": "工作区尚未初始化"})

    full_path = os.path.realpath(os.path.join(workspace, path))
    _base = os.path.realpath(workspace).rstrip("/") + "/"
    if not (full_path + "/").startswith(_base):
        return JSONResponse(status_code=403, content={"error": "路径越界"})

    try:
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()
        return {"path": path, "content": content}
    except FileNotFoundError:
        return JSONResponse(status_code=404, content={"error": f"文件不存在: {path}"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# ==================== S-001: 快速启动（一步建项目+执行） ====================

@router.post("/quick-start")
async def quick_start(request: Request):
    """S-001: 首屏一步启动 — 创建项目并立即开始执行。

    Body:
        project_name: str  (必填)
        requirement:  str  (必填)
    """
    from autoc.core.project import ProjectManager as PM, validate_project_name
    from autoc.core.project.models import ProjectStatus

    data = await request.json()
    display_name = data.get("display_name", "").strip()
    requirement = data.get("requirement", "").strip()

    # R-015: 支持中文显示名称，自动生成 ASCII folder slug
    raw_name = data.get("project_name", "").strip()
    if not raw_name and display_name:
        from autoc.core.project.manager import slugify_project_name
        raw_name = slugify_project_name(display_name)
    project_name = raw_name

    if not project_name:
        return JSONResponse(status_code=400, content={"error": "项目名称不能为空"})
    if not validate_project_name(project_name):
        return JSONResponse(status_code=400, content={"error": "项目名不合法，请使用字母、数字、下划线或连字符"})
    if not requirement:
        return JSONResponse(status_code=400, content={"error": "请输入需求描述"})

    cfg = load_config("config/config.yaml")
    workspace_root = cfg.get("workspace", {}).get("output_dir", "./workspace")

    # 项目若不存在则创建
    project_path = PM.find_project_by_name(project_name, workspace_root)
    if not project_path:
        os.makedirs(workspace_root, exist_ok=True)
        project_path = os.path.join(workspace_root, project_name)
        os.makedirs(project_path, exist_ok=True)
        pm = PM(project_path)

        pm.init(
            name=display_name or project_name,
            description=requirement,
            git_enabled=True,
        )

    # 并发守卫
    abs_path = os.path.abspath(project_path)
    with sessions_lock:
        running = [
            sid for sid, s in sessions.items()
            if s.get("status") == "running"
            and os.path.abspath(s.get("workspace_dir", "")) == abs_path
        ]
    if running:
        return JSONResponse(status_code=409, content={
            "error": f"项目 [{project_name}] 正在执行中",
            "running_sessions": running,
        })

    # 复用 /run 端点逻辑：直接转发给 run_project
    from fastapi import Request as FastAPIRequest
    import json as _json

    class _FakeRequest:
        async def json(self):
            return {"requirement": requirement, "project_name": project_name}

    resp = await run_project(_FakeRequest())
    if isinstance(resp, JSONResponse):
        return resp
    return {**resp, "project_name": project_name}


# ==================== S-002: 计划审批 ====================

@router.post("/sessions/{session_id}/approve-plan")
async def approve_plan_api(session_id: str, request: Request):
    """S-002: 用户审批 Planning 输出，批准或拒绝后继续/终止执行。

    Body:
        approved: bool  (true=批准继续, false=拒绝终止)
        feedback: str   (可选，拒绝时的反馈原因)
    """
    from autoc.core.orchestrator.gates import set_approval_result, has_approval_gate

    data = await request.json()
    approved = bool(data.get("approved", True))
    feedback = data.get("feedback", "").strip()

    with sessions_lock:
        session = sessions.get(session_id)
    if not session:
        return JSONResponse(status_code=404, content={"error": "会话不存在"})

    if not has_approval_gate(session_id):
        return JSONResponse(status_code=400, content={"error": "当前阶段不需要计划审批"})

    ok = set_approval_result(session_id, approved, feedback)
    if not ok:
        return JSONResponse(status_code=400, content={"error": "审批门已关闭或已超时"})

    return {"success": True, "approved": approved}
