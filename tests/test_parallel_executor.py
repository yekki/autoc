"""Parallel Executor 单元测试"""
import pytest
from unittest.mock import MagicMock, patch
from autoc.core.orchestrator.parallel import (
    ParallelExecutor, ParallelTaskResult, ParallelBatchResult,
)
from autoc.core.project.models import Task


def _make_task(task_id: str, deps: list[str] | None = None, priority: int = 0) -> Task:
    """创建测试用 Task"""
    t = Task(id=task_id, title=f"Task {task_id}", description=f"Desc {task_id}")
    t.dependencies = deps or []
    t.priority = priority
    return t


class TestParallelBatchSelection:
    """并行批次选取逻辑"""

    def test_empty_tasks(self):
        executor = ParallelExecutor(max_workers=3)
        batch = executor.select_parallel_batch([])
        assert batch == []

    def test_single_task(self):
        executor = ParallelExecutor(max_workers=3)
        tasks = [_make_task("t1")]
        batch = executor.select_parallel_batch(tasks)
        assert len(batch) == 1
        assert batch[0].id == "t1"

    def test_independent_tasks(self):
        executor = ParallelExecutor(max_workers=3)
        tasks = [_make_task("t1"), _make_task("t2"), _make_task("t3")]
        batch = executor.select_parallel_batch(tasks)
        assert len(batch) == 3

    def test_respects_max_workers(self):
        executor = ParallelExecutor(max_workers=2)
        tasks = [_make_task(f"t{i}") for i in range(5)]
        batch = executor.select_parallel_batch(tasks)
        assert len(batch) == 2

    def test_respects_max_batch(self):
        executor = ParallelExecutor(max_workers=5)
        tasks = [_make_task(f"t{i}") for i in range(5)]
        batch = executor.select_parallel_batch(tasks, max_batch=2)
        assert len(batch) == 2

    def test_filters_mutual_dependencies(self):
        executor = ParallelExecutor(max_workers=3)
        tasks = [
            _make_task("t1"),
            _make_task("t2", deps=["t1"]),
            _make_task("t3"),
        ]
        batch = executor.select_parallel_batch(tasks)
        ids = {t.id for t in batch}
        assert "t1" in ids
        assert "t3" in ids
        assert "t2" not in ids


class TestParallelTaskResult:
    """ParallelTaskResult 数据结构"""

    def test_default_values(self):
        r = ParallelTaskResult(task_id="t1", task_title="Test")
        assert r.success is False
        assert r.error == ""
        assert r.tokens_used == 0


class TestParallelBatchResult:
    """ParallelBatchResult 聚合"""

    def test_empty_batch(self):
        r = ParallelBatchResult()
        assert r.succeeded == 0
        assert r.failed == 0
        assert r.all_success is True
        assert r.total_tokens == 0

    def test_mixed_results(self):
        r = ParallelBatchResult(task_results=[
            ParallelTaskResult(task_id="t1", task_title="A", success=True, tokens_used=100),
            ParallelTaskResult(task_id="t2", task_title="B", success=False, tokens_used=50),
            ParallelTaskResult(task_id="t3", task_title="C", success=True, tokens_used=200),
        ])
        assert r.succeeded == 2
        assert r.failed == 1
        assert r.all_success is False
        assert r.total_tokens == 350

    def test_all_success(self):
        r = ParallelBatchResult(task_results=[
            ParallelTaskResult(task_id="t1", task_title="A", success=True),
            ParallelTaskResult(task_id="t2", task_title="B", success=True),
        ])
        assert r.all_success is True


class TestExecuteSingle:
    """_execute_single 单任务执行"""

    def test_successful_execution(self):
        executor = ParallelExecutor(max_workers=1)

        mock_agent = MagicMock()
        mock_clone = MagicMock()
        mock_clone.llm.total_tokens = 100
        mock_clone._changed_files = {"a.py"}
        mock_clone.implement_and_verify.return_value = {
            "pass": True,
            "summary": "All tests passed",
            "task_verification": [{"task_id": "t1", "passes": True}],
        }
        mock_agent.clone.return_value = mock_clone

        task = _make_task("t1")
        result = executor._execute_single(task, mock_agent, "", "")

        assert result.success is True
        assert result.task_id == "t1"
        assert "a.py" in result.files_changed

    def test_failed_execution(self):
        executor = ParallelExecutor(max_workers=1)

        mock_agent = MagicMock()
        mock_clone = MagicMock()
        mock_clone.llm.total_tokens = 50
        mock_clone._changed_files = set()
        mock_clone.implement_and_verify.return_value = {
            "pass": False,
            "summary": "Tests failed",
            "task_verification": [],
        }
        mock_agent.clone.return_value = mock_clone

        task = _make_task("t1")
        result = executor._execute_single(task, mock_agent, "", "")

        assert result.success is False
        assert "Tests failed" in result.error

    def test_exception_handling(self):
        executor = ParallelExecutor(max_workers=1)

        mock_agent = MagicMock()
        mock_clone = MagicMock()
        mock_clone.implement_and_verify.side_effect = RuntimeError("Boom")
        mock_clone.llm.total_tokens = 0
        mock_agent.clone.return_value = mock_clone

        task = _make_task("t1")
        result = executor._execute_single(task, mock_agent, "", "")

        assert result.success is False
        assert "Boom" in result.error
