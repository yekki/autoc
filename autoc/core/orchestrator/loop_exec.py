"""循环引擎执行阶段 — Dev / Critique Review

Mixin 模式：方法混入 IterativeLoop 类。
"""

import logging
import os
import time
import traceback
from types import SimpleNamespace
from typing import TYPE_CHECKING, Optional

from rich.console import Console

from autoc.core.project.state import PRDState
from autoc.core.project.models import Task
from autoc.core.project.memory import TaskStatus
from autoc.exceptions import AgentStuckError
from .loop_models import Phase, IterationResult

console = Console()
logger = logging.getLogger("autoc.loop")


def evaluate_task_pass(report: dict, task_id: str) -> bool:
    """判定任务是否通过。

    逻辑：如果 task_verification 中有精确匹配当前 task_id 的条目，优先使用该条目结果；
    否则回退到 report["pass"] 整体标志。
    """
    passed = report.get("pass", False) or report.get("passed", False)
    tv_list = report.get("task_verification", []) or []
    if tv_list:
        task_match = [tv for tv in tv_list if tv.get("task_id") == task_id]
        if task_match:
            # 取最后一个匹配条目（最新结果优先）
            return bool(task_match[-1].get("passes", False))
        reported_ids = [tv.get("task_id") for tv in tv_list]
        logger.warning(
            f"[{task_id}] task_verification 存在但无匹配条目 "
            f"(reported: {reported_ids})，回退到 pass flag"
        )
    elif passed:
        logger.info(f"[{task_id}] task_verification 为空，仅依赖 pass flag 判定通过")
    return passed


class _ExecMixin:
    """Dev / Critique Review 阶段执行逻辑（混入 IterativeLoop）"""

    _PHASE_META = {
        Phase.DEV:  ("Phase 2", "实现与验证", "green"),
        Phase.TEST: ("Phase 3", "测试与质量验证", "yellow"),
        Phase.FIX:  ("Phase 4", "Bug 修复", "red"),
    }

    def _emit_phase_if_changed(self, phase: Phase):
        """阶段变更时发送 phase_start 事件，连续同阶段不重复发送"""
        if phase == getattr(self, "_last_emitted_phase", None):
            return
        meta = self._PHASE_META.get(phase)
        if meta:
            self._emit("phase_start", phase=meta[0], title=meta[1], color=meta[2])
            self._last_emitted_phase = phase

    def _execute_iteration(
        self, iteration: int, phase: Phase,
        story: Optional[Task], prd: PRDState,
    ) -> IterationResult:
        start = time.time()
        iter_result = IterationResult(
            iteration=iteration, phase=phase,
            story_id=story.id if story else "",
            story_title=story.title if story else "",
        )

        _llm_snapshots = {
            "coder": self.orc.llm_coder.total_tokens,
            "critique": self.orc.llm_critique.total_tokens if self.orc.critique else 0,
        }

        try:
            if phase in (Phase.CRITIQUE_REVIEW, Phase.PLANNING_REVIEW):
                self._emit_phase_if_changed(phase)
                iter_result = self._execute_planning_review(iteration, prd, iter_result)
            elif phase == Phase.DEV:
                self._emit_phase_if_changed(phase)
                context = self._build_context(phase, story, prd,
                                              self.state.load_guardrails(),
                                              self.state.load_codebase_patterns())
                iter_result = self._execute_dev(iteration, story, prd, context, iter_result)
            elif phase in (Phase.TEST, Phase.FIX):
                # Implementer 模式下不应到达 TEST/FIX，兜底处理
                logger.warning(f"Implementer 模式下收到 {phase.value} 阶段，跳过")
                iter_result.success = True

        except Exception as e:
            logger.error(f"迭代 {iteration} 执行失败: {e}\n{traceback.format_exc()}")
            iter_result.error = str(e)
            iter_result.success = False
            if iter_result.tokens_used == 0:
                delta = self.orc.llm_coder.total_tokens - _llm_snapshots["coder"]
                if delta > 0:
                    iter_result.tokens_used = delta
                    logger.info(f"迭代 {iteration} 异常但消耗 {delta} token（已补录）")

        iter_result.elapsed_seconds = round(time.time() - start, 2)
        if iter_result.tokens_used > 0 and iter_result.elapsed_seconds < 0.1:
            logger.warning(
                f"迭代 {iteration} 计时异常: {iter_result.elapsed_seconds}s "
                f"但消耗 {iter_result.tokens_used} token — 使用估算值"
            )
            iter_result.elapsed_seconds = max(iter_result.elapsed_seconds, 1.0)
        return iter_result

    def _execute_dev(
        self, iteration: int, story: Optional[Task],
        prd: PRDState, context: str, ir: IterationResult,
    ) -> IterationResult:
        """Implementer 模式: 实现 + 验证 + 修复，一个连续会话完成"""
        if not story:
            ir.error = "No task to implement"
            return ir

        # 新任务开始时重置 fix 轮次，防止前一任务的轮次跨任务累积
        self._fix_round = 0

        impl = self.orc.code_act_agent.clone()
        # 对话历史持续累积，由 Condenser 自动管理长度（不再清空）

        # 注入 guardrails 上下文
        guardrails = self.state.load_guardrails()
        patterns = self.state.load_codebase_patterns()
        if guardrails or patterns:
            impl.inject_guardrails(guardrails, patterns)

        declared_files = len(story.files) if story.files else 0
        _tokens_before = impl.llm.total_tokens
        _task_start_time = time.time()

        console.print(
            f"  🔨 IMPL [{story.id}] {story.title} "
            f"(budget: {impl.max_iterations} iters, {declared_files} files)"
        )
        self._emit("task_start", task_id=story.id, task_title=story.title,
                    description=story.description, files=story.files,
                    max_iterations=impl.max_iterations)

        try:
            report = impl.implement_and_verify(story)
        except AgentStuckError as stuck_err:
            # Agent 持续停滞（severity >= 3），直接将失败次数拉满触发失败决策
            impl._save_final_snapshot("")  # 确保停滞时对话快照不丢失
            ir.agent_output = str(stuck_err)
            ir.files_changed = list(impl._changed_files)
            ir.tokens_used = impl.llm.total_tokens - _tokens_before
            ir.success = False
            ir.error = f"[STUCK] {stuck_err}"
            # 将失败次数设为上限，下一轮 _determine_phase 会调用 _planning_failure_decision
            self._task_failures[story.id] = self._max_task_retries
            # stuck 任务的报告标记为失败，供 FIX 阶段参考
            stuck_report = {"pass": False, "summary": str(stuck_err), "stuck": True}
            self._last_test_report = stuck_report
            self._test_reports.append(stuck_report)
            if len(self._test_reports) > self._max_test_reports:
                self._test_reports = self._test_reports[-self._max_test_reports:]
            self.orc.memory.update_task(story.id, status=TaskStatus.FAILED, error=ir.error)
            self._emit("task_complete", task_id=story.id, task_title=story.title,
                        success=False, error=ir.error,
                        files_changed=ir.files_changed,
                        tokens_used=ir.tokens_used,
                        elapsed_seconds=round(time.time() - _task_start_time, 2))
            logger.warning(
                f"[{story.id}] AgentStuckError 上报：{stuck_err}，"
                f"失败次数设为 {self._max_task_retries}，触发任务级决策"
            )
            return ir

        ir.agent_output = report.get("summary", "")
        ir.files_changed = list(impl._changed_files)
        ir.tokens_used = impl.llm.total_tokens - _tokens_before

        # 更新测试报告缓存，供 FIX 阶段的 failure_analyzer 使用
        self._last_test_report = report
        self._test_reports.append(report)
        if len(self._test_reports) > self._max_test_reports:
            self._test_reports = self._test_reports[-self._max_test_reports:]

        overall_passed = evaluate_task_pass(report, story.id)

        # P0: LLM-as-Judge 守门员 — 独立评判，防止"自报告通过但功能不工作"
        judge_evidence: dict | None = None
        if overall_passed:
            overall_passed, judge_evidence = self._llm_judge_gate(story, impl, report)

        if overall_passed:
            ir.success = True
            self._implemented.add(story.id)
            prd.mark_task_passed(story.id, True, report.get("summary", ""))
            self.state.save_prd(prd)
            self.orc.memory.update_task(story.id, status=TaskStatus.COMPLETED, passes=True)

            self._emit("task_verified", task_id=story.id, passes=True,
                        details=report.get("summary", ""))
            self._emit("test_result", passed=True, round=1, max_rounds=1,
                        quality_score=report.get("quality_score", 8),
                        bug_count=len(report.get("bugs", [])),
                        bugs=report.get("bugs", []),
                        verified_tasks=1, total_tasks=len(prd.tasks),
                        summary=report.get("summary", ""))
            # Git commit 由 _post_iteration 统一处理，避免双重提交
        else:
            ir.success = False
            ir.error = report.get("summary", "验证未通过")
            self._implemented.add(story.id)
            self._task_failures[story.id] = self._task_failures.get(story.id, 0) + 1
            self.orc.memory.update_task(story.id, status=TaskStatus.FAILED,
                                         error=ir.error)
            self._record_task_failure(
                story, ir, output=ir.agent_output, dev=impl,
                judge_evidence=judge_evidence,
            )
            logger.warning(
                f"IMPL [{story.id}] 验证未通过 (第 {self._task_failures[story.id]} 次): "
                f"{ir.error[:200]}"
            )

        _task_elapsed = round(time.time() - _task_start_time, 2)
        self._emit("task_complete", task_id=story.id, task_title=story.title,
                    success=ir.success, error=ir.error,
                    files_changed=ir.files_changed,
                    tokens_used=ir.tokens_used,
                    elapsed_seconds=_task_elapsed)

        if self.orc.sandbox:
            self.orc.sandbox.kill_user_processes()

        remaining = [t for t in prd.tasks if not t.passes]
        if not remaining and ir.success:
            self._start_preview_after_impl()

        self._iteration_changed_files = set(impl._changed_files)
        self.orc.code_act_agent._changed_files.update(impl._changed_files)

        if impl._changed_files and ir.success:
            actual = set(impl._changed_files)
            planned = set(story.files) if story.files else set()
            if actual - planned:
                story.files = sorted(planned | actual)
                self.state.save_prd(prd)
        return ir

    def _execute_dev_parallel(
        self, iteration: int, tasks: list[Task], prd: PRDState,
    ):
        """并行执行多个 DAG-ready 任务"""
        from .parallel import ParallelBatchResult

        self._fix_round = 0

        guardrails = self.state.load_guardrails()
        patterns = self.state.load_codebase_patterns()

        task_ids = [t.id for t in tasks]
        console.print(
            f"  🚀 并行执行 {len(tasks)} 个任务: {task_ids}"
        )
        self._emit("parallel_start", task_ids=task_ids, worker_count=len(tasks))

        batch_result = self._parallel_executor.execute_batch(
            tasks, self.orc.code_act_agent, guardrails, patterns,
        )

        for tr in batch_result.task_results:
            task = next((t for t in tasks if t.id == tr.task_id), None)
            if not task:
                continue

            # P0-3: 并行路径同样要经过 LLM-as-Judge 守门员
            if tr.success:
                impl_proxy = SimpleNamespace(_changed_files=set(tr.files_changed or []))
                judge_passed, judge_evidence = self._llm_judge_gate(
                    task, impl_proxy, tr.report or {},
                )
                if not judge_passed:
                    tr.success = False
                    tr.error = "LLM Judge 未通过（独立评审）"
                    _ir_proxy = SimpleNamespace(error=tr.error)
                    _dev_proxy2 = SimpleNamespace(_changed_files=set(tr.files_changed or []))
                    self._record_task_failure(
                        task, _ir_proxy, output=tr.error or "", dev=_dev_proxy2,
                        judge_evidence=judge_evidence,
                    )
                    self._task_failures[tr.task_id] = (
                        self._task_failures.get(tr.task_id, 0) + 1
                    )

            if tr.success:
                self._implemented.add(tr.task_id)
                prd.mark_task_passed(tr.task_id, True, tr.report.get("summary", ""))
                self.orc.memory.update_task(
                    tr.task_id, status=TaskStatus.COMPLETED, passes=True,
                )
                if hasattr(tr, 'report') and tr.report:
                    self._test_reports.append(tr.report)
                    if len(self._test_reports) > self._max_test_reports:
                        self._test_reports = self._test_reports[-self._max_test_reports:]
                self._emit("task_complete", task_id=tr.task_id,
                            task_title=tr.task_title, success=True,
                            files_changed=tr.files_changed,
                            tokens_used=tr.tokens_used,
                            elapsed_seconds=tr.elapsed_seconds)
                if self.orc.git_ops:
                    self.orc.git_ops.commit(
                        f"impl: [{tr.task_id}] {tr.task_title} — verified (parallel)"
                    )
            else:
                if tr.stuck:
                    # AgentStuckError：拉满失败计数触发任务级决策（与串行路径一致，不加入 _implemented）
                    self._task_failures[tr.task_id] = self._max_task_retries
                else:
                    self._implemented.add(tr.task_id)
                    self._task_failures[tr.task_id] = (
                        self._task_failures.get(tr.task_id, 0) + 1
                    )
                # 失败任务的报告同样缓存，供失败模式分析使用
                if hasattr(tr, 'report') and tr.report:
                    self._test_reports.append(tr.report)
                    if len(self._test_reports) > self._max_test_reports:
                        self._test_reports = self._test_reports[-self._max_test_reports:]
                self.orc.memory.update_task(
                    tr.task_id, status=TaskStatus.FAILED, error=tr.error,
                )
                _ir_proxy = SimpleNamespace(error=tr.error or "")
                _dev_proxy = SimpleNamespace(_changed_files=tr.files_changed or [])
                self._record_task_failure(task, _ir_proxy, output=tr.error or "", dev=_dev_proxy)
                self._emit("task_complete", task_id=tr.task_id,
                            task_title=tr.task_title, success=False,
                            error=tr.error,
                            tokens_used=tr.tokens_used,
                            elapsed_seconds=tr.elapsed_seconds)

            self.orc.code_act_agent._changed_files.update(tr.files_changed)

        self.state.save_prd(prd)

        # 聚合所有任务的变更文件
        all_changed = set()
        for tr in batch_result.task_results:
            all_changed.update(tr.files_changed or [])
        self._iteration_changed_files = all_changed

        # Fix P1-9: _last_test_report 取最后一个失败任务的报告（更有参考价值）
        failed_reports = [
            tr.report for tr in batch_result.task_results
            if not tr.success and hasattr(tr, 'report') and tr.report
        ]
        success_reports = [
            tr.report for tr in batch_result.task_results
            if tr.success and hasattr(tr, 'report') and tr.report
        ]
        if failed_reports:
            self._last_test_report = failed_reports[-1]
        elif success_reports:
            self._last_test_report = success_reports[-1]

        # Fix P0-3: 清理沙箱用户进程（对齐串行路径）
        if self.orc.sandbox:
            try:
                self.orc.sandbox.kill_user_processes()
            except Exception as e:
                logger.debug(f"kill_user_processes 失败（忽略）: {e}")

        self._emit(
            "parallel_done",
            succeeded=batch_result.succeeded,
            failed=batch_result.failed,
            elapsed=batch_result.total_elapsed,
            tokens=batch_result.total_tokens,
        )

        return batch_result

    def _start_preview_after_impl(self):
        """所有任务完成后启动预览，缓存到 orc._preview_info 供 finish_run 复用"""
        try:
            from autoc.core.orchestrator.lifecycle import try_start_preview
            preview_info = try_start_preview(self.orc)
            if preview_info and preview_info.get("available"):
                self.orc._preview_info = preview_info
                logger.info(f"Implementer 完成后预览已就绪: {preview_info.get('url')}")
            else:
                logger.info("Implementer 完成后预览启动未成功（非 Web 项目或启动超时）")
        except Exception as e:
            logger.warning(f"Implementer 完成后预览启动异常: {e}")

    def _llm_judge_gate(
        self, story: Task, impl, report: dict,
    ) -> tuple[bool, dict | None]:
        """P0: LLM-as-Judge 守门员 — 在 implement_and_verify 自报告通过后二次验证

        1. 先运行 acceptance_tests（如果有），使用 VerificationRunner
        2. 再运行 LLM-as-Judge 任务级评判（锚定原始需求）

        返回 (passed: bool, evidence: dict | None)
        - evidence 不为 None 时，由调用方通过 _record_task_failure 持久化，
          确保写入唯一的 prd.json 副本，避免内存对象分叉问题。
        """
        # --- Step 1: 运行 acceptance_tests ---
        acceptance_tests = getattr(story, "acceptance_tests", []) or []
        at_evidence: list[dict] = []
        at_failed = False

        if acceptance_tests:
            try:
                from autoc.core.verification import VerificationRunner
                preview_url = ""
                if self.orc._preview_info:
                    preview_url = self.orc._preview_info.get("url", "")
                runner = VerificationRunner(
                    llm=getattr(self.orc, "llm_critique", None),
                    shell=getattr(self.orc, "shell", None),
                )
                at_results = runner.run_task_tests(
                    story, self.orc.workspace_dir, preview_url=preview_url,
                )
                summary = runner.summarize_results(at_results)
                at_failed = not summary["all_passed"]
                if at_failed:
                    at_evidence = summary["evidence_list"]
                    logger.warning(
                        f"[{story.id}] 验收测试未通过: "
                        f"{summary['passed']}/{summary['total']} — "
                        f"{[e.get('test', '')[:40] for e in at_evidence[:2]]}"
                    )
                    first_ev = at_evidence[0] if at_evidence else {}
                    console.print(
                        f"  ⚠️  验收测试未通过 ({summary['passed']}/{summary['total']}): "
                        f"{first_ev.get('diagnosis', '') or first_ev.get('test', '')[:60]}"
                    )
                # R-016: 收集所有验收测试的 console_errors（包括通过的任务）
                # 聚合到 orc._preview_console_errors，done 事件使用
                for r in at_results:
                    errs = getattr(r.evidence, "console_errors", []) if r.evidence else []
                    if errs:
                        if not hasattr(self.orc, '_preview_console_errors'):
                            self.orc._preview_console_errors = []
                        # 去重：按 (type, message 前 80 字符) 判断
                        existing_keys = {(e.get("type"), e.get("message", "")[:80])
                                         for e in self.orc._preview_console_errors}
                        for msg in errs:
                            entry = {"type": "console.error", "message": str(msg)[:200]}
                            key = (entry["type"], entry["message"][:80])
                            if key not in existing_keys:
                                self.orc._preview_console_errors.append(entry)
                                existing_keys.add(key)
            except Exception as e:
                logger.warning(f"[{story.id}] acceptance_tests 执行异常（忽略）: {e}")

        # --- Step 2: LLM-as-Judge 任务级评判 ---
        # P0-2 修复：不再以 acceptance_criteria 非空为前提条件。
        # acceptance_criteria 为空时 fallback 到 description / title，
        # 确保守门员在任何情况下都会执行。
        judge_result = None
        llm_judge_failed = False
        try:
            from autoc.core.verification import judge_task_completion
            llm_judge = getattr(self.orc, "llm_critique", None)
            if llm_judge:
                # 优先用 acceptance_criteria；为空时 fallback 到 description，再 fallback 到 title
                criteria = story.acceptance_criteria or []
                if not criteria:
                    fallback = (story.description or "").strip()
                    criteria = [fallback[:400]] if fallback else [story.title]
                    logger.debug(
                        f"[{story.id}] acceptance_criteria 为空，Judge 以 description 作为判断基准"
                    )
                judge_result = judge_task_completion(
                    llm=llm_judge,
                    task_title=story.title,
                    task_description=story.description,
                    acceptance_criteria=criteria,
                    changed_files=list(impl._changed_files),
                    workspace_dir=self.orc.workspace_dir,
                    dev_report_summary=report.get("summary", ""),
                    shell=getattr(self.orc, "shell", None),
                    git_ops=getattr(self.orc, "git_ops", None),
                )
                if not judge_result.skipped and not judge_result.passed:
                    llm_judge_failed = True
                    console.print(
                        f"  🔍 LLM Judge 未通过: {judge_result.reasoning[:120]}"
                    )
                    if judge_result.risk_points:
                        console.print(f"  ⚠️  风险点: {judge_result.risk_points[:80]}")
                    logger.warning(
                        f"[{story.id}] LLM Judge 未通过: {judge_result.reasoning}"
                    )
                else:
                    logger.debug(
                        f"[{story.id}] LLM Judge 通过"
                        + (f" (skipped: {judge_result.skip_reason})" if judge_result.skipped else "")
                    )
        except Exception as e:
            logger.warning(f"[{story.id}] LLM Judge 执行异常（忽略）: {e}")

        overall_failed = at_failed or llm_judge_failed

        # P2-10 修复：不再 append 到 story.failure_trajectory（内存对象会分叉丢失）
        # 改为返回 evidence_entry，由调用方通过 _record_task_failure 统一写盘
        evidence_entry: dict | None = None
        if overall_failed:
            evidence_entry = {
                "source": "llm_judge_gate",
                "acceptance_tests_failed": at_failed,
                "llm_judge_failed": llm_judge_failed,
            }
            if at_evidence:
                evidence_entry["at_evidence"] = at_evidence[:3]
            if judge_result and not judge_result.skipped:
                evidence_entry["judge_reasoning"] = judge_result.reasoning
                evidence_entry["judge_risk_points"] = judge_result.risk_points
            self._emit(
                "judge_gate_failed",
                task_id=story.id,
                at_failed=at_failed,
                llm_judge_failed=llm_judge_failed,
                evidence=evidence_entry,
            )

        return not overall_failed, evidence_entry

    def _record_task_failure(
        self, story: Task, ir: "IterationResult",
        output: str, dev, missing_files: list[str] | None = None,
        judge_evidence: dict | None = None,
    ):
        """记录任务失败轨迹到 prd.json，供下次迭代参考

        judge_evidence 由 _llm_judge_gate 返回，在此处统一写盘，
        避免在内存对象上 append 后因 load_prd() 加载新副本而丢失。
        """
        prd = self.state.load_prd()
        for s in prd.tasks:
            if s.id == story.id:
                entry: dict = {
                    "error": ir.error,
                    "agent_output_tail": (output or "")[-300:],
                    "files_attempted": list(dev._changed_files),
                    "attempt": self._task_failures.get(story.id, 0),
                }
                if missing_files:
                    entry["missing_files"] = missing_files
                # P2-10: 合并 Judge 证据，统一持久化
                if judge_evidence:
                    entry.update(judge_evidence)
                s.failure_trajectory.append(entry)
                break
        self.state.save_prd(prd)

    def _check_story_files_exist(self, story: Task) -> list[str]:
        """检查任务声明的文件是否已在 workspace 中存在"""
        ws = self.orc.file_ops.workspace_dir if self.orc.file_ops else ""
        if not ws or not story.files:
            return []
        existing = []
        for f in story.files:
            fp = os.path.join(ws, f) if not os.path.isabs(f) else f
            if os.path.exists(fp):
                existing.append(f)
        return existing

    def _smoke_check(self, prd: PRDState) -> list[str]:
        """零成本冒烟检查（不消耗 LLM Token）

        检查项：story 声明文件存在性、Python 入口可 import、语法检查。
        """
        issues: list[str] = []
        ws = self.orc.file_ops.workspace_dir if self.orc.file_ops else ""
        if not ws:
            return issues

        for story in prd.tasks:
            if story.id not in self._implemented:
                continue
            for f in (story.files or []):
                fp = os.path.join(ws, f) if not os.path.isabs(f) else f
                if not os.path.exists(fp):
                    issues.append(f"[{story.id}] 声明文件缺失: {f}")

        app_py = os.path.join(ws, "app.py")
        main_py = os.path.join(ws, "main.py")
        entry = "app" if os.path.isfile(app_py) else ("main" if os.path.isfile(main_py) else None)

        if entry and self.orc.shell:
            try:
                result = self.orc.shell.execute(f"python -c 'import {entry}' 2>&1", timeout=15)
                result_str = result if isinstance(result, str) else str(result)
                if "Error" in result_str or "Traceback" in result_str:
                    err_lines = [l for l in result_str.strip().split("\n") if "Error" in l or "No module" in l]
                    short_err = err_lines[-1][:150] if err_lines else result_str.strip()[-150:]
                    issues.append(f"入口模块 import 失败: {short_err}")
            except Exception as e:
                logger.debug(f"冒烟检查 import 异常（非阻塞）: {e}")

        py_files = []
        for story in prd.tasks:
            if story.id not in self._implemented:
                continue
            for f in (story.files or []):
                if f.endswith(".py"):
                    fp = os.path.join(ws, f) if not os.path.isabs(f) else f
                    if os.path.isfile(fp):
                        py_files.append((story.id, f, fp))
        for story_id, rel, fp in py_files[:10]:
            try:
                with open(fp, "r", encoding="utf-8", errors="replace") as fh:
                    source = fh.read()
                compile(source, rel, "exec")
            except SyntaxError as se:
                issues.append(f"[{story_id}] {rel} 语法错误 L{se.lineno}: {se.msg}")
            except Exception:
                pass

        return issues
