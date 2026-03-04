"""操作入口 — quick_fix / resume / revise

从 scheduler.py 拆分，负责非主流程的操作命令。
主流程（refine → PM → Dev/Test）保留在 scheduler.py。
"""

from __future__ import annotations

import logging
import os
import re
import time
from datetime import datetime
from typing import TYPE_CHECKING

from rich.console import Console

from autoc.core.project.models import ProjectStatus, RequirementType, bump_major, bump_minor
from autoc.core.project.state import StateManager
from autoc.core.project import ProjectManager

if TYPE_CHECKING:
    from .facade import Orchestrator

console = Console()
logger = logging.getLogger("autoc.scheduler_ops")


# ==================== 操作：断点恢复 ====================

def execute_resume(orc: Orchestrator) -> dict:
    """从上次中断处恢复执行。

    使用 PLAN.md 恢复 → CodeActAgent → CritiqueAgent 循环。
    若无 PLAN.md 则从头开始。
    """
    from .lifecycle import (
        scan_workspace_files_into_memory,
        generate_summary, collect_agent_tokens, emit_token_session,
        emit_done, ensure_project_metadata,
    )
    from .scheduler import run_dev_and_test

    start_time = time.time()

    # 1. 恢复 PLAN.md
    plan_md = orc.memory.plan_md
    if not plan_md:
        plan_path = os.path.join(orc.workspace_dir, "PLAN.md")
        if os.path.exists(plan_path):
            try:
                with open(plan_path, "r", encoding="utf-8") as f:
                    plan_md = f.read().strip()
                if plan_md:
                    orc.memory.set_plan(plan_md, source=orc.memory.plan_source or "primary")
            except Exception as e:
                logger.warning(f"读取 PLAN.md 失败: {e}")

    if not plan_md:
        pm = ProjectManager(orc.workspace_dir)
        meta = pm.load()
        req = (meta.description if meta else "") or "恢复执行"
        logger.info("无可恢复的 PLAN.md，降级为全新 run: %s", req)
        return orc.run(requirement=req, clean=True)

    scan_workspace_files_into_memory(orc)

    # 1.5. Plan 来源识别：如果当前 plan 来自次需求，提示用户
    if orc.memory.plan_source == "secondary":
        primary_plan = orc.memory.get_primary_plan()
        if primary_plan:
            console.print("[yellow]⚠️  当前 PLAN.md 来自追加功能（次需求），主需求计划已备份在历史中[/yellow]")
            logger.info("Resume 使用的是次需求 plan（plan_source=secondary），主需求 plan 在 plan_history 中")
        orc._emit("resume_plan_source", source="secondary",
                   has_primary_backup=bool(primary_plan))

    # 2. 已完成项目重新执行：重置任务/bug/测试状态，让 loop 从 plan 重新解析
    meta = orc.project_manager.load()
    prev_status = meta.status if meta else None
    is_rerun = prev_status == ProjectStatus.COMPLETED.value
    if is_rerun:
        console.print("[cyan]🔄 重新执行: 按修改后的 PLAN.md 重新开发[/cyan]")
        orc.memory.tasks.clear()
        orc.memory.bug_reports.clear()
        orc.memory.test_results.clear()
        state_mgr = StateManager(orc.workspace_dir)
        if state_mgr.has_prd():
            state_mgr.clear_state_files()
        if orc.progress_tracker:
            old_task_ids = [t["id"] for t in (orc.progress_tracker.load_tasks() or [])]
            if old_task_ids:
                orc.progress_tracker.delete_tasks_by_ids(old_task_ids)
    else:
        console.print("[cyan]🔄 恢复执行: 使用已有 PLAN.md[/cyan]")

    # 3. 恢复项目元数据 + venv
    ensure_project_metadata(orc, orc.memory.requirement or "(恢复执行)")

    orc._emit("resume_start", start_phase="dev")

    # 确保沙箱在恢复场景下也能就绪（与 run_from_checkpoint 保持一致）
    orc.init_sandbox_after_planning()

    # 4. CodeActAgent → CritiqueAgent 循环
    _loop_exception = None
    try:
        run_dev_and_test(orc, plan_md)
    except Exception as e:
        _loop_exception = e
        logger.exception("恢复执行异常: %s", e)
        try:
            orc.project_manager.update_status(ProjectStatus.ABORTED, force=True)
        except Exception:
            pass

    # 5. 收尾（try/finally 保证 emit_done 必定执行，前端不会卡在「执行中」）
    elapsed = time.time() - start_time
    result: dict = {"success": False, "summary": "收尾异常", "elapsed_seconds": elapsed}
    try:
        result = generate_summary(orc, elapsed)
        orc.presenter.print_summary(result, elapsed)
        orc._emit("summary", **result)

        session_tokens = orc.total_tokens
        session_ts = datetime.now().isoformat()
        op_label = "rerun" if is_rerun else "resume"
        req_label = f"[{op_label}] {orc.memory.requirement or '重新执行'}"
        notes_label = "重新执行（修改后的 PLAN.md）" if is_rerun else "恢复执行（PLAN.md 驱动）"
        orc.project_manager.record_session(
            requirement=req_label,
            success=result.get("success", False),
            tasks_completed=result.get("tasks_completed", 0),
            tasks_total=result.get("tasks_total", 0),
            elapsed_seconds=elapsed,
            notes=notes_label,
            total_tokens=session_tokens,
            agent_tokens=collect_agent_tokens(orc),
            failure_reason=result.get("failure_reason", ""),
            session_id=orc.session_id,
        )

        emit_token_session(
            orc, requirement_label=req_label,
            total_tokens=session_tokens, elapsed_seconds=elapsed,
            success=result.get("success", False), timestamp=session_ts,
        )

        if not _loop_exception:
            if result.get("success"):
                orc.project_manager.update_status(ProjectStatus.COMPLETED)
            else:
                orc.project_manager.update_status(ProjectStatus.INCOMPLETE)

        if orc.git_ops:
            if result.get("success"):
                orc.git_ops.commit("feat: resume complete - all tests passed")
                current_version = orc.project_manager.get_version()
                orc.git_ops.tag(f"v{current_version}", f"AutoC: v{current_version} resume 通过")
            else:
                orc.git_ops.commit("wip: resume incomplete")

        from .lifecycle import try_start_preview
        preview_info = try_start_preview(orc)
        if preview_info and preview_info.get("available"):
            orc._preview_info = preview_info
            result["preview"] = preview_info
            orc._emit("preview_ready", **preview_info)

        logger.info("一项目一容器: 保留 Docker 容器供预览/调试/重跑")
    except Exception as e:
        logger.exception("resume 收尾异常: %s", e)
        result.setdefault("success", False)
        result.setdefault("failure_reason", str(e))
        try:
            orc.project_manager.update_status(ProjectStatus.INCOMPLETE, force=True)
        except Exception:
            pass
    finally:
        emit_done(orc, result)
    return result


# ==================== 操作：快速修复 ====================

def execute_quick_fix(
    orc: Orchestrator,
    bug_ids: list[str] | None = None,
    bug_titles: list[str] | None = None,
    bugs_data: list[dict] | None = None,
) -> dict:
    """快速修复指定 bug，不重跑完整测试循环"""
    from .lifecycle import (
        scan_workspace_files_into_memory, restore_tasks_from_file,
        generate_summary, collect_agent_tokens, emit_token_session,
        emit_done,
    )

    start_time = time.time()

    if not orc.memory.plan_md and not orc.memory.project_plan:
        if orc.progress_tracker:
            existing_tasks = orc.progress_tracker.load_tasks()
            if existing_tasks:
                restore_tasks_from_file(orc, existing_tasks)

    scan_workspace_files_into_memory(orc)
    orc.init_sandbox_after_planning()

    if bugs_data:
        for raw in bugs_data:
            if not isinstance(raw, dict):
                continue
            bid = raw.get("id") or f"bug-{raw.get('title', 'unknown')[:20]}"
            if bid not in orc.memory.bug_reports:
                from autoc.core.project.models import BugReport as _BR
                orc.memory.add_bug_report(_BR(
                    id=bid,
                    title=raw.get("title", ""),
                    description=raw.get("description", ""),
                    severity=raw.get("severity", "medium"),
                    file_path=raw.get("file_path", ""),
                    root_cause=raw.get("root_cause", ""),
                    fix_strategy=raw.get("fix_strategy", ""),
                    suggested_fix=raw.get("suggested_fix", ""),
                    affected_functions=raw.get("affected_functions", []),
                    status="open",
                ))

    all_bugs = orc.memory.get_open_bugs()
    if bug_ids:
        target_bugs = [b for b in all_bugs if b.id in bug_ids]
    elif bug_titles:
        title_set = set(bug_titles)
        target_bugs = [b for b in all_bugs if b.title in title_set]
    else:
        target_bugs = list(all_bugs)

    if not target_bugs:
        return {"success": True, "summary": "没有待修复的问题", "fixed": 0, "total": 0}

    orc._emit(
        "quick_fix_start",
        bug_count=len(target_bugs),
        bugs=[{"id": b.id, "title": b.title, "severity": b.severity} for b in target_bugs[:10]],
    )

    def _on_bug_progress(bug, status, idx, total):
        orc._emit("bug_fix_progress", bug_id=bug.id, bug_title=bug.title,
                   status=status, current=idx, total=total)

    fix_agent = orc.code_act_agent.clone()
    fixed = 0
    try:
        fixed = fix_agent.fix_bugs(target_bugs, on_progress=_on_bug_progress)
    except Exception as e:
        logger.error(f"快速修复失败: {e}")

    verified = _quick_verify_for_fix(orc)
    bug_results = []
    for bug in target_bugs:
        mem_bug = orc.memory.bug_reports.get(bug.id)
        if mem_bug and mem_bug.status == "pending_verification":
            if verified:
                orc.memory.update_bug(bug.id, status="fixed")
                bug_results.append({"id": bug.id, "title": bug.title, "status": "fixed"})
            else:
                orc.memory.update_bug(bug.id, status="open")
                bug_results.append({"id": bug.id, "title": bug.title, "status": "unfixed"})
        elif mem_bug and mem_bug.status == "open":
            bug_results.append({"id": bug.id, "title": bug.title, "status": "failed"})
        else:
            st = mem_bug.status if mem_bug else "unknown"
            bug_results.append({"id": bug.id, "title": bug.title, "status": st})

    if orc.code_quality:
        try:
            orc.code_quality.run_all()
        except Exception as e:
            logger.warning(f"格式化失败: {e}")

    bumped_version: str | None = None
    if orc.git_ops:
        orc.git_ops.commit(f"fix: quick-fix {fixed} code quality issues")
        if fixed > 0:
            bumped_version = orc.project_manager.bump_version(RequirementType.PATCH)
            orc.git_ops.tag(f"v{bumped_version}", f"AutoC: v{bumped_version} quick-fix")

    elapsed = time.time() - start_time
    files = list(orc.memory.files.keys())

    remaining_bugs = [
        {"id": b.id, "title": b.title, "severity": b.severity,
         "description": b.description, "status": b.status}
        for b in orc.memory.get_open_bugs()
    ]
    fixed_final = sum(1 for r in bug_results if r["status"] == "fixed")

    result = {
        "success": True,
        "summary": f"快速修复完成: {fixed_final}/{len(target_bugs)} 个问题已修复，耗时 {elapsed:.1f}s",
        "fixed": fixed_final,
        "total": len(target_bugs),
        "files": files,
        "elapsed_seconds": elapsed,
        "verified": verified,
        "total_tokens": orc.total_tokens,
        "tasks_completed": fixed_final,
        "tasks_total": len(target_bugs),
        "tasks_verified": fixed_final,
        "version": orc.project_manager.get_version(),
    }

    orc._emit("quick_fix_done", fixed=fixed_final, total=len(target_bugs),
              files=files, elapsed_seconds=elapsed, verified=verified,
              bug_results=bug_results, remaining_bugs=remaining_bugs)
    orc._emit("summary", **generate_summary(orc, elapsed))

    session_tokens = orc.total_tokens
    session_ts = datetime.now().isoformat()
    bug_titles_str = "、".join(b.title for b in target_bugs[:3])
    if len(target_bugs) > 3:
        bug_titles_str += f" 等{len(target_bugs)}项"
    req_label = f"[quick-fix] {bug_titles_str}"

    orc.project_manager.record_session(
        requirement=req_label,
        success=True,
        tasks_completed=fixed_final,
        tasks_total=len(target_bugs),
        elapsed_seconds=elapsed,
        notes=f"快速修复 {fixed_final}/{len(target_bugs)} 个问题（验证{'通过' if verified else '未通过'}）",
        total_tokens=session_tokens,
        agent_tokens=collect_agent_tokens(orc),
        session_id=orc.session_id,
    )

    try:
        snap_ver = bumped_version or orc.project_manager.get_version()
        orc.project_manager.save_version_snapshot(
            version=snap_ver,
            requirement_type="patch",
            requirement=req_label,
            bugs_fixed=bug_results,
            success=True,
            total_tokens=session_tokens,
            elapsed_seconds=elapsed,
            started_at=start_time,
            ended_at=time.time(),
        )
    except Exception as e:
        logger.warning(f"版本快照保存失败: {e}")

    emit_token_session(
        orc, requirement_label=req_label,
        total_tokens=session_tokens, elapsed_seconds=elapsed,
        success=True, timestamp=session_ts,
    )

    # 设置终态：快修结束后项目不再处于执行中状态
    verified_count = sum(1 for t in orc.memory.tasks.values() if t.passes)
    total_count = len(orc.memory.tasks)
    if verified_count == total_count and total_count > 0:
        orc.project_manager.update_status(ProjectStatus.COMPLETED)
    else:
        orc.project_manager.update_status(ProjectStatus.INCOMPLETE)

    emit_done(orc, result)
    return result


def _quick_verify_for_fix(orc: Orchestrator) -> bool:
    """快速修复后的验证 — 运行测试确认修复有效"""
    try:
        from autoc.stacks._registry import get_test_command
        cmd = get_test_command(orc.workspace_dir)
    except Exception:
        cmd = "python -m pytest tests/ -x --tb=line -q 2>&1"

    try:
        result = orc.shell.execute(cmd, timeout=60)
        result_lower = result.lower()
        # 更精确的匹配：避免 "no errors" / "0 failed" 被误判
        has_pass = bool(
            re.search(r'\b(\d+ passed|\d+ ok|all tests passed|0 failed)\b', result_lower)
        )
        has_fail = bool(
            re.search(r'\b(\d+ failed|\d+ error[s]?|assertion ?error|traceback)\b', result_lower)
        )
        # 回退：无结构化标记时，用 exit code 推断
        if not has_pass and not has_fail:
            has_pass = "passed" in result_lower or result_lower.strip().endswith("ok")
            has_fail = "failed" in result_lower or "error" in result_lower
        return has_pass and not has_fail
    except Exception as e:
        logger.warning(f"快速验证异常: {e}")
        return False


# ==================== 操作：重新定义项目（主需求变更） ====================

def execute_redefine_project(orc: Orchestrator, new_description: str) -> dict:
    """主需求变更 → 归档当前迭代（git tag）→ 清空 → major bump → 全量重来。"""
    from .lifecycle import (
        restore_tasks_from_file, clean_project_files,
    )

    old_task_ids = list(orc.memory.tasks.keys())

    state_mgr = StateManager(orc.workspace_dir)
    if state_mgr.has_prd():
        old_prd = state_mgr.load_prd()
        label = old_prd.project or "redefine"
        archive_path = state_mgr.archive_run(label)
        if archive_path:
            logger.info(f"旧 PRD 已归档: {archive_path}")
            orc._emit("archive_created", path=archive_path)

    old_version = orc.project_manager.get_version()
    if orc.git_ops:
        orc.git_ops.commit("chore: pre-redefine snapshot")
        tag_name = f"v{old_version}"
        tag_result = orc.git_ops.tag(tag_name, f"迭代归档: {old_version}")
        console.print(f"[cyan]🏷️  已归档为 {tag_name}[/cyan]")
        logger.info(f"Git tag 创建: {tag_result}")

    # 安全策略：容器仅随项目删除时一并清理，redefine 只断开引用
    if orc.sandbox:
        try:
            orc.sandbox.detach()
        except Exception as e:
            logger.debug(f"sandbox.detach() 异常（忽略）: {e}")

    cleaned = clean_project_files(orc)
    if cleaned:
        orc._emit("workspace_cleaned", files_removed=cleaned)

    state_mgr.clear_state_files()

    orc.memory.tasks.clear()
    orc.memory.bug_reports.clear()
    orc.memory.test_results.clear()
    orc.memory.plan_md = ""
    orc.memory.plan_history.clear()
    orc.memory.plan_source = ""
    # 删除旧 PLAN.md 及版本化副本
    plan_path = os.path.join(orc.workspace_dir, "PLAN.md")
    if os.path.exists(plan_path):
        try:
            os.remove(plan_path)
        except Exception as e:
            logger.warning(f"删除 PLAN.md 失败: {e}")
    try:
        for f in os.listdir(orc.workspace_dir):
            if f.startswith("PLAN-v") and f.endswith(".md"):
                os.remove(os.path.join(orc.workspace_dir, f))
    except Exception as e:
        logger.debug(f"清理 PLAN 版本文件: {e}")
    if orc.progress_tracker:
        orc.progress_tracker.delete_tasks_by_ids(old_task_ids)

    orc._requirement_type = "primary"
    pending_version = bump_major(old_version)
    orc._pending_version = pending_version
    orc._emit("redefine_start", old_version=old_version, new_version=pending_version)
    console.print(f"[cyan]📝 主需求变更，重新开始...[/cyan]")

    result = orc.run(new_description, incremental=False)

    if result.get("success"):
        orc.project_manager.set_version(pending_version)
        if orc.git_ops:
            orc.git_ops.tag(f"v{pending_version}", f"AutoC: v{pending_version} 主需求完成")
        orc.project_manager.record_requirement(
            req_id=f"req-{pending_version}", title=new_description[:200],
            description=new_description, req_type=RequirementType.PRIMARY,
            version=pending_version,
        )
        logger.info(f"主需求完成: v{old_version} → v{pending_version}")
    orc._pending_version = None
    return result


# ==================== 操作：追加功能（次级需求） ====================

def execute_add_feature(orc: Orchestrator, feature_description: str) -> dict:
    """次级需求 → 保留已有代码和任务 → 增量规划新任务 → append 到 PRD → minor bump。

    与 redefine_project 的关键区别：
    - 不替换主需求（主需求不变，feature_description 仅传给 PM 做增量规划）
    - 不归档 PRD（在现有 PRD 上 append）
    - 不清空工作区
    - minor bump 而非 major bump
    """
    from . import scheduler
    from .lifecycle import restore_tasks_from_file, scan_workspace_files_into_memory

    old_version = orc.project_manager.get_version()
    orc._requirement_type = "secondary"
    pending_version = bump_minor(old_version)
    orc._pending_version = pending_version
    orc._emit("add_feature_start",
               old_version=old_version, new_version=pending_version, feature=feature_description)
    console.print(f"[cyan]📝 追加功能，增量开发...[/cyan]")

    scan_workspace_files_into_memory(orc)

    orc.project_manager.update_status(ProjectStatus.PLANNING)

    # 增量规划：PlanningAgent 生成新的 PLAN.md
    plan_md = scheduler.run_planning_phase(orc, feature_description, incremental=True)
    if plan_md is None:
        orc._pending_version = None
        return {"success": False, "summary": "增量规划失败", "files": []}

    start_time = time.time()
    orc.init_sandbox_after_planning()
    try:
        scheduler.run_dev_and_test(orc, plan_md)
    except SystemExit:
        logger.warning("迭代循环被用户终止")
    except Exception as e:
        logger.exception("迭代循环异常: %s", e)

    elapsed = time.time() - start_time
    try:
        from .lifecycle import finalize
        result = finalize(orc, elapsed, feature_description)
    except Exception as e:
        logger.exception("收尾异常: %s", e)
        orc._pending_version = None
        try:
            orc.project_manager.update_status(ProjectStatus.INCOMPLETE, force=True)
        except Exception:
            pass
        fallback = {"success": False, "summary": f"收尾异常: {e}", "files": [],
                     "elapsed_seconds": elapsed}
        from .lifecycle import emit_done
        emit_done(orc, fallback)
        return fallback

    if result.get("success"):
        orc.project_manager.set_version(pending_version)
        if orc.git_ops:
            orc.git_ops.tag(f"v{pending_version}", f"AutoC: v{pending_version} 追加功能完成")
        orc.project_manager.record_requirement(
            req_id=f"req-{pending_version}", title=feature_description[:200],
            description=feature_description, req_type=RequirementType.SECONDARY,
            version=pending_version, parent_version=old_version,
        )
        try:
            all_tasks = list(orc.memory.tasks.values())
            _meta = orc.project_manager.load()
            orc.project_manager.save_version_snapshot(
                version=pending_version,
                requirement_type="secondary",
                requirement=feature_description,
                tech_stack=_meta.tech_stack if _meta else [],
                tasks=[{"id": t.id, "title": t.title,
                        "status": t.status.value if hasattr(t.status, 'value') else str(t.status),
                        "passes": t.passes} for t in all_tasks],
                success=True,
                total_tokens=orc.total_tokens,
                elapsed_seconds=elapsed,
                started_at=start_time,
                ended_at=time.time(),
            )
        except Exception as e:
            logger.warning(f"版本快照保存失败: {e}")
        logger.info(f"追加功能完成: v{old_version} → v{pending_version}")
    orc._pending_version = None
    return result
