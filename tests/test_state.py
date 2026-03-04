"""测试 state.py — PRDState / StateManager"""

import json
import os

from autoc.core.project.state import PRDState, StateManager
from autoc.core.project.models import Task


class TestPRDState:
    """PRDState 数据模型测试"""

    def test_empty_prd(self):
        prd = PRDState()
        assert prd.project == ""
        assert prd.tasks == []
        assert not prd.all_passed()
        assert prd.needs_planning()

    def test_progress_summary(self):
        prd = PRDState(tasks=[
            Task(id="t-1", title="A", passes=True),
            Task(id="t-2", title="B", passes=False),
        ])
        assert "1/2" in prd.progress_summary()

    def test_all_passed(self):
        prd = PRDState(tasks=[
            Task(id="t-1", title="A", passes=True),
        ])
        assert prd.all_passed()

    def test_needs_planning_with_pending(self):
        """有 pending 任务时不需要规划"""
        prd = PRDState(tasks=[
            Task(id="t-1", title="A", passes=False),
        ])
        assert not prd.needs_planning()

    def test_needs_planning_all_passed(self):
        """所有任务通过且未标记 plan_complete → 需要规划"""
        prd = PRDState(tasks=[
            Task(id="t-1", title="A", passes=True),
        ])
        assert prd.needs_planning()

    def test_plan_complete_no_planning(self):
        """plan_complete=True → 不再需要规划"""
        prd = PRDState(plan_complete=True)
        assert not prd.needs_planning()

    def test_build_completed_summary(self):
        prd = PRDState(tasks=[
            Task(id="t-1", title="画布渲染", passes=True),
            Task(id="t-2", title="碰撞检测", passes=False),
        ])
        summary = prd.build_completed_summary()
        assert "t-1" in summary
        assert "画布渲染" in summary
        assert "碰撞检测" not in summary

    def test_mark_task_passed(self):
        prd = PRDState(tasks=[
            Task(id="t-1", title="A"),
        ])
        prd.mark_task_passed("t-1", True, "ok")
        assert prd.tasks[0].passes
        assert prd.tasks[0].notes == "ok"

    def test_pick_next_task(self):
        prd = PRDState(tasks=[
            Task(id="t-1", title="A", priority=2, passes=False),
            Task(id="t-2", title="B", priority=0, passes=False),
        ])
        task = prd.pick_next_task()
        assert task.id == "t-2"

    def test_serialization_roundtrip(self):
        """序列化 → 反序列化 保留新字段"""
        prd = PRDState(
            project="test", requirement="做一个游戏",
            plan_batch=2, plan_complete=True,
        )
        data = prd.model_dump(by_alias=True)
        prd2 = PRDState(**data)
        assert prd2.requirement == "做一个游戏"
        assert prd2.plan_batch == 2
        assert prd2.plan_complete is True

    def test_backward_compat_old_prd(self):
        """旧版 prd.json（使用 userStories 键）能正常加载"""
        old = {"project": "old", "techStack": ["Python"],
               "userStories": [{"id": "t-1", "title": "X"}]}
        prd = PRDState(**old)
        assert prd.requirement == ""
        assert prd.plan_batch == 0
        assert prd.plan_complete is False
        assert len(prd.tasks) == 1
        assert prd.tasks[0].id == "t-1"


class TestStateManager:
    """StateManager 文件操作测试"""

    def test_load_empty(self, tmp_workspace):
        sm = StateManager(tmp_workspace)
        prd = sm.load_prd()
        assert prd.project == ""

    def test_save_and_load(self, tmp_workspace):
        sm = StateManager(tmp_workspace)
        prd = PRDState(project="test", requirement="hello")
        sm.save_prd(prd)
        loaded = sm.load_prd()
        assert loaded.project == "test"
        assert loaded.requirement == "hello"

    def test_import_from_tasks(self, tmp_workspace, sample_tasks):
        sm = StateManager(tmp_workspace)
        prd = sm.import_from_tasks(
            sample_tasks, project_name="demo",
            tech_stack=["Python"], requirement="做游戏",
        )
        assert len(prd.tasks) == 2
        assert prd.requirement == "做游戏"
        assert sm.has_prd()

    def test_append_tasks_dedup(self, tmp_workspace, sample_tasks):
        sm = StateManager(tmp_workspace)
        sm.import_from_tasks(sample_tasks, project_name="demo")
        new = [Task(id="task-2", title="dup"), Task(id="task-3", title="new")]
        prd = sm.append_tasks(new, batch=1)
        assert len(prd.tasks) == 3
        assert prd.plan_batch == 1

    def test_prd_json_on_disk(self, tmp_workspace):
        sm = StateManager(tmp_workspace)
        sm.save_prd(PRDState(project="disk-test", plan_batch=3))
        path = os.path.join(tmp_workspace, ".autoc", "prd.json")
        assert os.path.exists(path)
        with open(path) as f:
            data = json.load(f)
        assert data["planBatch"] == 3

    def test_progress_init_and_append(self, tmp_workspace):
        sm = StateManager(tmp_workspace)
        sm.init_progress("test-project")
        task = Task(id="t-1", title="Test Story")
        sm.append_progress(task, iteration=1, summary="done",
                           files_changed=["app.py"], learnings=["学到了"])
        content = sm.load_progress()
        assert "Test Story" in content
        assert "app.py" in content
