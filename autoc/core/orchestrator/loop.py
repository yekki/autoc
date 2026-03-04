"""Iterative Loop — 统一迭代循环引擎

核心设计:
  每次迭代 = 全新 Agent 上下文（上下文轮转）。
  状态通过文件 (prd.json / progress.txt / guardrails.md) 持久化，
  每次状态变更同步到 SQLite（供 Web UI 查询）。

融合 Pipeline 高级特性:
  - 失败模式分析 (FailureAnalyzer)
  - 修复策略递进 (fix_attempts → 默认 → 重构 → 重写)
  - 反思机制 (连续 2 轮失败后 LLM 分析根因)
  - Git 检查点 + 回归回滚
  - 并行任务执行 (agent.clone())
  - 修复后快速验证 (pytest -x)
  - 自动 lint-fix (测试通过时修复低优先级问题)
  - 修复轨迹记录 (经验库)
"""

import logging
import time
from typing import TYPE_CHECKING, Optional

from rich.console import Console

from autoc.core.project.state import StateManager, PRDState
from autoc.core.project.models import Task
from autoc.core.analysis.exit_detector import ExitDetector, ExitReason
from autoc.core.infra.circuit_breaker import (
    CircuitBreaker, RateLimiter, IterationRecord, BreakerState,
)
from .loop_models import Phase, IterationResult, LoopResult, TokenTracker
from .loop_exec import _ExecMixin
from .loop_fix import _FixMixin
from .loop_review import _ReviewMixin
from .loop_support import _SupportMixin
from .parallel import ParallelExecutor

if TYPE_CHECKING:
    from .facade import Orchestrator

console = Console()
logger = logging.getLogger("autoc.loop")


class IterativeLoop(_ExecMixin, _FixMixin, _ReviewMixin, _SupportMixin):
    """统一迭代循环引擎

    Coder Agent 完成 实现+验证+修复，可选 Critique Agent 做代码评审。
    Planning 阶段在 Orchestrator 中完成，Loop 只处理任务调度和安全机制。

    Args:
        orchestrator: 父编排器，提供 Agent 实例、工具、配置
        state_manager: 状态文件管理器 (prd.json / progress.txt / guardrails.md)
        config: 循环配置 (max_iterations, circuit_breaker, exit_detection, rate_limit)
    """

    def __init__(
        self,
        orchestrator: "Orchestrator",
        state_manager: StateManager,
        config: dict | None = None,
    ):
        self.orc = orchestrator
        self.state = state_manager

        cfg = config or {}
        exit_cfg = cfg.get("exit_detection", {})
        cb_cfg = cfg.get("circuit_breaker", {})
        rl_cfg = cfg.get("rate_limit", {})

        self.max_fix_rounds = cfg.get("max_rounds", orchestrator.max_rounds)
        self.batch_size = cfg.get("batch_size", 5)

        self.exit_detector = ExitDetector(
            completion_threshold=exit_cfg.get("completion_threshold", 2),
            require_exit_signal=exit_cfg.get("require_exit_signal", True),
            max_consecutive_done=exit_cfg.get("max_consecutive_done", 2),
        )
        self.circuit_breaker = CircuitBreaker(
            no_progress_threshold=cb_cfg.get("no_progress_threshold", 3),
            same_error_threshold=cb_cfg.get("same_error_threshold", 5),
            cooldown_seconds=cb_cfg.get("cooldown_minutes", 5) * 60,
            auto_reset=cb_cfg.get("auto_reset", False),
        )
        self.rate_limiter = RateLimiter(
            max_calls_per_hour=rl_cfg.get("max_calls_per_hour", 100),
        )

        # P-FT-01: 任务级失败保护 / P-FT-02: 熔断器 (见 AGENT_SCHEDULING_PARADIGM.md §6)
        # 预加载已通过任务，避免增量开发时对旧任务重复执行 DEV
        prd = state_manager.load_prd() if state_manager.has_prd() else None
        self._pre_seeded_ids: set[str] = {
            t.id for t in prd.tasks if t.passes
        } if prd else set()
        self._implemented: set[str] = set(self._pre_seeded_ids)
        self._fix_round: int = 0
        self._last_test_report: dict = {}
        self._test_reports: list[dict] = []
        self._fix_history: list[dict] = []
        self._phase_state: Phase = Phase.DEV
        self._phase_transitions: list[tuple[str, str, str]] = []
        self._task_failures: dict[str, int] = {}
        self._max_task_retries: int = cfg.get("max_task_retries", 3)
        self._iteration_changed_files: set[str] = set()
        self._max_test_reports = cfg.get("max_test_reports", 3)
        self.token_tracker = TokenTracker()
        # 评审/修复状态（显式声明，避免类变量污染多实例）
        self._critique_consecutive_failures: int = 0
        self._no_bug_fail_count: int = 0

        # 并行执行引擎
        parallel_cfg = cfg.get("parallel", {})
        self._enable_parallel = getattr(orchestrator, "enable_parallel", False)
        self._parallel_executor = ParallelExecutor(
            max_workers=parallel_cfg.get(
                "max_workers",
                getattr(orchestrator, "max_parallel_tasks", 3),
            ),
        )

    def _emit(self, event_type: str, **data):
        self.orc.on_event({"type": event_type, "agent": "loop", "data": data})

    # ================================================================
    # State Machine — 集中式阶段转换
    # ================================================================

    _VALID_TRANSITIONS: dict[Phase, set[Phase]] = {
        Phase.DEV: {Phase.DEV, Phase.TEST, Phase.CRITIQUE_REVIEW, Phase.PLANNING_REVIEW},
        Phase.TEST: {Phase.DEV, Phase.FIX, Phase.CRITIQUE_REVIEW},
        Phase.FIX: {Phase.TEST, Phase.FIX, Phase.DEV},
        Phase.CRITIQUE_REVIEW: {Phase.DEV, Phase.PLANNING_REVIEW},
        Phase.PLANNING_REVIEW: {Phase.DEV},
    }

    def _transition(self, to: str | Phase, reason: str = ""):
        """统一的阶段转换入口，所有 _phase_state 修改必须经过此方法"""
        target = Phase(to) if isinstance(to, str) else to
        frm = self._phase_state
        valid = self._VALID_TRANSITIONS.get(frm, set())
        if target not in valid and frm != target:
            logger.warning(f"非标准转换 {frm.value} → {target.value} (reason: {reason})，允许但记录")
        self._phase_state = target
        self._phase_transitions.append((frm.value, target.value, reason))
        logger.info(f"阶段转换: {frm.value} → {target.value} ({reason})")

    # ================================================================
    # Main Loop
    # ================================================================

    def run(self, max_iterations: int = 20) -> LoopResult:
        """执行迭代循环: Dev → Test → Fix → (可选 Critique)，每次迭代全新上下文"""
        start_time = time.time()
        result = LoopResult()
        self.exit_detector.reset()
        # 直接赋值而非经 _transition：首次设置无"前一状态"，避免记录冗余转换
        self._phase_state = Phase.DEV
        self._phase_transitions = []

        prd = self.state.load_prd()

        self._emit("loop_start", max_iterations=max_iterations,
                    project=prd.project, stories_total=len(prd.tasks))

        for iteration in range(1, max_iterations + 1):
            if not self.rate_limiter.can_proceed():
                wait = self.rate_limiter.wait_time_seconds()
                console.print(f"[yellow]  ⏳ 速率限制: 等待 {wait:.0f}s[/yellow]")
                time.sleep(min(wait, 60))
                if not self.rate_limiter.can_proceed():
                    result.exit_reason = ExitReason.RATE_LIMITED
                    break

            if self.circuit_breaker.is_open():
                console.print("[bold red]  🔌 熔断器已触发，停止循环[/bold red]")
                result.exit_reason = ExitReason.CIRCUIT_BREAKER
                break

            prd = self.state.load_prd()

            if prd.all_passed():
                actually_devd = self._implemented - self._pre_seeded_ids
                if not actually_devd and iteration == 1:
                    logger.warning(
                        "all_passed=True 但无任务经过 DEV（疑似残留状态），重置"
                    )
                    for t in prd.tasks:
                        t.passes = False
                    prd.plan_complete = False
                    self.state.save_prd(prd)
                elif not prd.plan_complete and getattr(self.orc, "critique", None):
                    self._transition("critique_review", "所有任务通过，Critique 评审")
                    continue
                else:
                    console.print("[bold green]  ✅ 所有 stories 已通过![/bold green]")
                    result.exit_reason = ExitReason.ALL_STORIES_PASSED
                    break

            # 尝试并行执行：多个 DAG-ready 任务同时运行
            parallel_batch = self._get_parallel_batch(prd)
            if len(parallel_batch) > 1 and self._phase_state == Phase.DEV:

                batch_result = self._execute_dev_parallel(
                    iteration, parallel_batch, prd,
                )
                for tr in batch_result.task_results:
                    result.total_tokens += tr.tokens_used
                    self.rate_limiter.record_call()
                    # Fix P1-6: token_tracker 补录
                    try:
                        self.token_tracker.record(
                            role="coder", phase="dev",
                            task_id=tr.task_id,
                            tokens=tr.tokens_used,
                        )
                    except Exception:
                        pass
                prd = self.state.load_prd()

                # Fix P0-4: 全部通过时触发预览
                if prd.all_passed():
                    try:
                        self._start_preview_after_impl()
                    except Exception as e:
                        logger.debug(f"_start_preview_after_impl 失败（忽略）: {e}")

                # 并行路径补全熔断器记录
                any_error = any(not tr.success for tr in batch_result.task_results)
                total_changed = sum(len(tr.files_changed or []) for tr in batch_result.task_results)
                cb_record = IterationRecord(
                    iteration=iteration,
                    files_changed=total_changed,
                    has_error=any_error,
                    phase=Phase.DEV.value,
                    story_passed=not any_error,
                )
                self.circuit_breaker.record(cb_record)

                # 并行路径补全退出检测
                parallel_summary = f"并行执行 {len(parallel_batch)} 个任务"
                exit_analysis = self.exit_detector.analyze(
                    agent_output=parallel_summary,
                    all_stories_passed=prd.all_passed(),
                    has_progress=total_changed > 0,
                    plan_complete=prd.plan_complete,
                    phase=Phase.DEV.value,
                )
                if exit_analysis.should_exit:
                    result.exit_reason = exit_analysis.reason
                    break

                # Fix P0-3: 同步 SQLite（进度持久化）
                try:
                    self._sync_to_sqlite(prd)
                except Exception as e:
                    logger.debug(f"并行路径 _sync_to_sqlite 失败（忽略）: {e}")

                # Fix P0-3: 记录每个任务进度到 progress_tracker
                if self.orc.progress_tracker:
                    for tr in batch_result.task_results:
                        try:
                            self.orc.progress_tracker.write_task_result(
                                task_id=tr.task_id,
                                phase=Phase.DEV.value,
                                success=tr.success,
                                files=list(tr.files_changed or []),
                                summary=tr.report.get("summary", "") if tr.report else "",
                            )
                        except Exception:
                            pass

                # 并行路径发射 iteration_done 事件
                self._emit("iteration_done", iteration=iteration,
                           phase=Phase.DEV.value, success=not any_error)
                continue

            phase, story = self._determine_phase(prd)
            if phase is None:
                if prd.all_passed():
                    result.exit_reason = ExitReason.ALL_STORIES_PASSED
                else:
                    result.exit_reason = ExitReason.MAX_ITERATIONS
                    console.print(
                        "[bold yellow]  ⚠️ 所有任务重试次数已耗尽，"
                        f"仍有 {len([t for t in prd.tasks if not t.passes])} 个未通过[/bold yellow]"
                    )
                break

            self._print_iteration_header(iteration, max_iterations, phase, story, prd)

            self._emit("iteration_start",
                        iteration=iteration, phase=phase.value,
                        story_id=story.id if story else "",
                        story_title=story.title if story else "")

            iter_result = self._execute_iteration(iteration, phase, story, prd)
            result.iterations.append(iter_result)
            result.total_tokens += iter_result.tokens_used
            self.rate_limiter.record_call()

            if phase in (Phase.CRITIQUE_REVIEW, Phase.PLANNING_REVIEW):
                role = "critique"
            else:
                role = "coder"
            self.token_tracker.record(
                role=role, phase=phase.value,
                task_id=story.id if story else "",
                tokens=iter_result.tokens_used,
            )

            # 后处理 + 退出检测，任何步骤失败都不能阻止 iteration_done 发出
            _should_exit = False
            _exit_reason = None
            _exit_msg = ""
            try:
                self._post_iteration(iteration, phase, story, iter_result, prd)

                git_did_commit = False
                if self.orc.git_ops:
                    if phase in (Phase.DEV, Phase.FIX):
                        git_did_commit = bool(iter_result.files_changed)
                    elif phase == Phase.TEST:
                        git_did_commit = True

                cb_record = IterationRecord(
                    iteration=iteration,
                    files_changed=len(iter_result.files_changed),
                    git_committed=git_did_commit,
                    has_error=bool(iter_result.error),
                    error_message=iter_result.error,
                    agent_output_length=len(iter_result.agent_output),
                    story_id=story.id if story else "",
                    story_passed=story.passes if story else False,
                    phase=phase.value,
                    bug_fixed=(phase == Phase.FIX and iter_result.success),
                )
                self.circuit_breaker.record(cb_record)

                prd_after = self.state.load_prd()
                unpassed = [t for t in prd_after.tasks if not t.passes]
                truly_untested = [
                    t for t in unpassed
                    if t.id in self._implemented
                    and self._phase_state in (Phase.DEV, Phase.TEST)
                ]
                has_untested = bool(truly_untested)
                exit_analysis = self.exit_detector.analyze(
                    agent_output=iter_result.agent_output,
                    all_stories_passed=prd_after.all_passed(),
                    iteration=iteration,
                    max_iterations=max_iterations,
                    has_progress=len(iter_result.files_changed) > 0,
                    plan_complete=prd_after.plan_complete,
                    phase=phase.value,
                    has_untested_stories=has_untested,
                )
                _should_exit = exit_analysis.should_exit
                _exit_reason = exit_analysis.reason
                _exit_msg = exit_analysis.message
            except Exception as post_err:
                logger.error(f"迭代 {iteration} 后处理异常（iteration_done 仍会发出）: {post_err}")
                import traceback
                logger.error(traceback.format_exc())
                _should_exit = True
                _exit_reason = ExitReason.MAX_ITERATIONS

            self._emit("iteration_done",
                        iteration=iteration, phase=phase.value,
                        story_id=story.id if story else "",
                        story_title=story.title if story else "",
                        success=iter_result.success,
                        error=iter_result.error or "",
                        files_changed=len(iter_result.files_changed),
                        tokens_used=iter_result.tokens_used,
                        elapsed_seconds=iter_result.elapsed_seconds,
                        should_exit=_should_exit)

            if _should_exit:
                if _exit_msg:
                    console.print(f"[bold green]  🏁 退出: {_exit_msg}[/bold green]")
                result.exit_reason = _exit_reason
                break

            try:
                prd_footer = self.state.load_prd()
                self._print_iteration_footer(iteration, iter_result, prd_footer)
            except Exception:
                pass

        # 确保 exit_reason 不为 None
        if result.exit_reason is None:
            result.exit_reason = ExitReason.MAX_ITERATIONS

        # Summary
        final_prd = self.state.load_prd()
        result.total_iterations = len(result.iterations)
        result.stories_total = len(final_prd.tasks)
        result.stories_passed = sum(1 for t in final_prd.tasks if t.passes)
        result.success = final_prd.all_passed()
        result.elapsed_seconds = time.time() - start_time

        self._emit("loop_done",
                    success=result.success,
                    total_iterations=result.total_iterations,
                    stories_passed=result.stories_passed,
                    stories_total=result.stories_total,
                    exit_reason=result.exit_reason.value if result.exit_reason else None,
                    elapsed_seconds=result.elapsed_seconds,
                    token_breakdown=self.token_tracker.snapshot(),
                    total_tokens=result.total_tokens)

        self._print_final_summary(result)
        return result

    # ================================================================
    # Phase Determination
    # ================================================================

    def _determine_phase(
        self, prd: PRDState
    ) -> tuple[Optional[Phase], Optional[Task]]:
        """确定下一步: DEV 实现 or Critique 评审

        DEV 阶段由 Coder Agent 一次性完成 编码+验证+修复。
        任务级失败保护：单个任务失败超过 max_task_retries 次后跳过。
        """
        pending = [t for t in prd.tasks if not t.passes]

        if self._phase_state in (Phase.CRITIQUE_REVIEW, Phase.PLANNING_REVIEW):
            return self._phase_state, None

        if not pending:
            return None, None

        if self._phase_state == Phase.DEV:
            common_failure = self._detect_common_failure(prd)
            if common_failure:
                logger.warning(f"共性问题: {common_failure}")

            completed_ids = self._implemented | {t.id for t in prd.tasks if t.passes}
            not_impl = [
                t for t in pending
                if t.id not in self._implemented
                and self._task_failures.get(t.id, 0) < self._max_task_retries
            ]
            ready = [t for t in not_impl if self._deps_satisfied(t, completed_ids)]
            blocked = [t for t in not_impl if t not in ready]
            if blocked and not ready:
                logger.warning(
                    f"依赖阻塞: {[t.id for t in blocked]}，"
                    f"已完成: {completed_ids}，强制解锁第一个"
                )
                ready = not_impl[:1]
            if ready:
                ready.sort(key=lambda t: (
                    0 if self._task_failures.get(t.id, 0) > 0 else 1,
                    t.priority,
                ))
                return Phase.DEV, ready[0]

            exceeded = [
                t for t in pending
                if t.id not in self._implemented
                and self._task_failures.get(t.id, 0) >= self._max_task_retries
            ]
            for t in exceeded:
                fail_count = self._task_failures[t.id]
                decision = self._planning_failure_decision(t, fail_count)
                if decision == "retry" or decision == "simplify":
                    self._task_failures[t.id] = 0
                    return Phase.DEV, t
                self._implemented.add(t.id)

            # Implementer 模式: 所有任务已实现+验证，检查是否全部通过
            all_impl_passed = all(t.passes for t in prd.tasks if t.id in self._implemented)
            if all_impl_passed:
                return None, None

            # 有未通过的已实现任务 → 从中选第一个尚未超限的重新实现
            failed_tasks = [t for t in pending if t.id in self._implemented]
            for retry_task in failed_tasks:
                if self._task_failures.get(retry_task.id, 0) < self._max_task_retries:
                    self._implemented.discard(retry_task.id)
                    return Phase.DEV, retry_task

            return None, None

        logger.error(f"_determine_phase: 未处理的阶段状态 {self._phase_state}，返回 None")
        return None, None

    # ================================================================
    # Helpers & Display
    # ================================================================

    def _get_parallel_batch(self, prd: PRDState) -> list[Task]:
        """获取可并行执行的任务批次（多个 DAG-ready 且互无依赖的任务）"""
        if not self._enable_parallel:
            return []

        pending = [t for t in prd.tasks if not t.passes]
        completed_ids = self._implemented | {t.id for t in prd.tasks if t.passes}
        not_impl = [
            t for t in pending
            if t.id not in self._implemented
            and self._task_failures.get(t.id, 0) < self._max_task_retries
        ]
        ready = [t for t in not_impl if self._deps_satisfied(t, completed_ids)]
        if len(ready) <= 1:
            return []

        ready.sort(key=lambda t: (
            0 if self._task_failures.get(t.id, 0) > 0 else 1,
            t.priority,
        ))
        return self._parallel_executor.select_parallel_batch(ready)

    @staticmethod
    def _deps_satisfied(task: Task, completed_ids: set[str]) -> bool:
        """检查任务的所有依赖是否已完成（改进 A: DAG 依赖就绪检查）"""
        if not task.dependencies:
            return True
        return all(d in completed_ids for d in task.dependencies)

    def _print_iteration_header(self, iteration, max_iter, phase, story, prd):
        console.print()
        story_info = f" [{story.id}] {story.title}" if story else ""
        console.rule(
            f"[bold cyan]Iteration {iteration}/{max_iter} "
            f"— {phase.value.upper()}{story_info} "
            f"({prd.progress_summary()})[/bold cyan]"
        )

    def _print_iteration_footer(self, iteration, result, prd):
        status = "[green]✓[/green]" if result.success else "[red]✗[/red]"
        files = f", {len(result.files_changed)} files" if result.files_changed else ""
        console.print(
            f"  {status} 迭代 {iteration} 完成 "
            f"({result.elapsed_seconds:.1f}s{files}) — {prd.progress_summary()}"
        )

    def _print_final_summary(self, result: LoopResult):
        console.print()
        if result.success:
            console.rule("[bold green]🎉 所有 Stories 通过![/bold green]")
        else:
            reason = result.exit_reason.value if result.exit_reason else "unknown"
            console.rule(f"[bold yellow]循环结束 — {reason}[/bold yellow]")
        console.print(
            f"  迭代次数: {result.total_iterations}\n"
            f"  Stories: {result.stories_passed}/{result.stories_total} passed\n"
            f"  Token: {result.total_tokens:,}\n"
            f"  耗时: {result.elapsed_seconds:.1f}s"
        )
        console.print()
