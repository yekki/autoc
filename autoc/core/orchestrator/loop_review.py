"""Critique 评审模块 — 代码级质量评审，替代旧 PM Review

使用 CritiqueAgent 读取实际代码 + 运行测试，
产出 4 维量化评分 (correctness/quality/completeness/best_practices)
和代码级 issues 列表。

保留 PM 失败决策 / 共性问题检测 / 进度审查等非评审功能。
"""

import logging
import os

from rich.console import Console

from autoc.core.project.state import PRDState
from autoc.core.project.models import Task
from autoc.agents.critique import CRITIQUE_DIMENSIONS, PASS_THRESHOLD
from .loop_models import Phase, IterationResult

console = Console()
logger = logging.getLogger("autoc.loop")


MAX_CRITIQUE_FAILURES = 2


class _ReviewMixin:
    """评审逻辑：Critique 评审 / 失败决策 / 共性问题检测 / 进度审查（混入 IterativeLoop）"""

    def _execute_planning_review(
        self, iteration: int, prd: PRDState, ir: IterationResult,
    ) -> IterationResult:
        """Critique Agent 代码级评审（替代旧 PM Review）

        4 维评分 + 代码级 issues，基于实际代码和运行时证据。
        总分 >= 85 为通过；任何维度 < 10 强制不通过。

        降级策略：
        - Critique 基础设施异常（LLM 超时、沙箱错误等）→ 自动通过 + 告警
        - 连续 N 次基础设施失败 → 本次会话禁用 Critique
        """
        critique = getattr(self.orc, "critique", None)
        if critique is None:
            ir.success = True
            self._transition("dev", "无 Critique Agent，跳过评审")
            return ir

        console.print("[bold magenta]  📋 Critique 评审 — 4 维代码级评审[/bold magenta]")
        self._emit("planning_review", status="starting")

        tasks_to_review = self._collect_tasks_for_critique(prd)

        if not tasks_to_review:
            ir.success = True
            ir.agent_output = "无待评审任务"
            self._transition("dev", "无待评审任务")
            return ir

        requirement = prd.requirement or prd.description
        data_models = getattr(prd, "data_models", "") or ""
        api_design = getattr(prd, "api_design", "") or ""

        all_reports = []
        clone_tokens_total = 0
        for task_info in tasks_to_review:
            critique_clone = critique.clone()
            report = critique_clone.review_task(
                task_id=task_info["id"],
                task_title=task_info["title"],
                task_description=task_info.get("description", ""),
                task_files=task_info.get("files", []),
                verification_steps=task_info.get("verification_steps", []),
                acceptance_criteria=task_info.get("acceptance_criteria"),
                requirement=requirement,
                data_models=data_models,
                api_design=api_design,
            )
            all_reports.append(report)
            # clone 拥有独立 LLMClient，从 clone 自身累积 token 消耗
            clone_tokens_total += getattr(critique_clone.llm, "total_tokens", 0)

        ir.tokens_used = clone_tokens_total

        # ── 降级检查：基础设施失败 → 自动通过 ──
        infra_failures = [r for r in all_reports if r.get("infrastructure_failure")]
        if infra_failures:
            self._critique_consecutive_failures += 1
            fail_reasons = "; ".join(r.get("summary", "?")[:80] for r in infra_failures[:3])
            logger.warning(
                f"Critique 基础设施异常 ({self._critique_consecutive_failures}/{MAX_CRITIQUE_FAILURES}): "
                f"{fail_reasons}"
            )
            console.print(
                f"[bold yellow]  ⚠️ Critique 基础设施异常，降级为自动通过 — {fail_reasons}[/bold yellow]"
            )
            self._emit("planning_acceptance", passed=True,
                        answer=f"Critique 基础设施异常，降级自动通过: {fail_reasons}",
                        degraded=True)
            ir.success = True
            ir.agent_output = f"Critique 降级自动通过（基础设施异常: {fail_reasons}）"
            prd.plan_complete = True
            self.state.save_prd(prd)
            self._transition("dev", "Critique 基础设施异常，降级通过")

            if self._critique_consecutive_failures >= MAX_CRITIQUE_FAILURES:
                logger.warning(f"Critique 连续 {MAX_CRITIQUE_FAILURES} 次基础设施失败，本次会话自动禁用")
                console.print(
                    f"[bold red]  🚫 Critique 连续 {MAX_CRITIQUE_FAILURES} 次失败，已自动禁用[/bold red]"
                )
                self.orc.critique = None

            return ir

        self._critique_consecutive_failures = 0

        all_passed = all(r.get("passed", False) for r in all_reports)
        all_issues = []
        for r in all_reports:
            all_issues.extend(r.get("issues", []))

        avg_scores = {}
        for dim in CRITIQUE_DIMENSIONS:
            dim_scores = [r.get("scores", {}).get(dim, 0) for r in all_reports]
            avg_scores[dim] = round(sum(dim_scores) / len(dim_scores)) if dim_scores else 0
        total_score = sum(avg_scores.values())

        scores_display = " / ".join(f"{d}={avg_scores.get(d, 0)}" for d in CRITIQUE_DIMENSIONS)

        if all_passed:
            console.print(
                f"[bold green]  ✅ Critique 评审通过 — "
                f"总分 {total_score}/100 ({scores_display})[/bold green]"
            )
            self._emit("planning_acceptance", passed=True,
                        answer=f"Critique 评审通过: {total_score}/100",
                        rubric_pass=len(all_reports), rubric_total=len(all_reports),
                        critique_scores=avg_scores, critique_total=total_score,
                        critique_issues=len(all_issues))
            ir.success = True
            ir.agent_output = (
                f"Critique 评审通过 ({total_score}/100): {scores_display}"
            )
            prd.plan_complete = True
            self.state.save_prd(prd)
            self._transition("dev", "Critique 评审通过")
        else:
            failed_reports = [r for r in all_reports if not r.get("passed", False)]
            fail_tasks = ", ".join(r.get("task_id", "?") for r in failed_reports[:3])
            critical_issues = [
                i for i in all_issues if i.get("severity") in ("critical", "high")
            ]
            issue_summary = "; ".join(
                f"{i.get('file_path', '?')}: {i.get('description', '')[:60]}"
                for i in critical_issues[:3]
            )

            console.print(
                f"[bold yellow]  ⚠️ Critique 评审未通过 — "
                f"总分 {total_score}/100 ({scores_display}), "
                f"未通过任务: {fail_tasks}[/bold yellow]"
            )
            if critical_issues:
                for issue in critical_issues[:5]:
                    console.print(
                        f"[yellow]    • [{issue.get('severity')}] "
                        f"{issue.get('file_path', '?')}:{issue.get('line_number', '?')} "
                        f"— {issue.get('description', '')[:80]}[/yellow]"
                    )

            self._emit("planning_acceptance", passed=False,
                        answer=f"Critique 评审未通过: {total_score}/100",
                        rubric_pass=len(all_reports) - len(failed_reports),
                        rubric_total=len(all_reports),
                        critique_scores=avg_scores, critique_total=total_score,
                        critique_issues=len(all_issues),
                        failed_items=[{"reason": issue_summary}])
            self._emit("planning_decision", action="fix", reason=issue_summary[:200])

            # 将 issues 注入 Implementer 的修复上下文
            self._inject_critique_issues_for_fix(all_issues)

            # 重置失败任务的 passes 状态，让 _determine_phase 重新选中
            failed_task_ids = {r.get("task_id") for r in failed_reports}
            for t in prd.tasks:
                if t.id in failed_task_ids:
                    t.passes = False
                    self._implemented.discard(t.id)
                    # 递增失败计数，防止 Critique 持续不通过导致无限循环
                    self._task_failures[t.id] = self._task_failures.get(t.id, 0) + 1
                    # 将 Critique issues 摘要写入 failure_trajectory，供 Agent 重做时参考
                    task_report = next(
                        (r for r in failed_reports if r.get("task_id") == t.id), None
                    )
                    if task_report:
                        task_issues = task_report.get("issues", [])
                        issues_summary = "; ".join(
                            i.get("description", "")[:100]
                            for i in task_issues
                            if i.get("severity") in ("critical", "high")
                        )[:500] or task_report.get("summary", "")[:200]
                        if issues_summary:
                            t.failure_trajectory.append({
                                "error": f"[Critique] {issues_summary}",
                                "attempt": self._task_failures.get(t.id, 0),
                            })
            self.state.save_prd(prd)

            ir.success = False
            ir.agent_output = (
                f"Critique 评审未通过 ({total_score}/100): "
                f"{issue_summary[:200]}"
            )
            self._transition("dev", f"Critique 评审未通过，进入修复: {fail_tasks}")

        return ir

    def _collect_tasks_for_critique(self, prd: PRDState) -> list[dict]:
        """收集待评审的任务列表"""
        current_plan_ids = set()
        if self.orc.memory.project_plan:
            current_plan_ids = {t.id for t in self.orc.memory.project_plan.tasks}

        tasks = []
        for t in prd.tasks:
            is_current = t.id in current_plan_ids
            if not is_current and t.passes:
                continue
            tasks.append({
                "id": t.id,
                "title": t.title,
                "description": getattr(t, "description", ""),
                "files": list(t.files) if t.files else [],
                "verification_steps": list(t.verification_steps) if t.verification_steps else [],
                "acceptance_criteria": list(t.acceptance_criteria) if hasattr(t, "acceptance_criteria") and t.acceptance_criteria else None,
            })
        return tasks

    def _inject_critique_issues_for_fix(self, issues: list[dict]):
        """将 Critique issues 注入到 Implementer 可读的上下文中"""
        if not issues:
            return
        critical_issues = [i for i in issues if i.get("severity") in ("critical", "high")]
        if not critical_issues:
            return

        lines = ["## Critique Agent 评审反馈（需修复）"]
        for i, issue in enumerate(critical_issues[:10], 1):
            file_path = issue.get("file_path", "unknown")
            line_num = issue.get("line_number", "")
            desc = issue.get("description", "")
            suggestion = issue.get("suggestion", "")
            loc = f"{file_path}:{line_num}" if line_num else file_path
            lines.append(f"{i}. [{issue.get('severity')}] {loc} — {desc}")
            if suggestion:
                lines.append(f"   建议: {suggestion}")

        feedback = "\n".join(lines)
        if hasattr(self, "state") and self.state:
            try:
                existing = self.state.load_guardrails()
                # 清理上一轮 Critique 反馈（防止无限膨胀）
                CRITIQUE_MARKER_START = "## Critique Agent 评审反馈（需修复）"
                if CRITIQUE_MARKER_START in existing:
                    marker_idx = existing.rfind(CRITIQUE_MARKER_START)
                    existing = existing[:marker_idx].rstrip() + "\n"
                updated = existing + "\n\n" + feedback if existing.strip() else feedback
                self.state.save_guardrails(updated)
            except Exception as e:
                logger.warning(f"注入 Critique 反馈失败: {e}")

    # ================================================================
    # PM 失败决策（保留，不变）
    # ================================================================

    def _planning_failure_decision(self, story: Task, fail_count: int) -> str:
        """任务连续失败后决策下一步动作（使用 Coder AI）。

        返回值:
            "retry"    — 换思路重试
            "simplify" — 简化任务要求后重试
            "skip"     — 跳过该任务
        """
        decision_llm = getattr(self.orc, "llm_coder", None)
        if decision_llm is None:
            return "skip"

        trajectory = story.failure_trajectory[-3:] if story.failure_trajectory else []
        traj_text = "\n".join(
            f"  第{i+1}次: {t.get('error', '未知错误')[:150]}"
            for i, t in enumerate(trajectory)
        ) or "  （无失败记录）"

        prompt = (
            f"你是项目监理。以下任务连续失败 {fail_count} 次，请决定下一步。\n\n"
            f"## 任务\n- [{story.id}] {story.title}\n- {story.description[:200]}\n\n"
            f"## 失败轨迹\n{traj_text}\n\n"
            f"## 可选动作\n"
            f"1. `RETRY` — 失败原因可解决，换思路重试\n"
            f"2. `SIMPLIFY` — 需求太复杂，简化后重试\n"
            f"3. `SKIP` — 非核心功能或当前无法解决，跳过\n\n"
            f"请用一行回答，格式: `动作: 理由`"
        )

        try:
            response = decision_llm.chat(
                messages=[
                    {"role": "system", "content": "你是项目监理，负责对失败任务做决策。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3, max_tokens=200,
            )
            answer = response.get("content", "").strip().upper()
        except Exception as e:
            logger.warning(f"失败决策调用失败: {e}")
            return "skip"

        if answer.startswith("RETRY"):
            reason = answer.split(":", 1)[-1].strip() if ":" in answer else ""
            console.print(f"[cyan]  🔄 决策: 重试 [{story.id}] — {reason[:80]}[/cyan]")
            self._emit("planning_decision", action="retry", task_id=story.id, reason=reason[:200])
            return "retry"
        elif answer.startswith("SIMPLIFY"):
            reason = answer.split(":", 1)[-1].strip() if ":" in answer else ""
            console.print(f"[yellow]  ✂️ 决策: 简化 [{story.id}] — {reason[:80]}[/yellow]")
            self._emit("planning_decision", action="simplify", task_id=story.id, reason=reason[:200])
            if reason:
                story.description = f"[简化] {reason[:300]}\n\n原始: {story.description[:200]}"
                story.failure_trajectory.clear()
            return "simplify"
        else:
            reason = answer.split(":", 1)[-1].strip() if ":" in answer else "决定跳过"
            console.print(f"[dim]  ⏭️ 决策: 跳过 [{story.id}] — {reason[:80]}[/dim]")
            self._emit("planning_decision", action="skip", task_id=story.id, reason=reason[:200])
            return "skip"

    # ================================================================
    # 共性问题检测（保留，不变）
    # ================================================================

    def _detect_common_failure(self, prd: PRDState) -> str | None:
        """扫描多任务失败轨迹，检测共性根因。"""
        failed_stories = [
            t for t in prd.tasks
            if getattr(t, 'failure_trajectory', None) and not t.passes
        ]
        if len(failed_stories) < 2:
            return None

        error_keywords: dict[str, int] = {}
        for s in failed_stories:
            for t in (getattr(s, 'failure_trajectory', None) or [])[-2:]:
                err = t.get("error", "").lower()
                for keyword in _extract_error_keywords(err):
                    error_keywords[keyword] = error_keywords.get(keyword, 0) + 1

        common = [kw for kw, cnt in error_keywords.items() if cnt >= 2]
        if not common:
            return None

        common_desc = ", ".join(common[:5])
        console.print(
            f"[bold red]  ⚠️ 共性问题检测: {len(failed_stories)} 个任务"
            f"有相同失败模式 ({common_desc})[/bold red]"
        )
        self._emit("planning_decision", action="common_failure",
                    affected_tasks=[s.id for s in failed_stories],
                    keywords=common[:5])
        return common_desc

    # ================================================================
    # PM 进度审查（保留，不变）
    # ================================================================

    def _planning_progress_review(self, prd: PRDState) -> str | None:
        """读取 dev/ 工作日志，快速审查产出是否符合规约。"""
        if not getattr(self.orc, "llm_coder", None):
            return None

        ws = getattr(self.orc, "workspace_dir", "")
        dev_dir = os.path.join(ws, ".autoc", "dev")
        if not os.path.isdir(dev_dir):
            return None

        log_summaries = []
        for t in prd.tasks:
            log_path = os.path.join(dev_dir, f"task-{t.id}.log")
            if os.path.isfile(log_path):
                try:
                    with open(log_path, "r", encoding="utf-8") as f:
                        content = f.read(500)
                    passed = "PASS" in content.upper() or "通过" in content
                    status = "✅" if passed else "⚠️"
                    log_summaries.append(f"- [{t.id}] {t.title}: {status} {content[:100]}")
                except Exception:
                    log_summaries.append(f"- [{t.id}] {t.title}: ❓ 日志读取失败")

        if not log_summaries:
            return None

        summary = "\n".join(log_summaries)
        logger.info(f"PM 进度审查:\n{summary}")
        self._emit("planning_review", status="progress_check", summary=summary[:500])
        return summary


def _extract_error_keywords(error_text: str) -> list[str]:
    """从错误文本中提取关键词用于共性检测"""
    keywords = []
    patterns = [
        "modulenotfounderror", "importerror", "no module named",
        "connectionrefused", "connection refused", "econnrefused",
        "permission denied", "filenotfounderror", "no such file",
        "syntaxerror", "indentationerror", "typeerror", "nameerror",
        "timeout", "port already in use", "address already in use",
        "database", "sqlite", "mysql", "postgres",
    ]
    for p in patterns:
        if p in error_text:
            keywords.append(p)
    return keywords
