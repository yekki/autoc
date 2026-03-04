"""测试 snarktank/ralph 精华吸收"""

import os
import json

from autoc.core.project.state import StateManager
from autoc.core.project.models import Task


class TestCodebasePatterns:
    """progress.txt Codebase Patterns 区域"""

    def test_init_has_patterns_section(self, tmp_workspace):
        sm = StateManager(tmp_workspace)
        sm.init_progress("test-project")
        content = sm.load_progress()
        assert "## Codebase Patterns" in content

    def test_load_codebase_patterns(self, tmp_workspace):
        sm = StateManager(tmp_workspace)
        sm.init_progress("test")
        sm.update_codebase_patterns(["Use sql<N> for aggregations"])
        patterns = sm.load_codebase_patterns()
        assert "sql<N>" in patterns

    def test_update_patterns_dedup(self, tmp_workspace):
        sm = StateManager(tmp_workspace)
        sm.init_progress("test")
        sm.update_codebase_patterns(["Pattern A", "Pattern B"])
        sm.update_codebase_patterns(["Pattern B", "Pattern C"])
        content = sm.load_progress()
        assert content.count("Pattern B") == 1
        assert "Pattern C" in content

    def test_patterns_injected_in_context(self, tmp_workspace):
        sm = StateManager(tmp_workspace)
        sm.init_progress("test")
        sm.update_codebase_patterns(["Always use IF NOT EXISTS"])
        patterns = sm.load_codebase_patterns()
        assert "IF NOT EXISTS" in patterns


class TestPytestFileStripping:
    """L5: 自动移除 Dev 任务中的 pytest 文件"""

    def test_strips_test_files_from_task(self):
        from autoc.core.planning.validator import validate_plan
        from autoc.core.project.models import Task, ProjectPlan

        task = Task(
            id="t-1", title="集成测试与优化",
            description="编写测试并优化",
            files=["app.py", "tests/test_app.py", "tests/test_models.py", "README.md"],
            verification_steps=["python -m py_compile app.py"],
        )
        plan = ProjectPlan(tasks=[task])
        validate_plan(plan, complexity="medium")
        assert "tests/test_app.py" not in task.files
        assert "tests/test_models.py" not in task.files
        assert "app.py" in task.files

    def test_keeps_non_test_files(self):
        from autoc.core.planning.validator import validate_plan
        from autoc.core.project.models import Task, ProjectPlan

        task = Task(
            id="t-2", title="核心功能",
            description="实现核心功能模块",
            files=["app.py", "models.py", "utils.py"],
            verification_steps=["python -m py_compile app.py"],
        )
        plan = ProjectPlan(tasks=[task])
        validate_plan(plan, complexity="medium")
        assert task.files == ["app.py", "models.py", "utils.py"]


