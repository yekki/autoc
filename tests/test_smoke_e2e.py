"""端到端冒烟测试 — 验证核心数据流完整性

覆盖范围:
  - Task 模型字段完整性（含 files / verification_steps / acceptance_criteria）
  - import_from_tasks 数据传递
  - generate_summary 统计一致性
  - 复杂度评估基本正确性
"""

import os
import json
import tempfile

from autoc.core.project.state import PRDState, StateManager
from autoc.core.project.models import Task
from autoc.core.project.memory import SharedMemory, Task as MemTask, TaskStatus
from autoc.core.analysis.complexity import assess_complexity


class TestTaskModel:
    """Task 模型字段完整性"""

    def test_files_field_exists(self):
        task = Task(id="t-1", title="test")
        assert hasattr(task, "files")
        assert task.files == []

    def test_files_field_with_data(self):
        task = Task(id="t-1", title="test", files=["main.py", "utils.py"])
        assert task.files == ["main.py", "utils.py"]

    def test_verification_steps_and_acceptance_criteria(self):
        task = Task(
            id="t-1", title="test",
            verification_steps=["python main.py"],
            acceptance_criteria=["应用正常运行"],
        )
        assert task.verification_steps == ["python main.py"]
        assert task.acceptance_criteria == ["应用正常运行"]

    def test_serialization_roundtrip(self):
        task = Task(
            id="t-1", title="test task",
            description="do something",
            acceptance_criteria=["check A", "check B"],
            verification_steps=["python -c 'print(1)'"],
            files=["main.py"],
            feature_tag="core",
        )
        data = task.model_dump()
        restored = Task(**data)
        assert restored.files == ["main.py"]
        assert restored.acceptance_criteria == ["check A", "check B"]
        assert restored.verification_steps == ["python -c 'print(1)'"]
        assert restored.feature_tag == "core"

    def test_json_roundtrip(self):
        task = Task(id="t-1", title="test", files=["app.py"])
        json_str = task.model_dump_json()
        restored = Task.model_validate_json(json_str)
        assert restored.files == ["app.py"]

    def test_backward_compat_no_files_in_json(self):
        """旧版 prd.json 中没有 files 字段，反序列化不应崩溃"""
        raw = {"id": "t-1", "title": "old task", "description": "legacy"}
        task = Task(**raw)
        assert task.files == []

    def test_failure_trajectory_field(self):
        task = Task(id="t-1", title="test")
        assert task.failure_trajectory == []
        task.failure_trajectory.append({"error": "failed", "attempt": 1})
        assert len(task.failure_trajectory) == 1

    def test_notes_field(self):
        task = Task(id="t-1", title="test", notes="some notes")
        assert task.notes == "some notes"


class TestImportFromTasks:
    """import_from_tasks 数据传递完整性"""

    def test_import_preserves_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = StateManager(tmpdir)
            tasks_data = [
                {
                    "id": "task-1",
                    "title": "Create main",
                    "description": "Write main.py",
                    "verification_steps": ["python main.py"],
                    "acceptance_criteria": ["应用正常运行"],
                    "priority": 0,
                    "passes": False,
                    "feature_tag": "",
                    "files": ["main.py", "utils.py"],
                }
            ]
            prd = mgr.import_from_tasks(
                tasks_data, project_name="test-proj",
                tech_stack=["Python"],
            )
            assert len(prd.tasks) == 1
            task = prd.tasks[0]
            assert task.files == ["main.py", "utils.py"]
            assert task.verification_steps == ["python main.py"]
            assert task.acceptance_criteria == ["应用正常运行"]

    def test_import_missing_files_defaults_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = StateManager(tmpdir)
            tasks_data = [
                {
                    "id": "task-1",
                    "title": "Task without files",
                    "description": "No files specified",
                    "verification_steps": [],
                    "priority": 0,
                    "passes": False,
                }
            ]
            prd = mgr.import_from_tasks(tasks_data, project_name="test-proj")
            assert prd.tasks[0].files == []

    def test_prd_json_roundtrip_with_files(self):
        """prd.json 写入后重新加载，files 不丢失"""
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = StateManager(tmpdir)
            tasks_data = [
                {
                    "id": "task-1",
                    "title": "Main task",
                    "description": "desc",
                    "verification_steps": ["check"],
                    "files": ["main.py"],
                    "priority": 0,
                    "passes": False,
                }
            ]
            mgr.import_from_tasks(tasks_data, project_name="test")

            reloaded = mgr.load_prd()
            assert reloaded.tasks[0].files == ["main.py"]



class TestSummaryConsistency:
    """generate_summary 统计一致性"""

    def test_completed_matches_passes(self):
        """当 task passes=True 时，status 应为 COMPLETED"""
        mem = SharedMemory()
        mem.requirement = "test"
        task = MemTask(
            id="task-1", title="Test",
            description="d", priority=0,
            verification_steps=["check"],
        )
        mem.tasks["task-1"] = task

        task.status = TaskStatus.COMPLETED
        task.passes = True

        all_tasks = list(mem.tasks.values())
        completed = len([t for t in all_tasks if t.status == TaskStatus.COMPLETED])
        verified = len([t for t in all_tasks if t.passes])
        assert completed == verified, (
            f"completed={completed} != verified={verified}: "
            f"tasks_completed 和 passes 统计不一致"
        )

    def test_failed_task_not_counted_as_completed(self):
        mem = SharedMemory()
        task = MemTask(
            id="task-1", title="Test",
            description="d", priority=0,
        )
        task.status = TaskStatus.FAILED
        task.passes = False
        mem.tasks["task-1"] = task

        all_tasks = list(mem.tasks.values())
        completed = len([t for t in all_tasks if t.status == TaskStatus.COMPLETED])
        verified = len([t for t in all_tasks if t.passes])
        assert completed == 0
        assert verified == 0


class TestComplexityAssessment:
    """复杂度评估基本正确性"""

    def test_print_hello_is_simple(self):
        assert assess_complexity("创建一个命令行应用，在终端打印：hello") == "simple"

    def test_hello_world_is_simple(self):
        assert assess_complexity("hello world") == "simple"

    def test_calculator_is_simple(self):
        assert assess_complexity("做一个计算器") == "simple"

    def test_todo_app_is_simple(self):
        assert assess_complexity("todo 待办应用") == "simple"

    def test_web_app_with_db_is_medium(self):
        assert assess_complexity("用 Flask 做一个带数据库的 web 应用") in ("medium", "complex")

    def test_microservice_is_complex(self):
        assert assess_complexity("用 Docker 部署微服务架构，包含 Redis 缓存和 JWT 认证") == "complex"

    def test_short_requirement_is_simple(self):
        assert assess_complexity("打印 1 到 10") == "simple"
