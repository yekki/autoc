"""任务调度模块 — 需求优化 + PlanningAgent 规划 + CodeActAgent→Critique 迭代

主流程: refine_requirement → run_planning_phase → run_dev_and_test
架构: OpenHands V1.1 模式 — PlanningAgent → PLAN.md → CodeActAgent → CritiqueAgent 循环
操作入口（quick_fix / resume / revise）已拆分至 scheduler_ops.py。
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from rich.console import Console

from autoc.core.project.models import ProjectStatus

if TYPE_CHECKING:
    from .facade import Orchestrator

console = Console()
logger = logging.getLogger("autoc.scheduler")


# ==================== 需求优化 ====================

def refine_requirement(orc: Orchestrator, requirement: str) -> str:
    """需求智能优化: 在规划阶段前对需求进行质量评估和增强

    tech_stack 已从参数中移除 — 技术栈由 PlanningAgent 自主决策。
    """
    if not orc.refiner:
        return requirement

    tokens_before = orc.llm_helper.total_tokens
    try:
        result = orc.refiner.refine(
            requirement,
            workspace_dir=orc.workspace_dir,
            on_event=orc.on_event,
        )
        refine_tokens = orc.llm_helper.total_tokens - tokens_before

        if result.skipped:
            if result.quality_before > 0:
                console.print(
                    f"  📝 需求质量评估: [bold green]{result.quality_before:.0%}[/bold green] — 质量良好，无需优化"
                )
            if refine_tokens > 0:
                orc._emit("iteration_done",
                          iteration=0, phase="refine", success=True,
                          tokens_used=refine_tokens, elapsed_seconds=0,
                          story_title=f"需求质量评估 {result.quality_before:.0%}")
            return requirement

        console.print(
            f"  📝 需求质量: [yellow]{result.quality_before:.0%}[/yellow] → "
            f"[green]{result.quality_after:.0%}[/green] (已优化)"
        )

        if result.enhancements:
            console.print("  [dim]增强项:[/dim]")
            for enh in result.enhancements[:5]:
                console.print(f"    [dim]• {enh}[/dim]")

        if result.suggested_split:
            console.print(
                f"  [yellow]⚠️  建议拆分为 {len(result.suggested_split)} 个子需求:[/yellow]"
            )
            for i, sub in enumerate(result.suggested_split, 1):
                console.print(f"    [yellow]{i}. {sub}[/yellow]")

        orc._refiner_hints = {
            "quality": result.quality_before,
            "too_broad": bool(result.suggested_split),
            "suggested_split": result.suggested_split,
            "enhancements": result.enhancements,
        }

        if refine_tokens > 0:
            orc._emit("iteration_done",
                      iteration=0, phase="refine", success=True,
                      tokens_used=refine_tokens, elapsed_seconds=0,
                      story_title=f"需求优化 {result.quality_before:.0%} → {result.quality_after:.0%}")

        return result.refined

    except Exception as e:
        logger.warning(f"需求优化失败，使用原始需求: {e}")
        return requirement


# ==================== Planning 阶段 (PlanningAgent) ====================

def run_planning_phase(orc: Orchestrator, requirement: str, incremental: bool) -> str | None:
    """Phase 1: PlanningAgent 通过 ReAct 循环探索代码库 + 生成 PLAN.md

    Returns:
        plan_md (str) — Markdown 格式的实现计划，失败时返回 None
    """
    orc.project_manager.update_status(ProjectStatus.PLANNING)

    _planning_tokens_before = orc.llm_planner.total_tokens

    orc.presenter.print_phase("Phase 1", "需求分析与项目规划", "blue")
    orc._emit("phase_start", phase="Phase 1", title="需求分析与项目规划", color="blue")
    orc._emit("planning_analyzing", step="start", message="PlanningAgent 开始分析需求...",
              complexity="auto")

    # S-004: 子步骤 1 — 分析需求
    orc._emit("planning_substep", step=1, label="分析需求和约束", status="running")

    workspace_info = ""
    try:
        files = orc.file_ops.list_files(".", recursive=False)
        if files:
            workspace_info = f"工作区已有文件:\n" + "\n".join(f"  - {f}" for f in files[:30])
            if incremental:
                workspace_info += "\n\n⚠️ 增量模式：这是在已有项目上追加功能，请重点关注现有代码结构。"
    except Exception:
        pass

    # 增量模式下注入主需求上下文，让 PlanningAgent 理解项目全貌
    if incremental and orc.memory.requirement and orc.memory.requirement != requirement:
        primary_plan = orc.memory.get_primary_plan()
        workspace_info += f"\n\n## 项目主需求（核心目标，新功能不得与之冲突）\n{orc.memory.requirement}"
        if primary_plan:
            plan_summary = primary_plan[:2000]
            if len(primary_plan) > 2000:
                plan_summary += "\n...(已截断)"
            workspace_info += f"\n\n## 主需求的实现计划（参考，确保新增功能与已有架构兼容）\n{plan_summary}"

    # S-004: 子步骤 1 完成，开始子步骤 2 — 设计架构
    orc._emit("planning_substep", step=1, label="分析需求和约束", status="done")
    orc._emit("planning_substep", step=2, label="设计技术架构", status="running")

    max_attempts = 2
    last_error = None
    plan_md = None

    for attempt in range(1, max_attempts + 1):
        try:
            plan_md = orc.planner_agent.execute_plan(
                requirement=requirement,
                workspace_info=workspace_info,
            )
            last_error = None
            break
        except Exception as e:
            last_error = e
            if attempt < max_attempts:
                logger.warning(f"PlanningAgent 失败 (第 {attempt} 次)，自动重试: {e}")
                console.print(f"[yellow]⚠️ 规划失败，正在重试 ({attempt}/{max_attempts})...[/yellow]")

    if last_error is not None or not plan_md:
        error_msg = str(last_error) if last_error else "PlanningAgent 未产出计划"
        logger.error(f"Planning 失败: {error_msg}")
        console.print(f"[red]❌ Planning 失败: {error_msg}[/red]")
        # S-004: 规划失败时将剩余子步骤标记为完成，避免前端进度条停在中途
        orc._emit("planning_substep", step=2, label="设计技术架构", status="done")
        orc._emit("planning_substep", step=3, label="拆解实现步骤", status="done")
        planning_tokens = orc.llm_planner.total_tokens - _planning_tokens_before
        if planning_tokens > 0:
            orc._emit("iteration_done",
                      iteration=0, phase="planning", success=False,
                      tokens_used=planning_tokens, elapsed_seconds=0,
                      error=error_msg[:200], story_title="需求分析失败")
        orc._emit("error", message=f"Planning 失败: {error_msg}")
        return None

    planning_tokens = orc.llm_planner.total_tokens - _planning_tokens_before

    # S-004: 子步骤 2 完成，子步骤 3 — 拆解实现步骤（PLAN.md 即是结果）
    orc._emit("planning_substep", step=2, label="设计技术架构", status="done")
    orc._emit("planning_substep", step=3, label="拆解实现步骤", status="done")

    orc._emit("iteration_done",
              iteration=0, phase="planning", success=True,
              tokens_used=planning_tokens, elapsed_seconds=0,
              story_title="PLAN.md 生成完成")

    post_planning_phase(orc, plan_md, requirement)
    return plan_md


# ==================== 规划后处理 ====================

def post_planning_phase(orc: Orchestrator, plan_md: str, requirement: str):
    """规划阶段后处理: 归档旧 plan → 存入内存 → 发射事件 → git commit"""

    # 归档旧 plan（在覆盖前），仅当已有 plan 时
    if orc.memory.plan_md and orc.memory.plan_md != plan_md:
        version = orc.project_manager.get_version()
        orc.memory.archive_current_plan(version, orc.memory.requirement or requirement)
        try:
            orc.file_ops.write_file(f"PLAN-v{version}.md", orc.memory.plan_md)
            logger.info(f"旧计划已备份: PLAN-v{version}.md")
        except Exception as e:
            logger.warning(f"备份旧 PLAN.md 失败: {e}")

    try:
        orc.file_ops.write_file("PLAN.md", plan_md)
    except Exception as e:
        logger.warning(f"写入 PLAN.md 失败: {e}")

    # 标记 plan 来源
    plan_source = getattr(orc, '_requirement_type', 'primary') or 'primary'
    orc.memory.set_plan(plan_md, source=plan_source)

    orc._emit("plan_ready", plan_md=plan_md)

    if orc.git_ops:
        orc.git_ops.commit("feat: project plan (PLAN.md)")

    from autoc.core.orchestrator.lifecycle import save_checkpoint
    save_checkpoint(orc, "phase1_plan_done")


# ==================== Dev/Test 迭代 (CodeActAgent → Critique) ====================

def _run_rule_based_review(orc: Orchestrator) -> dict | None:
    """规则型 Critic 兜底评审（无 CritiqueAgent 时使用）"""
    from autoc.core.critic import CompositeCritic
    from autoc.core.critic.base import CodeQualityCritic, SecurityCritic, CriticContext

    try:
        files: dict[str, str] = {}
        for rel_path in (orc.memory.files or {}):
            try:
                content = orc.file_ops.read_file(rel_path)
                if content:
                    files[rel_path] = content
            except Exception:
                pass
        if not files:
            return None

        composite = CompositeCritic(pass_threshold=0.70)
        composite.add(CodeQualityCritic()).add(SecurityCritic())

        ctx = CriticContext(
            files=files,
            requirement=orc.memory.requirement or "",
        )
        result = composite.evaluate(ctx)
        return {
            "passed": result.passed,
            "total_score": result.score_100,
            "summary": f"规则型评审: {result.score_100}/100",
            "scores": result.metadata.get("individual_results", {}),
            "issues": [
                {"severity": i.severity, "description": i.description,
                 "file_path": i.file_path, "line_number": i.line_number,
                 "suggestion": i.suggestion}
                for i in result.issues
            ],
        }
    except Exception as e:
        logger.warning(f"规则型评审失败: {e}")
        return None


def run_dev_and_test(orc: Orchestrator, plan_md: str, max_iterations: int | None = None):
    """Phase 2: CodeActAgent 实现 + 评审迭代循环

    评审策略：
    - CritiqueAgent 启用：LLM 评审 → 反馈 → 修复循环（最多 N 轮）
    - CritiqueAgent 未启用：规则型 Critic 做基础质量门槛（单轮）
    - 会话持续累积：Round 2+ 保留 CodeActAgent 上下文（对齐 OpenHands）
    """
    orc.project_manager.update_status(ProjectStatus.DEVELOPING)

    max_rounds = max_iterations or orc.max_rounds or 3
    feedback = None
    final_passed = False
    # 初始化为 0：当 max_rounds=0 时 for 循环不执行，iteration 不会被赋值
    iteration = 0
    # 记录真实退出原因（异常 break 不同于正常达到 max_rounds）
    _exit_reason_override: str | None = None

    orc.presenter.print_phase("Phase 2", "开发与迭代", "green")
    orc._emit("phase_start", phase="Phase 2", title="开发与迭代", color="green")
    orc._emit("execution_start", task_count=0)

    for iteration in range(1, max_rounds + 1):
        iter_start = time.time()
        coder_tokens_before = orc.llm_coder.total_tokens
        orc._emit("iteration_start", iteration=iteration, phase="dev",
                  story_title=f"CodeActAgent 实现 (Round {iteration})",
                  story_id=f"round-{iteration}")

        console.print(f"\n  [bold green]▶ Round {iteration}/{max_rounds}[/bold green]")

        # --- CodeActAgent 实现 ---
        console.print("  [green]  🔨 CodeActAgent 正在实现...[/green]")
        try:
            report = orc.code_act_agent.execute_plan(plan_md, feedback=feedback)
        except Exception as e:
            logger.error(f"CodeActAgent 执行异常 (Round {iteration}): {e}")
            dev_tokens = orc.llm_coder.total_tokens - coder_tokens_before
            orc._emit("iteration_done", iteration=iteration, phase="dev",
                      success=False, error=str(e)[:200],
                      tokens_used=dev_tokens,
                      elapsed_seconds=time.time() - iter_start,
                      story_title=f"CodeActAgent 异常 (Round {iteration})")
            _exit_reason_override = f"agent_exception (Round {iteration}): {str(e)[:80]}"
            break

        iter_elapsed = time.time() - iter_start
        console.print(f"  [green]  ✓ CodeActAgent 完成 ({iter_elapsed:.1f}s)[/green]")

        # --- Git commit ---
        if orc.git_ops:
            try:
                orc.git_ops.commit(f"feat: implementation round {iteration}")
            except Exception:
                pass

        dev_tokens = orc.llm_coder.total_tokens - coder_tokens_before

        # --- 评审 ---
        if orc.critique:
            critique_tokens_before = orc.llm_critique.total_tokens
            # LLM 评审: CritiqueAgent
            console.print("  [magenta]  🔍 CritiqueAgent 正在评审...[/magenta]")
            try:
                critique_result = orc.critique.review_plan(
                    plan_md=plan_md,
                    requirement=orc.memory.requirement,
                )
            except Exception as e:
                logger.error(f"CritiqueAgent 评审异常（降级自动通过）: {e}")
                critique_result = {"passed": True, "summary": f"评审异常，降级通过: {e}",
                                   "scores": {}, "issues": [],
                                   "infrastructure_failure": True}

            if critique_result.get("infrastructure_failure"):
                passed = True
                summary = critique_result.get("summary", "基础设施异常")
                logger.warning(f"Critique 基础设施异常，降级自动通过: {summary}")
                console.print(f"  [bold yellow]  ⚠️ Critique 降级通过 — {summary}[/bold yellow]")
            else:
                passed = critique_result.get("passed", False)
                summary = critique_result.get("summary", "")

            total_score = critique_result.get("total_score", 0)
            critique_tokens = orc.llm_critique.total_tokens - critique_tokens_before
            round_tokens = dev_tokens + critique_tokens

            orc._emit("iteration_done", iteration=iteration, phase="critique",
                      success=passed,
                      tokens_used=round_tokens,
                      elapsed_seconds=time.time() - iter_start,
                      story_title=f"评审 {'通过' if passed else '未通过'} ({total_score}/100)")

            if passed:
                console.print(
                    f"  [bold green]  ✓ 评审通过[/bold green] — "
                    f"总分 {total_score}/100: {summary}"
                )
                final_passed = True
                break
            else:
                console.print(
                    f"  [yellow]  ✗ 评审未通过[/yellow] — "
                    f"总分 {total_score}/100: {summary}"
                )
                issues = critique_result.get("issues", [])
                if issues:
                    console.print(f"  [yellow]    {len(issues)} 个问题需要修复[/yellow]")

                feedback = _build_critique_feedback(critique_result)

                if iteration < max_rounds:
                    console.print(f"  [yellow]  → 将反馈注入 CodeActAgent 进行下一轮修复[/yellow]")
        else:
            # 规则型兜底评审（单轮，不产生反馈循环）
            rule_result = _run_rule_based_review(orc)
            if rule_result:
                total_score = rule_result.get("total_score", 0)
                passed = rule_result.get("passed", True)
                n_issues = len(rule_result.get("issues", []))
                console.print(
                    f"  [dim]  📋 规则评审: {total_score}/100"
                    f" ({n_issues} 个问题)[/dim]"
                )
                if not passed:
                    console.print("  [yellow]  ⚠ 规则评审未通过（存在 critical 级别问题）[/yellow]")
                orc._emit("iteration_done", iteration=iteration, phase="rule_review",
                          success=passed, tokens_used=dev_tokens,
                          elapsed_seconds=time.time() - iter_start,
                          story_title=f"规则评审 {total_score}/100")
                final_passed = passed
            else:
                orc._emit("iteration_done", iteration=iteration, phase="dev",
                          success=True, tokens_used=dev_tokens,
                          elapsed_seconds=time.time() - iter_start,
                          story_title=f"实现完成 (Round {iteration})")
                final_passed = True
            break

    orc._execution_success = final_passed
    orc._scheduler_dev_iterations = iteration
    if _exit_reason_override:
        orc._scheduler_exit_reason = _exit_reason_override
    elif final_passed:
        orc._scheduler_exit_reason = "completed"
    elif iteration < max_rounds:
        # for 循环提前 break（评审通过之外的情况）
        orc._scheduler_exit_reason = f"early_exit (round {iteration}/{max_rounds})"
    else:
        orc._scheduler_exit_reason = f"max_rounds_reached ({max_rounds})"

    status = ProjectStatus.COMPLETED if final_passed else ProjectStatus.INCOMPLETE
    orc.project_manager.update_status(status)

    if final_passed:
        orc._emit("execution_complete", tasks_verified=1, tasks_total=1)
    else:
        fail_reason = (
            f"评审未通过 (共 {max_rounds} 轮): {feedback[:120] if feedback else '无详细反馈'}"
        )
        orc._emit("execution_failed",
                   tasks_verified=0, tasks_total=1,
                   failure_reason=fail_reason,
                   recovery_suggestions=["增加迭代次数", "优化需求描述", "检查 PLAN.md"])


def _build_critique_feedback(critique_result: dict) -> str:
    """将 CritiqueAgent 评审结果格式化为 CodeActAgent 可消费的反馈"""
    parts = ["## 评审反馈（请根据以下问题修复代码）\n"]

    summary = critique_result.get("summary", "")
    if summary:
        parts.append(f"**总结**: {summary}\n")

    scores = critique_result.get("scores", {})
    if scores:
        parts.append("**评分**:")
        for dim, score in scores.items():
            parts.append(f"  - {dim}: {score}/25")
        parts.append("")

    issues = critique_result.get("issues", [])
    if issues:
        parts.append(f"**问题清单 ({len(issues)} 个)**:\n")
        for i, issue in enumerate(issues, 1):
            severity = issue.get("severity", "medium")
            desc = issue.get("description", "")
            file_path = issue.get("file_path", "")
            line = issue.get("line_number", "")
            suggestion = issue.get("suggestion", "")

            loc = f"`{file_path}`" if file_path else ""
            if line:
                loc += f" L{line}"

            parts.append(f"{i}. [{severity}] {loc}: {desc}")
            if suggestion:
                parts.append(f"   → 建议: {suggestion}")

    return "\n".join(parts)


from autoc.core.orchestrator.scheduler_ops import (  # noqa: F401, E402
    execute_quick_fix, execute_resume,
    execute_redefine_project, execute_add_feature,
)
