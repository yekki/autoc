"""Parallel Executor — Agent Delegation 并行执行引擎

参考 OpenHands Agent Delegation 设计：
- 基于 DAG 依赖图，自动识别可并行的任务批次
- 使用 ThreadPoolExecutor + CodeActAgent.clone() 并行执行
- 结果聚合 + 错误隔离（单任务失败不影响其他并行任务）
- 与 IterativeLoop 解耦，作为可插拔执行策略

并行执行流程：
1. 从 ready tasks 中选取一批无依赖关系的任务
2. 每个任务创建独立 clone，在线程池中并行执行
3. 等待所有任务完成，聚合结果
4. 更新 PRD 状态，返回批次结果
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from autoc.core.orchestrator.loop_exec import evaluate_task_pass
from autoc.core.project.models import Task
from autoc.exceptions import AgentStuckError

if TYPE_CHECKING:
    from autoc.agents.code_act_agent import CodeActAgent
    from autoc.core.project.state import PRDState

logger = logging.getLogger("autoc.parallel")


@dataclass
class ParallelTaskResult:
    """单个并行任务的执行结果"""
    task_id: str
    task_title: str
    success: bool = False
    stuck: bool = False  # True 表示 AgentStuckError，触发与串行一致的拉满失败计数
    error: str = ""
    report: dict = field(default_factory=dict)
    files_changed: list[str] = field(default_factory=list)
    tokens_used: int = 0
    elapsed_seconds: float = 0.0


@dataclass
class ParallelBatchResult:
    """并行批次的聚合结果"""
    task_results: list[ParallelTaskResult] = field(default_factory=list)
    total_elapsed: float = 0.0

    @property
    def succeeded(self) -> int:
        return sum(1 for r in self.task_results if r.success)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.task_results if not r.success)

    @property
    def all_success(self) -> bool:
        return all(r.success for r in self.task_results)

    @property
    def total_tokens(self) -> int:
        return sum(r.tokens_used for r in self.task_results)


class ParallelExecutor:
    """DAG 感知的并行执行引擎

    用法：
        executor = ParallelExecutor(max_workers=3)
        batch = executor.select_parallel_batch(ready_tasks, completed_ids)
        result = executor.execute_batch(batch, code_act_agent, guardrails, patterns)
    """

    def __init__(self, max_workers: int = 3):
        self._max_workers = max_workers

    def select_parallel_batch(
        self,
        ready_tasks: list[Task],
        max_batch: int | None = None,
    ) -> list[Task]:
        """从 ready tasks 中选取可并行执行的批次

        规则：
        1. 互相之间不存在依赖关系
        2. 不超过 max_workers 个
        3. 优先选择失败重试的任务（priority boost）
        """
        if not ready_tasks:
            return []

        batch_size = min(
            max_batch or self._max_workers,
            self._max_workers,
            len(ready_tasks),
        )
        if batch_size <= 1:
            return ready_tasks[:1]

        # 过滤互相依赖的任务
        batch: list[Task] = []
        batch_ids: set[str] = set()
        for task in ready_tasks:
            if len(batch) >= batch_size:
                break
            task_deps = set(task.dependencies) if task.dependencies else set()
            if not task_deps & batch_ids:
                batch.append(task)
                batch_ids.add(task.id)

        return batch

    def execute_batch(
        self,
        tasks: list[Task],
        main_agent: "CodeActAgent",
        guardrails: str = "",
        patterns: str = "",
    ) -> ParallelBatchResult:
        """并行执行一批任务

        每个任务使用独立的 clone() 实例，在线程池中并行运行。
        """
        if not tasks:
            return ParallelBatchResult()

        if len(tasks) == 1:
            result = self._execute_single(
                tasks[0], main_agent, guardrails, patterns,
            )
            return ParallelBatchResult(
                task_results=[result], total_elapsed=result.elapsed_seconds,
            )

        batch_start = time.time()
        results: list[ParallelTaskResult] = []

        logger.info(
            f"并行执行 {len(tasks)} 个任务: "
            f"{[t.id for t in tasks]} (workers={self._max_workers})"
        )

        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            futures = {}
            for task in tasks:
                future = pool.submit(
                    self._execute_single,
                    task, main_agent, guardrails, patterns,
                )
                futures[future] = task

            for future in as_completed(futures):
                task = futures[future]
                try:
                    result = future.result()
                    results.append(result)
                    status = "✅" if result.success else "❌"
                    logger.info(
                        f"  {status} [{task.id}] {task.title} "
                        f"({result.elapsed_seconds:.1f}s, {result.tokens_used} tokens)"
                    )
                except Exception as e:
                    logger.error(f"  ❌ [{task.id}] 执行异常: {e}")
                    results.append(ParallelTaskResult(
                        task_id=task.id,
                        task_title=task.title,
                        success=False,
                        error=str(e),
                    ))

        batch_elapsed = time.time() - batch_start
        batch_result = ParallelBatchResult(
            task_results=results, total_elapsed=batch_elapsed,
        )
        logger.info(
            f"并行批次完成: {batch_result.succeeded}/{len(tasks)} 成功, "
            f"{batch_elapsed:.1f}s, {batch_result.total_tokens} tokens"
        )
        return batch_result

    def _execute_single(
        self,
        task: Task,
        main_agent: "CodeActAgent",
        guardrails: str,
        patterns: str,
    ) -> ParallelTaskResult:
        """在独立 clone 上执行单个任务

        clone() 为每个 worker 创建独立的 LLMClient 实例（独立 call_log + 计数器），
        token 统计直接读取克隆实例的 total_tokens，无竞态风险。
        """
        start = time.time()
        # clone() 创建独立 LLMClient（base.py _clone_llm），call_log 和计数器均从零开始
        impl = main_agent.clone()

        if guardrails or patterns:
            impl.inject_guardrails(guardrails, patterns)

        try:
            report = impl.implement_and_verify(task)
        except AgentStuckError as stuck_err:
            impl._save_final_snapshot("")
            logger.warning(f"[{task.id}] 并行任务 AgentStuckError: {stuck_err}")
            return ParallelTaskResult(
                task_id=task.id,
                task_title=task.title,
                success=False,
                stuck=True,
                error=f"[STUCK] {stuck_err}",
                elapsed_seconds=time.time() - start,
            )
        except Exception as e:
            logger.error(f"[{task.id}] implement_and_verify 异常: {e}")
            return ParallelTaskResult(
                task_id=task.id,
                task_title=task.title,
                success=False,
                error=str(e),
                elapsed_seconds=time.time() - start,
            )

        # 直接读取独立克隆的 total_tokens（clone() 已确保各 worker 有独立 LLMClient）
        tokens_used = getattr(impl.llm, "total_tokens", 0)

        overall_passed = evaluate_task_pass(report, task.id)

        return ParallelTaskResult(
            task_id=task.id,
            task_title=task.title,
            success=overall_passed,
            error="" if overall_passed else report.get("summary", "未通过"),
            report=report,
            files_changed=list(impl._changed_files),
            tokens_used=tokens_used,
            elapsed_seconds=time.time() - start,
        )
