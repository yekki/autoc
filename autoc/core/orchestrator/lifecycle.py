"""项目生命周期管理 — 工作区/Checkpoint/初始化/收尾/经验/预览

从 orchestrator.py 拆分，负责项目级别的创建、恢复、收尾流程。
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from datetime import datetime
from typing import TYPE_CHECKING

from rich.console import Console

from autoc.core.project.memory import SharedMemory, TaskStatus
from autoc.core.project.models import ProjectStatus
from .gates import AUTOC_INTERNAL_FILES

if TYPE_CHECKING:
    from .facade import Orchestrator

console = Console()
logger = logging.getLogger("autoc.lifecycle")


# ==================== 工作区管理 ====================

def check_workspace(orc: Orchestrator, clean: bool = False) -> bool:
    if not os.path.exists(orc.workspace_dir):
        os.makedirs(orc.workspace_dir, exist_ok=True)
        return True

    items = [
        f for f in os.listdir(orc.workspace_dir)
        if not f.startswith(".") and f != "__pycache__"
    ]

    if not items:
        return True

    if clean:
        console.print(f"[yellow]🧹 清理工作区: {orc.workspace_dir}[/yellow]")
        # 安全策略：容器仅随项目删除时一并清理，此处只断开引用
        try:
            orc.sandbox.detach()
        except Exception:
            pass
        for item in os.listdir(orc.workspace_dir):
            if item.startswith("."):
                continue
            path = os.path.join(orc.workspace_dir, item)
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            else:
                try:
                    os.remove(path)
                except OSError:
                    pass
        return True

    console.print(
        f"[yellow]⚠️  工作区非空 ({len(items)} 项): {orc.workspace_dir}\n"
        f"   提示: 使用 --clean 参数可自动清理[/yellow]"
    )
    return True


def workspace_has_project_files(orc: Orchestrator) -> bool:
    """检查工作区是否有真正的项目文件（排除 AutoC 内部文件和 .git）"""
    try:
        for item in os.listdir(orc.workspace_dir):
            if item in AUTOC_INTERNAL_FILES:
                continue
            if item.startswith(".git") or item.startswith(".autoc"):
                continue
            return True
    except OSError:
        pass
    return False


def clean_project_files(orc: Orchestrator) -> int:
    """清理工作区中的项目文件，保留 AutoC 内部文件和 .git 目录"""
    _keep = AUTOC_INTERNAL_FILES | {".autoc"}
    cleaned = 0
    try:
        for item in os.listdir(orc.workspace_dir):
            if item in _keep or item.startswith(".git") or item.startswith(".autoc"):
                continue
            path = os.path.join(orc.workspace_dir, item)
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    os.remove(path)
                cleaned += 1
            except OSError as e:
                logger.warning(f"清理文件失败 {item}: {e}")
    except OSError as e:
        logger.error(f"清理工作区失败: {e}")
    if cleaned:
        console.print(f"[cyan]🧹 已清理 {cleaned} 个项目文件/目录[/cyan]")
    return cleaned


def scan_workspace_files_into_memory(orc: Orchestrator) -> None:
    """扫描工作区目录，将已存在的文件注册到 memory.files"""
    if not os.path.isdir(orc.workspace_dir):
        return
    _skip_dirs = {
        ".git", "__pycache__", "node_modules", ".venv", "venv",
        ".pytest_cache", ".mypy_cache", "dist", "build",
    }
    _skip_files = AUTOC_INTERNAL_FILES | {".DS_Store"}
    for root, dirs, files in os.walk(orc.workspace_dir):
        dirs[:] = [d for d in dirs if d not in _skip_dirs and not d.startswith(".")]
        for filename in files:
            if filename in _skip_files or filename.startswith("."):
                continue
            abs_path = os.path.join(root, filename)
            rel_path = os.path.relpath(abs_path, orc.workspace_dir)
            if rel_path not in orc.memory.files:
                orc.memory.register_file(rel_path, description="workspace file", created_by="scan")


# ==================== Checkpoint ====================

def save_checkpoint(orc: Orchestrator, phase: str):
    if not orc.enable_checkpoint:
        return
    filepath = os.path.join(orc.checkpoint_dir, "memory_state.json")
    orc.memory.save_state(filepath)

    # 同步保存对话快照索引到 checkpoint 目录
    if hasattr(orc, "conversation_store") and orc.conversation_store:
        _save_conversation_index(orc)

    logger.info(f"Checkpoint 已保存 @ {phase}")


def _save_conversation_index(orc: Orchestrator):
    """将 ConversationStore 的统计信息附加到 checkpoint，
    便于 resume 时定位到正确的 session"""
    import json
    index_path = os.path.join(orc.checkpoint_dir, "conversation_index.json")
    try:
        stats = orc.conversation_store.stats
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"对话索引保存失败: {e}")


def load_checkpoint(orc: Orchestrator) -> bool:
    filepath = os.path.join(orc.checkpoint_dir, "memory_state.json")
    if os.path.exists(filepath):
        if orc.memory.load_state(filepath):
            console.print("[green]📂 已从 checkpoint 恢复状态[/green]")
            # 恢复对话断点续传上下文
            _load_conversation_resume_context(orc)
            return True
    return False


def _load_conversation_resume_context(orc: Orchestrator):
    """从 ConversationStore 加载断点续传上下文，注入到 Agent"""
    if not hasattr(orc, "conversation_store") or not orc.conversation_store:
        return
    for agent_name, agent in [("code_act", orc.code_act_agent)]:
        resume_ctx = orc.conversation_store.get_resume_context(agent.name)
        if resume_ctx:
            console.print(
                f"[cyan]📝 {agent.name} 对话上下文已恢复 "
                f"(快照 {resume_ctx['snapshot_id']}, "
                f"{resume_ctx['message_count']} 条消息)[/cyan]"
            )
            agent._conversation_resume_context = resume_ctx


# ==================== 项目初始化 / 恢复 ====================

def ensure_project_metadata(orc: Orchestrator, requirement: str):
    if not orc.project_manager.exists():
        default_name = os.path.basename(orc.file_ops.workspace_dir) or "autoc-project"
        orc.project_manager.init(
            name=default_name,
            description=requirement[:200],
            git_enabled=orc.git_ops is not None,
        )
        logger.info("项目元数据已自动初始化")


def try_restore_existing_tasks(orc: Orchestrator, incremental: bool) -> bool:
    """尝试恢复已有 PLAN.md 或任务列表。返回是否应跳过规划阶段。"""

    # 优先检查 PLAN.md（新架构）
    plan_path = os.path.join(orc.workspace_dir, "PLAN.md")
    if os.path.exists(plan_path):
        try:
            with open(plan_path, "r", encoding="utf-8") as f:
                plan_md = f.read()
            if plan_md.strip():
                orc.memory.set_plan(plan_md, source=orc.memory.plan_source or "primary")
                console.print("[cyan]📋 检测到已有 PLAN.md，跳过规划阶段[/cyan]")
                if incremental:
                    console.print("[cyan]📋 增量模式: 将为新需求重新规划...[/cyan]")
                    return False
                return True
        except Exception as e:
            logger.warning(f"读取 PLAN.md 失败: {e}")

    return False


def restore_tasks_from_file(orc: Orchestrator, tasks_data: list[dict]):
    """从 DB 恢复任务状态到共享记忆"""
    from autoc.core.project.memory import Task, ProjectPlan

    tasks = []
    for td in tasks_data:
        status = TaskStatus.COMPLETED if td.get("passes", False) else TaskStatus.PENDING
        task = Task(
            id=td.get("id", ""),
            title=td.get("title", ""),
            description=td.get("description", ""),
            status=status,
            priority=td.get("priority", 1),
            dependencies=td.get("dependencies", []),
            files=td.get("files", []),
            verification_steps=td.get("verification_steps", []),
            passes=td.get("passes", False),
            feature_tag=td.get("feature_tag", ""),
        )
        tasks.append(task)

    if not orc.memory.project_plan:
        plan = ProjectPlan(
            project_name="(从任务列表恢复)",
            tasks=tasks,
        )
        orc.memory.set_project_plan(plan)
    else:
        for task in tasks:
            orc.memory.tasks[task.id] = task

    console.print(
        f"  📋 已恢复 {len(tasks)} 个任务 "
        f"({sum(1 for t in tasks if t.passes)} 已通过, "
        f"{sum(1 for t in tasks if not t.passes)} 待完成)"
    )


def run_from_checkpoint(orc: Orchestrator, start_time: float) -> dict:
    from autoc.core.orchestrator.scheduler import run_dev_and_test

    orc.presenter.print_header(orc.memory.requirement, orc._get_enabled_features())

    plan_md = orc.memory.plan_md
    if not plan_md:
        console.print("[yellow]⚠️  无项目计划，从头开始[/yellow]")
        return orc.run(orc.memory.requirement, resume=False)

    # 确保沙箱在恢复场景下也能就绪
    orc.init_sandbox_after_planning()

    try:
        run_dev_and_test(orc, plan_md)
    except Exception as e:
        logger.exception("恢复执行异常: %s", e)

    elapsed = time.time() - start_time
    result = generate_summary(orc, elapsed)
    orc.presenter.print_summary(result, elapsed)
    orc._emit("summary", **result)
    save_checkpoint(orc, "completed")
    return result


# ==================== 收尾 / 总结 ====================

def _aggregate_llm_tokens(orc: Orchestrator) -> tuple[int, int, int]:
    """聚合所有 Agent 的 prompt/completion/cached tokens（去重）"""
    seen: set[int] = set()
    prompt = completion = cached = 0
    llm_list = [orc.llm_planner, orc.llm_coder, orc.llm_helper]
    if orc.critique:
        llm_list.append(orc.llm_critique)
    for llm in llm_list:
        if id(llm) not in seen:
            seen.add(id(llm))
            prompt += getattr(llm, "prompt_tokens", 0)
            completion += getattr(llm, "completion_tokens", 0)
            cached += getattr(llm, "cached_tokens", 0)
    return prompt, completion, cached


def finalize(orc: Orchestrator, elapsed: float, requirement: str) -> dict:
    """收尾: 记录进度、经验、项目元数据，输出总结"""
    total = len(orc.memory.tasks)
    verified = len(orc.memory.get_verified_tasks()) if total > 0 else 0
    completed = len(orc.memory.get_tasks_by_status(TaskStatus.COMPLETED)) if total > 0 else 0

    if orc.progress_tracker and total > 0:
        orc.progress_tracker.write_entry(
            title=f"Session 完成 (验证 {verified}/{total})",
            content=orc.memory.get_summary(),
            notes=generate_notes_for_next_session(orc),
        )

    try:
        orc.project_manager.update_progress(
            total_tasks=total, completed_tasks=completed, verified_tasks=verified,
        )
    except Exception as e:
        logger.warning(f"update_progress 失败（项目可能未初始化）: {e}")

    exec_success = getattr(orc, "_execution_success", None)
    try:
        if exec_success is not None:
            if not exec_success:
                orc.project_manager.update_status(ProjectStatus.INCOMPLETE)
        elif not (verified == total and total > 0):
            orc.project_manager.update_status(ProjectStatus.INCOMPLETE)
    except Exception as e:
        logger.warning(f"update_status 失败（项目可能未初始化）: {e}")

    try:
        result = generate_summary(orc, elapsed)
    except Exception as e:
        logger.error(f"生成总结失败: {e}")
        result = {
            "success": verified == total and total > 0,
            "partial_success": not (verified == total and total > 0) and verified > 0,
            "summary": f"总结生成异常: {e}",
            "files": list(orc.memory.files.keys()),
            "tasks_completed": completed,
            "tasks_total": total,
            "tasks_verified": verified,
            "elapsed_seconds": elapsed,
            "total_tokens": orc.total_tokens,
            "failure_reason": str(e),
        }
    _current_version = getattr(orc, '_pending_version', None) or orc.project_manager.get_version()
    _req_type = getattr(orc, '_requirement_type', 'primary')
    result["version"] = _current_version
    result["requirement_type"] = _req_type
    orc.presenter.print_summary(result, elapsed)
    orc._emit("summary", **result)

    # --- 非关键操作：失败不能阻断 token_session / done 事件 ---
    try:
        if orc.git_ops:
            if result["success"]:
                orc.git_ops.commit("feat: project complete - all tests passed")
            else:
                orc.git_ops.commit("wip: project incomplete - needs attention")
    except Exception as e:
        logger.warning(f"Git 提交失败（不影响成本上报）: {e}")

    try:
        if orc.experience and (orc.memory.project_plan or orc.memory.plan_md):
            record_experience(orc, result, elapsed)
    except Exception as e:
        logger.warning(f"经验记录失败（不影响成本上报）: {e}")

    # F4: UserProfile 记录项目结果，更新用户偏好
    try:
        if hasattr(orc, "user_profile") and orc.user_profile:
            orc.user_profile.record_project_result(result.get("success", False))
    except Exception as e:
        logger.warning(f"UserProfile 记录失败: {e}")

    # F3: EventLog session 结束统计
    try:
        if hasattr(orc, "event_log") and orc.event_log:
            event_stats = orc.event_log.stats
            logger.info(f"EventLog 统计: {event_stats}")
            orc.event_log.flush()
    except Exception as e:
        logger.warning(f"EventLog 统计失败: {e}")

    session_tokens = orc.total_tokens
    session_ts = datetime.now().isoformat()

    _detected_tech: list[str] = []
    try:
        _detected_tech = detect_tech_stack_from_workspace(orc.workspace_dir)
        if _detected_tech:
            orc.project_manager.update_metadata(tech_stack=_detected_tech)
            logger.info(f"技术栈标签（自动检测）: {_detected_tech}")
    except Exception as e:
        logger.warning(f"技术栈自动检测失败: {e}")

    try:
        orc.project_manager.record_session(
            requirement=requirement,
            success=result["success"],
            tasks_completed=result["tasks_completed"],
            tasks_total=result["tasks_total"],
            elapsed_seconds=elapsed,
            notes=generate_notes_for_next_session(orc),
            total_tokens=session_tokens,
            agent_tokens=collect_agent_tokens(orc),
            failure_reason=result.get("failure_reason", ""),
            session_id=orc.session_id,
            tech_stack=_detected_tech,
        )
    except Exception as e:
        logger.warning(f"Session 记录失败（不影响成本上报）: {e}")

    try:
        all_tasks = list(orc.memory.tasks.values())
        orc.project_manager.save_version_snapshot(
            version=_current_version,
            requirement_type=_req_type,
            requirement=requirement,
            tech_stack=_detected_tech,
            tasks=[{"id": t.id, "title": t.title,
                    "status": t.status.value if hasattr(t.status, 'value') else str(t.status),
                    "passes": t.passes,
                    "error": t.error if hasattr(t, 'error') and t.error else ""}
                   for t in all_tasks],
            success=result["success"],
            total_tokens=session_tokens,
            elapsed_seconds=elapsed,
            started_at=time.time() - elapsed,
            ended_at=time.time(),
        )
    except Exception as e:
        logger.warning(f"版本快照保存失败（不影响主流程）: {e}")

    try:
        if result["success"]:
            orc._emit("execution_complete", tasks_verified=verified, tasks_total=total)
        else:
            all_tasks = list(orc.memory.tasks.values())
            passed_tasks = [
                {"id": t.id, "title": t.title}
                for t in all_tasks if t.passes
            ]
            orc._emit("execution_failed", tasks_verified=verified, tasks_total=total,
                       failure_reason=result.get("failure_reason", ""),
                       recovery_suggestions=result.get("recovery_suggestions", []),
                       partial_success=result.get("partial_success", False),
                       passed_tasks=passed_tasks)
    except Exception as e:
        logger.warning(f"execution_complete/failed 事件发射失败: {e}")

    # --- 关键路径：token_session 必须发出，前端依赖它更新成本数据 ---
    emit_token_session(
        orc, requirement_label=requirement,
        total_tokens=session_tokens, elapsed_seconds=elapsed,
        success=result["success"], timestamp=session_ts,
        version=_current_version, requirement_type=_req_type,
    )

    # Token 成本统计
    try:
        from autoc.core.analysis.token_stats import TokenStats
        token_stats = TokenStats(orc.project_manager)
        cost_info = token_stats.format_summary()
        if cost_info:
            console.print(f"\n[dim]💰 Token 成本统计:\n{cost_info}[/dim]")
    except Exception:
        pass

    save_checkpoint(orc, "completed")

    # 复用 TEST 阶段已启动的预览，验活后复用，失效则重启
    from autoc.core.runtime.preview import PreviewManager as _PM
    preview_info = orc._preview_info if getattr(orc, '_preview_info', None) else None
    if preview_info and preview_info.get("available") and preview_info.get("url"):
        if orc.preview_manager and _PM._check_http_reachable(preview_info["url"]):
            logger.info("复用 TEST 阶段已启动的预览（health check 通过）")
        else:
            logger.warning("缓存的预览 URL 已失效，重新启动")
            preview_info = try_start_preview(orc)
            if preview_info and preview_info.get("available"):
                orc._preview_info = preview_info
    else:
        preview_info = try_start_preview(orc)
        if preview_info and preview_info.get("available"):
            orc._preview_info = preview_info

    if preview_info and preview_info.get("available"):
        result["preview"] = preview_info
        orc._emit("preview_ready", **preview_info)

    # 自动生成文档
    if result.get("success"):
        try:
            from autoc.core.doc_generator import generate_and_save
            readme_path = generate_and_save(orc.workspace_dir)
            if readme_path:
                console.print(f"[dim]📝 README.md 已自动生成[/dim]")
        except Exception:
            pass

    logger.info("一项目一容器: 保留 Docker 容器供预览/调试/重跑")

    emit_done(orc, result)
    return result


def emit_done(orc: Orchestrator, result: dict) -> None:
    """发射 done 终结事件并标记 session 完成。

    所有操作路径（run / resume / quick_fix 等）必须在结束时调用此函数，
    否则前端 isRunning 永远不会置为 false。
    """
    agg_prompt, agg_completion, agg_cached = _aggregate_llm_tokens(orc)
    all_tasks_snapshot = [
        {"id": t.id, "title": t.title,
         "status": t.status.value if hasattr(t.status, 'value') else str(t.status),
         "passes": t.passes,
         "error": t.error if hasattr(t, 'error') and t.error else "",
         "tokens_used": getattr(t, 'tokens_used', 0),
         "elapsed_seconds": getattr(t, 'elapsed_seconds', 0)}
        for t in orc.memory.tasks.values()
    ]
    preview_errors = getattr(orc, '_preview_console_errors', [])[:20]
    try:
        orc._emit("done",
                  success=result.get("success", False),
                  summary=result.get("summary", ""),
                  tasks_completed=result.get("tasks_completed", 0),
                  tasks_total=result.get("tasks_total", 0),
                  tasks_verified=result.get("tasks_verified", 0),
                  total_tokens=result.get("total_tokens", 0),
                  elapsed_seconds=result.get("elapsed_seconds", 0),
                  version=result.get("version", ""),
                  failure_reason=result.get("failure_reason", ""),
                  recovery_suggestions=result.get("recovery_suggestions", []),
                  prompt_tokens=agg_prompt,
                  completion_tokens=agg_completion,
                  cached_tokens=agg_cached,
                  tasks=all_tasks_snapshot,
                  preview_errors=preview_errors)
    except Exception as e:
        logger.warning(f"done 事件发射失败: {e}")
    finally:
        orc._finish_session(result.get("success", False))


def try_start_preview(orc: Orchestrator, **_kw) -> dict | None:
    """尝试启动项目预览，预览 URL 通过 SSE 事件推送给 Web 前端"""
    from autoc.core.runtime.preview import ProjectType

    if not orc.preview_manager:
        return None

    preview_mode = orc._preview_config.get("auto_preview", "auto")
    if preview_mode == "off":
        return None

    project_type, command, port = orc.preview_manager.detect_project()

    # 通过技术栈适配器增强检测
    if project_type == ProjectType.UNKNOWN or project_type == ProjectType.LIBRARY:
        try:
            from autoc.stacks._registry import parse_project_context
            ctx = parse_project_context(orc.workspace_dir)
            if ctx.project_type in ("web_frontend", "web_fullstack", "web_backend"):
                command = ctx.start_command or command
                port = ctx.default_port or port
                if ctx.project_type == "web_frontend":
                    project_type = ProjectType.WEB_FRONTEND
                elif ctx.project_type == "web_backend":
                    project_type = ProjectType.WEB_BACKEND
                else:
                    project_type = ProjectType.WEB_FULLSTACK
                logger.info(f"技术栈适配器补充检测: {ctx.language}/{ctx.framework} → {project_type.value}")
        except Exception:
            pass

    logger.info(f"检测到项目类型: {project_type.value}, 命令: {command}, 端口: {port}")

    if project_type in (ProjectType.UNKNOWN, ProjectType.LIBRARY, ProjectType.GUI_APP):
        if project_type == ProjectType.GUI_APP:
            logger.info("检测到 GUI 应用（pygame/tkinter 等），跳过容器内预览")
        return None

    try:
        if project_type == ProjectType.CLI_TOOL:
            info = orc.preview_manager.run_cli_demo(command, sandbox=orc.sandbox)
        elif orc._preview_config.get("runtime") == "e2b":
            from autoc.core.runtime.runtime import create_runtime
            runtime = create_runtime(
                orc.workspace_dir, config={"preview": orc._preview_config},
                sandbox=orc.sandbox,
            )
            info = orc.preview_manager.start_cloud(runtime, command, port)
        else:
            info = orc.preview_manager.start_docker(
                orc.sandbox, command, port,
            )

        console.print()
        if info.available:
            if info.url:
                console.print(f"[bold green]🌐 预览已启动: {info.url}[/bold green]")
            else:
                console.print(f"[bold green]🔧 CLI 试运行完成[/bold green]")
                if info.message:
                    console.print(f"[dim]{info.message[:500]}[/dim]")
        else:
            console.print(f"[yellow]⚠️ 预览未启动: {info.message}[/yellow]")

        return {
            "available": info.available,
            "project_type": info.project_type.value,
            "url": info.url,
            "port": info.port,
            "command": info.command,
            "runtime": info.runtime,
            "message": info.message,
        }
    except Exception as e:
        logger.warning(f"预览启动失败: {e}")
        return None


# ==================== 辅助函数 ====================

def generate_notes_for_next_session(orc: Orchestrator) -> str:
    notes_parts = []

    unfinished = [t for t in orc.memory.tasks.values() if not t.passes]
    if unfinished:
        notes_parts.append(f"待完成任务: {len(unfinished)} 个")
        for t in unfinished[:5]:
            notes_parts.append(f"  - [{t.id}] {t.title} (状态: {t.status.value})")

    blocked = orc.memory.get_blocked_tasks()
    if blocked:
        notes_parts.append(f"\n⚠️ 阻塞任务 ({len(blocked)} 个):")
        for t in blocked:
            notes_parts.append(f"  - [{t.id}] {t.title}: {t.block_reason[:100]}")

    open_bugs = orc.memory.get_open_bugs()
    if open_bugs:
        notes_parts.append(f"\n🐛 未修复 Bug ({len(open_bugs)} 个):")
        for b in open_bugs[:5]:
            notes_parts.append(f"  - [{b.severity}] {b.title}")

    return "\n".join(notes_parts) if notes_parts else "所有任务已完成"


def record_experience(orc: Orchestrator, result: dict, elapsed: float):
    if not orc.experience or not orc.memory.project_plan:
        return

    plan = orc.memory.project_plan
    bugs_found = [
        {"title": b.title, "description": b.description, "suggested_fix": b.suggested_fix}
        for b in orc.memory.bug_reports.values()
    ]
    bugs_fixed = [
        {"title": b.title, "description": b.description, "suggested_fix": b.suggested_fix}
        for b in orc.memory.bug_reports.values() if b.status == "fixed"
    ]

    if result["success"]:
        orc.experience.record_project(
            requirement=orc.memory.requirement,
            project_name=plan.project_name,
            tech_stack=plan.tech_stack,
            architecture=plan.architecture,
            directory_structure=plan.directory_structure,
            files=list(orc.memory.files.keys()),
            bugs_found=bugs_found,
            bugs_fixed=bugs_fixed,
            quality_score=result.get("quality_score", 8),
            success=True,
            elapsed_seconds=elapsed,
            total_tokens=result.get("total_tokens", 0),
        )
        console.print("[dim]📚 成功经验已记录[/dim]")
    else:
        bugs_unresolved = [
            {"title": b.title, "description": b.description}
            for b in orc.memory.get_open_bugs()
        ]
        orc.experience.record_failure(
            requirement=orc.memory.requirement,
            project_name=plan.project_name,
            failure_reason=result.get("summary", "未知原因")[:300],
            rounds_attempted=orc.max_rounds,
            total_tokens=result.get("total_tokens", 0),
            elapsed_seconds=elapsed,
            bugs_unresolved=bugs_unresolved,
        )
        console.print("[dim]📚 失败经验已记录，将帮助后续避免类似问题[/dim]")


def collect_agent_tokens(orc: Orchestrator) -> dict[str, int]:
    """收集各 Agent 的 token 消耗，按前端三分类输出: helper / coder / critique。

    - helper: RequirementRefiner + ask_helper 咨询（llm_helper）
    - coder:  PlanningAgent + CodeActAgent（llm_planner / llm_coder，常共享同一实例）
    - critique: CritiqueAgent（llm_critique）

    当 planner 与 coder 共享同一 LLM 实例时，优先使用 per-tag 计数器拆分；
    若 per-tag 数据不可用，回退到合并计入 coder。
    """
    _AGENT_CLASS_MAP = {
        "planner": "PlanningAgent",
        "coder": "CodeActAgent",
        "critique": "CritiqueAgent",
    }
    # llm_helper: RequirementRefiner（直接调用，不设 tag）+ CodeActAgent._helper_llm
    # llm_planner: PlanningAgent（tag="PlanningAgent"），未配置时 fallback 到 llm_coder
    # llm_coder: CodeActAgent（tag="CodeActAgent"）
    # llm_critique: CritiqueAgent（tag="CritiqueAgent"）
    agents = [
        ("helper", orc.llm_helper),
        ("planner", orc.llm_planner),
        ("coder", orc.llm_coder),
        ("critique", orc.llm_critique),
    ]

    # 按 LLM 实例分组（共享实例的 agent 归入同一组）
    instance_groups: dict[int, tuple[list[str], object]] = {}
    for name, llm in agents:
        lid = id(llm)
        if lid in instance_groups:
            instance_groups[lid][0].append(name)
        else:
            instance_groups[lid] = ([name], llm)

    raw: dict[str, int] = {}
    prompt_total = 0
    completion_total = 0
    cached_total = 0
    call_count = 0
    error_count = 0

    for _lid, (names, llm) in instance_groups.items():
        prompt_total += getattr(llm, "prompt_tokens", 0)
        completion_total += getattr(llm, "completion_tokens", 0)
        cached_total += getattr(llm, "cached_tokens", 0)
        call_count += len(getattr(llm, "call_log", []))
        error_count += getattr(llm, "error_calls", 0)

        if len(names) > 1:
            tag_tokens = getattr(llm, "_tag_tokens", {})
            split_ok = False
            if tag_tokens:
                for agent_name in names:
                    class_name = _AGENT_CLASS_MAP.get(agent_name)
                    if class_name and class_name in tag_tokens:
                        td = tag_tokens[class_name]
                        raw[agent_name] = td.get("total", 0)
                        split_ok = True
                    elif split_ok:
                        raw[agent_name] = 0
            if not split_ok:
                # per-tag 不可用，所有 token 计入组内最后一个 agent
                # 典型场景: planner+coder 共享 → 全部计入 coder
                for n in names[:-1]:
                    raw[n] = 0
                raw[names[-1]] = llm.total_tokens
        else:
            raw[names[0]] = llm.total_tokens

    # 合并为前端三分类: planner 归入 coder
    result: dict[str, int] = {}
    result["helper"] = raw.get("helper", 0)
    result["coder"] = raw.get("coder", 0) + raw.get("planner", 0)
    result["critique"] = raw.get("critique", 0)

    result["_prompt_tokens"] = prompt_total
    result["_completion_tokens"] = completion_total
    result["_cached_tokens"] = cached_total
    result["_call_count"] = call_count
    result["_error_calls"] = error_count
    return result


def emit_token_session(
    orc: Orchestrator, requirement_label: str,
    total_tokens: int, elapsed_seconds: float,
    success: bool, timestamp: str,
    version: str = "", requirement_type: str = "",
):
    """通过 SSE 推送本次执行的 token 记录给前端"""
    agent_tokens = collect_agent_tokens(orc)
    ver = version or getattr(orc, '_pending_version', None) or orc.project_manager.get_version()
    orc._emit(
        "token_session",
        requirement=requirement_label,
        total_tokens=total_tokens,
        prompt_tokens=agent_tokens.get("_prompt_tokens", 0),
        completion_tokens=agent_tokens.get("_completion_tokens", 0),
        cached_tokens=agent_tokens.get("_cached_tokens", 0),
        elapsed_seconds=elapsed_seconds,
        success=success,
        timestamp=timestamp,
        agent_tokens=agent_tokens,
        version=ver,
        requirement_type=requirement_type or "primary",
    )


def _diagnose_root_cause(
    success: bool, exit_reason: str | None, dev_iterations: int,
    completed: int, total: int, bugs_open: int, blocking_bugs: int,
    file_count: int, passed_tests: int, total_tests: int,
) -> str | None:
    """从执行数据推断失败的根本原因（因果诊断，而非结果复述）"""
    if success:
        return None

    if dev_iterations == 0 and file_count == 0:
        if exit_reason == "all_stories_passed":
            return "检测到残留状态导致系统误判为已完成，Developer 阶段从未执行"
        return "Developer 阶段未执行，系统在规划阶段后异常退出"

    if exit_reason == "rate_limited":
        return "API 调用频率超出限制，系统等待后仍无法继续，已暂停执行"

    if exit_reason == "circuit_breaker":
        return "连续多次迭代失败触发熔断保护，执行被自动终止"

    if exit_reason == "max_iterations":
        return "达到最大迭代次数限制，仍有任务未完成"

    if exit_reason == "no_progress":
        return "多次迭代无实质进展，系统主动退出避免资源浪费"

    if blocking_bugs > 0:
        return f"存在 {blocking_bugs} 个高优先级 Bug 未修复，阻塞了验证流程"

    if bugs_open > 0 and completed > 0:
        return f"{completed} 个任务已完成但验证受阻，{bugs_open} 个 Bug 待修复"

    if total_tests > 0 and passed_tests == 0:
        return "所有测试均失败，代码未通过验证"

    if completed == 0 and file_count > 0:
        return f"生成了 {file_count} 个文件但代码编写未完成，可能是开发阶段中断"

    if completed > 0 and completed < total:
        return f"部分任务完成 ({completed}/{total})，剩余任务在开发或测试阶段失败"

    return None


def generate_summary(orc: Orchestrator, elapsed: float) -> dict:
    all_tasks = list(orc.memory.tasks.values())
    total_tasks = len(all_tasks)
    # passes=True 的任务也算 completed（兼容 auto-verify 路径未更新 status 的情况）
    completed = len([t for t in all_tasks if t.status == TaskStatus.COMPLETED or t.passes])
    failed = len([t for t in all_tasks if t.status == TaskStatus.FAILED and not t.passes])
    blocked = len([t for t in all_tasks if t.dependencies and any(
        orc.memory.tasks.get(d) and orc.memory.tasks[d].status != TaskStatus.COMPLETED
        for d in t.dependencies
    )])
    verified = len([t for t in all_tasks if t.passes])
    total_tests = len(orc.memory.test_results)
    passed_tests = len([t for t in orc.memory.test_results if t.passed])
    open_bugs = orc.memory.get_open_bugs()
    blocking_bugs = [b for b in open_bugs if b.severity in ("critical", "high")]
    files = list(orc.memory.files.keys())
    tokens = orc.total_tokens

    # 新架构：无任务时由 _execution_success 标记；旧架构：全部任务验证通过
    if total_tasks > 0:
        success = verified == total_tasks
        partial_success = not success and verified > 0
    else:
        success = getattr(orc, "_execution_success", False)
        partial_success = False

    git_log = orc.git_ops.log(100) if orc.git_ops else ""
    git_commits = len(git_log.strip().split("\n")) if git_log.strip() else 0

    cache_stats: dict[str, int] = {}
    for llm in (orc.llm_coder, orc.llm_helper):
        cs = llm.cache_stats
        for k in ("hits", "misses"):
            cache_stats[k] = cache_stats.get(k, 0) + cs[k]

    agent_tokens = collect_agent_tokens(orc)
    prompt_total = agent_tokens.get("_prompt_tokens", 0)
    completion_total = agent_tokens.get("_completion_tokens", 0)
    cached_total = agent_tokens.get("_cached_tokens", 0)
    call_count = agent_tokens.get("_call_count", 0)
    error_calls = agent_tokens.get("_error_calls", 0)
    pc_ratio = (
        f"{prompt_total / completion_total:.1f}:1"
        if completion_total > 0 else "N/A"
    )
    efficiency = (
        f"{completion_total / tokens * 100:.1f}%"
        if tokens > 0 else "N/A"
    )
    # GLM cache read 约为 input 价格的 20%，节省 80%
    cache_saving = ""
    if cached_total > 0 and prompt_total > 0:
        cache_hit_pct = cached_total * 100 // prompt_total
        from autoc.core.analysis.token_stats import TokenStats
        try:
            ts = TokenStats(orc.project_manager)
            saved_usd = ts.estimate_cache_savings(cached_total, orc.llm_default.config.model)
            cache_saving = f", 缓存命中 {cache_hit_pct}% (省 ${saved_usd:.3f})"
        except Exception:
            cache_saving = f", 缓存命中 {cache_hit_pct}%"

    calls_info = f", {call_count} 次 API 调用" if call_count > 0 else ""
    errors_info = f", {error_calls} 次失败" if error_calls > 0 else ""

    project_name = "N/A"
    if orc.memory.project_plan:
        project_name = orc.memory.project_plan.project_name
    else:
        _meta = orc.project_manager.load() if orc.project_manager else None
        if _meta and _meta.name:
            project_name = _meta.name

    if total_tasks > 0:
        tasks_line = f"任务: {completed}/{total_tasks} 完成, {failed} 失败, {blocked} 阻塞\n"
        verify_line = f"验证: {verified}/{total_tasks} 通过 (passes)\n"
    else:
        tasks_line = "执行模式: PLAN.md 驱动\n"
        verify_line = ""

    summary = (
        f"项目: {project_name}\n"
        f"{tasks_line}"
        f"{verify_line}"
        f"测试: {passed_tests}/{total_tests} 通过\n"
        f"Bug: {len(open_bugs)} 待修复 ({len(blocking_bugs)} 阻塞性)\n"
        f"文件: {len(files)} 个\n"
        f"Git: {git_commits} 个提交\n"
        f"耗时: {elapsed:.1f}s\n"
        f"Token: {tokens} (prompt {prompt_total} / completion {completion_total}, "
        f"比值 {pc_ratio}, 有效率 {efficiency}{cache_saving}{calls_info}{errors_info})\n"
        f"缓存: {cache_stats.get('hits', 0)} 命中 / {cache_stats.get('misses', 0)} 未中"
    )

    loop_result = getattr(orc, "_loop_result", None)
    exit_reason = None
    dev_iterations = 0
    if loop_result:
        exit_reason = loop_result.exit_reason.value if loop_result.exit_reason else None
        dev_iterations = len([
            it for it in loop_result.iterations if it.phase.value == "dev"
        ])
    else:
        dev_iterations = getattr(orc, "_scheduler_dev_iterations", 0)
        exit_reason = getattr(orc, "_scheduler_exit_reason", None)

    # PLAN.md 驱动模式下 memory.tasks 为空，需在计算 failure_reason 前补齐，
    # 避免 total_tasks=0 时 _diagnose_root_cause 得不到调用
    if total_tasks == 0 and getattr(orc, "_execution_success", None) is not None:
        total_tasks = 1
        completed = 1 if success else 0
        verified = 1 if success else 0

    failure_reason = _diagnose_root_cause(
        success, exit_reason, dev_iterations, completed, total_tasks,
        len(open_bugs), len(blocking_bugs), len(files),
        passed_tests, total_tests,
    ) if not success and total_tasks > 0 else None

    result = {
        "success": success,
        "partial_success": partial_success,
        "summary": summary,
        "files": files,
        "tasks_completed": completed,
        "tasks_total": total_tasks,
        "tasks_verified": verified,
        "tasks_blocked": blocked,
        "tests_passed": passed_tests,
        "tests_total": total_tests,
        "bugs_open": len(open_bugs),
        "git_commits": git_commits,
        "elapsed_seconds": elapsed,
        "total_tokens": tokens,
        "agent_tokens": agent_tokens,
        "cache_hits": cache_stats.get("hits", 0),
        "prompt_tokens": prompt_total,
        "completion_tokens": completion_total,
        "cached_tokens": cached_total,
        "call_count": call_count,
        "error_calls": error_calls,
        "token_efficiency": efficiency,
        "exit_reason": exit_reason,
        "dev_iterations": dev_iterations,
        "failure_reason": failure_reason,
    }

    if completion_total > 0 and prompt_total / completion_total > 20:
        logger.warning(
            f"⚠️ Token 效率偏低: prompt/completion = {pc_ratio}, "
            f"有效率 {efficiency}。可能原因: system prompt 过长、工具 schema 过多、"
            f"对话轮数过多导致历史重复传输"
        )

    if not success:
        # _diagnose_failure 提供恢复建议；failure_reason 优先使用精细的 _diagnose_root_cause 结果
        fallback_reason, result["recovery_suggestions"] = \
            _diagnose_failure(completed, total_tasks, verified, failed,
                              blocking_bugs, open_bugs, tokens)
        if not result.get("failure_reason"):
            result["failure_reason"] = fallback_reason

    return result


def _diagnose_failure(
    completed: int, total: int, verified: int, failed: int,
    blocking_bugs: list, open_bugs: list, tokens: int,
) -> tuple[str, list[str]]:
    """分析失败根因并给出恢复建议"""
    suggestions: list[str] = []

    if total == 0:
        return "规划阶段未生成任何任务", ["检查 LLM API Key 是否有效", "查看日志确认规划输出"]

    if completed == 0 and tokens == 0:
        return "LLM API 调用失败，未消耗任何 Token", [
            "检查 API Key 是否有效",
            "确认网络连接正常",
            "查看后端日志获取具体错误信息",
            "点击「重新运行」重新执行",
        ]

    if completed > 0 and tokens > 100_000 and failed > 0:
        reason = f"上下文溢出: 累计 {tokens} Token 超出模型窗口限制，后续任务无法执行"
        suggestions = [
            "减少任务数量，让 PM 合并相关任务",
            "使用更大上下文窗口的模型",
            "尝试 clean 模式重新执行",
        ]
        return reason, suggestions

    if blocking_bugs:
        bug_titles = [b.title[:30] for b in blocking_bugs[:3]]
        reason = f"{len(blocking_bugs)} 个阻塞性 Bug 未修复: {', '.join(bug_titles)}"
        suggestions = [
            "尝试「快速修复」定向修复 Bug",
            "修复后「重测」重新验证",
            "或使用「断点续传」继续上次进度",
        ]
        return reason, suggestions

    if verified < total and verified > 0:
        reason = f"{verified}/{total} 个任务已通过验证，{total - verified} 个待完成"
        suggestions = [
            "尝试「重新运行」重新执行",
            "或「重测」重新验证剩余任务",
            "也可修改需求后重新运行",
        ]
        return reason, suggestions

    if verified < total:
        reason = f"{total - verified}/{total} 个任务未通过验证"
        suggestions = [
            "尝试「重新运行」重新执行",
            "或「重测」重新验证",
            "也可使用「断点续传」继续上次进度",
        ]
        return reason, suggestions

    return "未知原因", ["查看执行日志获取详细信息"]


# ==================== 事后技术栈检测 ====================

_TECH_RULES: list[tuple[str, list[str]]] = [
    # (标签, [匹配文件/内容 glob 规则])
    # 语言
    ("Python", ["*.py"]),
    ("TypeScript", ["*.ts", "*.tsx", "tsconfig.json"]),
    ("JavaScript", ["*.js", "*.jsx"]),
    ("Go", ["go.mod", "*.go"]),
    ("Java", ["*.java", "pom.xml", "build.gradle"]),
    ("Rust", ["Cargo.toml", "*.rs"]),
    # 后端框架（检测依赖文件内容）
    ("FastAPI", ["__fastapi__"]),
    ("Flask", ["__flask__"]),
    ("Django", ["__django__", "manage.py"]),
    ("Express", ["__express__"]),
    ("Spring Boot", ["__spring-boot__"]),
    # 前端框架
    ("React", ["__react__", "__react-dom__"]),
    ("Vue", ["__vue__", "*.vue"]),
    ("Next.js", ["__next__", "next.config.*"]),
    ("Vite", ["vite.config.*"]),
    # 数据库
    ("SQLite", ["__sqlite3__", "__sqlite__", "*.db", "*.sqlite"]),
    ("PostgreSQL", ["__psycopg__", "__asyncpg__", "__pg__"]),
    ("MySQL", ["__mysql__", "__pymysql__"]),
    ("MongoDB", ["__pymongo__", "__mongoose__", "__mongodb__"]),
    ("Redis", ["__redis__", "__ioredis__"]),
    # 工具
    ("Docker", ["Dockerfile", "docker-compose.yml", "docker-compose.yaml"]),
    ("CLI", ["__click__", "__argparse__", "__typer__"]),
]


_DEP_FILES: set[str] = {
    "requirements.txt", "pyproject.toml", "setup.py", "Pipfile",
    "package.json", "go.mod", "Cargo.toml", "pom.xml", "build.gradle",
}

_MAX_DEP_FILE_SIZE = 512 * 1024  # 512 KB


def detect_tech_stack_from_workspace(workspace_dir: str) -> list[str]:
    """扫描工作区文件推断技术栈标签（纯规则，不调用 LLM）"""
    import fnmatch
    import os
    import re

    if not os.path.isdir(workspace_dir):
        return []

    skip_dirs = {".git", "node_modules", "__pycache__", "venv", ".venv", ".autoc", "dist", "build"}
    detected: set[str] = set()

    all_files: set[str] = set()
    dep_content = ""

    for dirpath, dirnames, filenames in os.walk(workspace_dir):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for fname in filenames:
            all_files.add(fname)
            if fname in _DEP_FILES:
                fpath = os.path.join(dirpath, fname)
                try:
                    size = os.path.getsize(fpath)
                    if size <= _MAX_DEP_FILE_SIZE:
                        with open(fpath, encoding="utf-8", errors="ignore") as f:
                            dep_content += f.read().lower() + "\n"
                except Exception:
                    pass

    for tag, patterns in _TECH_RULES:
        for pattern in patterns:
            if pattern.startswith("__") and pattern.endswith("__"):
                keyword = pattern[2:-2]
                if re.search(r'(?:[\s"\'\-/]|^)' + re.escape(keyword) + r'(?:[\s"\'\-/,]|$)', dep_content, re.MULTILINE):
                    detected.add(tag)
                    break
            elif any(c in pattern for c in ("*", "?", "[")):
                if any(fnmatch.fnmatch(f, pattern) for f in all_files):
                    detected.add(tag)
                    break
            else:
                if pattern in all_files:
                    detected.add(tag)
                    break

    if "TypeScript" in detected and "JavaScript" in detected:
        detected.discard("JavaScript")
    html_files = any(f.endswith(".html") for f in all_files)
    css_files = any(f.endswith(".css") for f in all_files)
    if html_files and css_files and ("JavaScript" in detected or "TypeScript" in detected):
        if "React" not in detected and "Vue" not in detected:
            detected.add("HTML/CSS/JS")
            detected.discard("JavaScript")

    priority = [
        "Python", "FastAPI", "Flask", "Django",
        "Node.js", "Express", "Go", "Java", "Spring Boot", "Rust",
        "React", "Vue", "HTML/CSS/JS", "TypeScript", "Next.js", "Vite",
        "SQLite", "PostgreSQL", "MySQL", "MongoDB", "Redis",
        "Docker", "CLI",
    ]
    result = [t for t in priority if t in detected]
    leftover = sorted(detected - set(priority))
    return (result + leftover)[:8]
