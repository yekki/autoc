"""LLM 输出类型容错测试

覆盖：所有接收 LLM JSON 的 Pydantic 模型字段类型自动转换，
以及 parse_plan / validate_plan 对非标准 LLM 输出的容错。

背景：LLM 返回的 JSON 中，字段类型经常与 schema 不一致，例如
- id 返回 int 而非 str
- priority 返回 "high" 而非 0
- list[str] 字段返回 list[int] 或单个 str
- int 字段返回 str
- float 字段返回 str
- 字段为 None 而非默认值
"""

import json

import pytest

from autoc.core.project.models import (
    Task, TaskStatus, BugReport, ProjectPlan, TechDecision,
    RefinedRequirement, ClarificationRequest,
)
from autoc.core.planning.validator import parse_plan, validate_plan


# =====================================================================
# Task 模型类型容错
# =====================================================================

class TestTaskCoercion:

    def test_int_id(self):
        t = Task(id=1, title="test")
        assert t.id == "1"
        assert isinstance(t.id, str)

    def test_float_id(self):
        t = Task(id=3.14, title="test")
        assert t.id == "3.14"

    def test_none_id(self):
        t = Task(id=None, title="test")
        assert t.id == ""

    def test_priority_string_high(self):
        t = Task(id="1", title="test", priority="high")
        assert t.priority == 0

    def test_priority_string_medium(self):
        t = Task(id="1", title="test", priority="medium")
        assert t.priority == 1

    def test_priority_string_low(self):
        t = Task(id="1", title="test", priority="low")
        assert t.priority == 2

    def test_priority_string_critical(self):
        t = Task(id="1", title="test", priority="critical")
        assert t.priority == 0

    def test_priority_string_number(self):
        t = Task(id="1", title="test", priority="2")
        assert t.priority == 2

    def test_priority_none(self):
        t = Task(id="1", title="test", priority=None)
        assert t.priority == 0

    def test_priority_unknown_string(self):
        t = Task(id="1", title="test", priority="urgent")
        assert t.priority == 0

    def test_dependencies_int_list(self):
        t = Task(id="1", title="test", dependencies=[1, 2, 3])
        assert t.dependencies == ["1", "2", "3"]

    def test_dependencies_mixed_types(self):
        t = Task(id="1", title="test", dependencies=["task-1", 2, "task-3"])
        assert t.dependencies == ["task-1", "2", "task-3"]

    def test_dependencies_none(self):
        t = Task(id="1", title="test", dependencies=None)
        assert t.dependencies == []

    def test_files_single_string(self):
        t = Task(id="1", title="test", files="main.py")
        assert t.files == ["main.py"]

    def test_files_none(self):
        t = Task(id="1", title="test", files=None)
        assert t.files == []

    def test_files_int_list(self):
        """极端情况：LLM 返回数字文件名"""
        t = Task(id="1", title="test", files=[1, 2])
        assert t.files == ["1", "2"]

    def test_files_dict_list_via_parse_plan(self):
        """LLM 返回 files 为 [{path, content}] 字典列表 — 曾导致代码标签页乱码"""
        raw = json.dumps({
            "tasks": [{
                "id": "1",
                "title": "打印你好",
                "description": "创建命令行应用打印你好",
                "files": [
                    {"path": "main.py", "content": "#!/usr/bin/env python3\nprint('你好')"},
                    {"path": "README.md", "content": "# Hello"},
                ],
                "verification_steps": ["python main.py"],
            }]
        })
        plan = parse_plan(raw)
        assert plan is not None
        assert plan.tasks[0].files == ["main.py", "README.md"]

    def test_verification_steps_single_string(self):
        t = Task(id="1", title="test", verification_steps="python main.py")
        assert t.verification_steps == ["python main.py"]

    def test_verification_steps_none(self):
        t = Task(id="1", title="test", verification_steps=None)
        assert t.verification_steps == []

    def test_acceptance_criteria_none(self):
        t = Task(id="1", title="test", acceptance_criteria=None)
        assert t.acceptance_criteria == []

    def test_full_llm_style_dict(self):
        """模拟 LLM 返回的完整 task dict"""
        raw = {
            "id": 1,
            "title": "实现用户登录",
            "description": "创建登录页面和后端验证",
            "priority": "high",
            "dependencies": [0],
            "files": ["login.py", "templates/login.html"],
            "verification_steps": ["python -c 'import login'", "test -f login.py"],
            "feature_tag": "auth",
        }
        t = Task(**raw)
        assert t.id == "1"
        assert t.priority == 0
        assert t.dependencies == ["0"]
        assert len(t.files) == 2
        assert t.feature_tag == "auth"


# =====================================================================
# BugReport 模型类型容错
# =====================================================================

class TestBugReportCoercion:

    def test_int_id(self):
        b = BugReport(id=42, title="bug", description="desc")
        assert b.id == "42"

    def test_none_id(self):
        b = BugReport(id=None, title="bug", description="desc")
        assert b.id == ""

    def test_line_number_string(self):
        b = BugReport(id="1", title="bug", description="d", line_number="15")
        assert b.line_number == 15

    def test_line_number_none(self):
        b = BugReport(id="1", title="bug", description="d", line_number=None)
        assert b.line_number == 0

    def test_line_number_empty_string(self):
        b = BugReport(id="1", title="bug", description="d", line_number="")
        assert b.line_number == 0

    def test_line_number_invalid_string(self):
        b = BugReport(id="1", title="bug", description="d", line_number="unknown")
        assert b.line_number == 0

    def test_fix_attempts_string(self):
        b = BugReport(id="1", title="bug", description="d", fix_attempts="3")
        assert b.fix_attempts == 3

    def test_fix_attempts_none(self):
        b = BugReport(id="1", title="bug", description="d", fix_attempts=None)
        assert b.fix_attempts == 0

    def test_affected_functions_int_list(self):
        b = BugReport(id="1", title="bug", description="d", affected_functions=[1, 2])
        assert b.affected_functions == ["1", "2"]

    def test_affected_functions_single_string(self):
        b = BugReport(id="1", title="bug", description="d", affected_functions="main")
        assert b.affected_functions == ["main"]

    def test_affected_functions_none(self):
        b = BugReport(id="1", title="bug", description="d", affected_functions=None)
        assert b.affected_functions == []

    def test_affected_functions_mixed(self):
        b = BugReport(id="1", title="b", description="d",
                       affected_functions=["func_a", 42, "func_c"])
        assert b.affected_functions == ["func_a", "42", "func_c"]

    def test_full_llm_style_bug(self):
        """模拟 CodeActAgent._process_report 中 LLM 产出的 bug_data"""
        raw = {
            "id": 1,
            "title": "Login validation fails",
            "description": "Password check always returns true",
            "severity": "high",
            "file_path": "auth.py",
            "line_number": "42",
            "affected_functions": ["validate_password", "check_hash"],
            "fix_attempts": "0",
        }
        b = BugReport(**raw)
        assert b.id == "1"
        assert b.line_number == 42
        assert b.fix_attempts == 0
        assert len(b.affected_functions) == 2


# =====================================================================
# RefinedRequirement 模型类型容错
# =====================================================================

class TestRefinedRequirementCoercion:

    def test_quality_string(self):
        r = RefinedRequirement(original="a", refined="b", quality_before="0.75")
        assert r.quality_before == 0.75

    def test_quality_none(self):
        r = RefinedRequirement(original="a", refined="b", quality_before=None)
        assert r.quality_before == 0.0

    def test_quality_invalid_string(self):
        r = RefinedRequirement(original="a", refined="b", quality_after="good")
        assert r.quality_after == 0.0

    def test_tech_hints_single_string(self):
        r = RefinedRequirement(original="a", refined="b", tech_hints="python")
        assert r.tech_hints == ["python"]

    def test_tech_hints_none(self):
        r = RefinedRequirement(original="a", refined="b", tech_hints=None)
        assert r.tech_hints == []

    def test_suggested_split_int_list(self):
        r = RefinedRequirement(original="a", refined="b", suggested_split=[1, 2])
        assert r.suggested_split == ["1", "2"]

    def test_enhancements_none(self):
        r = RefinedRequirement(original="a", refined="b", enhancements=None)
        assert r.enhancements == []


# =====================================================================
# ClarificationRequest 模型类型容错
# =====================================================================

class TestClarificationRequestCoercion:

    def test_questions_none(self):
        c = ClarificationRequest(questions=None)
        assert c.questions == []

    def test_questions_single_string(self):
        c = ClarificationRequest(questions="你的目标用户是谁？")
        assert c.questions == ["你的目标用户是谁？"]

    def test_defaults_int_list(self):
        c = ClarificationRequest(defaults=[1, 2])
        assert c.defaults == ["1", "2"]


# =====================================================================
# ProjectPlan 模型类型容错
# =====================================================================

class TestProjectPlanCoercion:

    def test_description_dict(self):
        p = ProjectPlan(description={"summary": "a web app"})
        assert isinstance(p.description, str)
        assert "summary" in p.description

    def test_description_none(self):
        p = ProjectPlan(description=None)
        assert p.description == ""

    def test_tech_stack_comma_string(self):
        p = ProjectPlan(tech_stack="python, flask, sqlite")
        assert p.tech_stack == ["python", "flask", "sqlite"]

    def test_tech_stack_none(self):
        p = ProjectPlan(tech_stack=None)
        assert p.tech_stack == []

    def test_user_stories_string(self):
        p = ProjectPlan(user_stories="用户可以登录")
        assert p.user_stories == ["用户可以登录"]

    def test_user_stories_none(self):
        p = ProjectPlan(user_stories=None)
        assert p.user_stories == []

    def test_architecture_list(self):
        p = ProjectPlan(architecture=["MVC", "REST"])
        assert isinstance(p.architecture, str)
        assert "MVC" in p.architecture

    def test_risk_assessment_dict(self):
        p = ProjectPlan(risk_assessment={"level": "low", "detail": "none"})
        assert isinstance(p.risk_assessment, str)


# =====================================================================
# parse_plan — LLM JSON 输出边界测试
# =====================================================================

class TestParsePlanLLMOutput:

    def test_int_task_ids(self):
        """LLM 返回 int 类型 task id"""
        raw = json.dumps({
            "project_name": "test",
            "tasks": [{
                "id": 1,
                "title": "初始化项目",
                "description": "创建项目结构和配置文件",
                "files": ["main.py", "config.py"],
                "verification_steps": ["python main.py", "test -f config.py"],
            }]
        })
        plan = parse_plan(raw)
        assert plan is not None
        assert plan.tasks[0].id == "1"

    def test_int_priority(self):
        """LLM 返回字符串 priority"""
        raw = json.dumps({
            "tasks": [{
                "id": "task-1",
                "title": "核心功能",
                "description": "实现核心逻辑",
                "priority": "high",
                "files": ["core.py"],
                "verification_steps": ["python core.py"],
            }]
        })
        plan = parse_plan(raw)
        assert plan is not None
        assert plan.tasks[0].priority == 0

    def test_int_dependencies(self):
        """LLM 返回 int 类型的 dependencies"""
        raw = json.dumps({
            "tasks": [
                {
                    "id": 1,
                    "title": "基础",
                    "description": "基础设施搭建",
                    "files": ["base.py"],
                    "verification_steps": ["python base.py"],
                },
                {
                    "id": 2,
                    "title": "功能",
                    "description": "功能开发",
                    "dependencies": [1],
                    "files": ["feature.py"],
                    "verification_steps": ["python feature.py"],
                },
            ]
        })
        plan = parse_plan(raw)
        assert plan is not None
        assert plan.tasks[1].dependencies == ["1"]

    def test_missing_optional_fields(self):
        """LLM 输出缺少可选字段"""
        raw = json.dumps({
            "tasks": [{
                "id": "t1",
                "title": "任务",
                "description": "做一些事",
                "files": ["app.py"],
                "verification_steps": ["python app.py"],
            }]
        })
        plan = parse_plan(raw)
        assert plan is not None
        assert plan.tasks[0].dependencies == []
        assert plan.tasks[0].feature_tag == ""

    def test_none_values_in_task(self):
        """LLM 输出中字段为 null"""
        raw = json.dumps({
            "tasks": [{
                "id": "t1",
                "title": "任务",
                "description": "做一些事",
                "files": ["app.py"],
                "verification_steps": ["python app.py"],
                "dependencies": None,
                "feature_tag": None,
            }]
        })
        plan = parse_plan(raw, requirement_text="test")
        assert plan is not None
        t = plan.tasks[0]
        assert t.dependencies == []

    def test_markdown_wrapped_json(self):
        """LLM 用 markdown 代码块包裹 JSON"""
        raw = '```json\n{"tasks": [{"id": 1, "title": "T1", "description": "d", "files": ["a.py"], "verification_steps": ["python a.py"]}]}\n```'
        plan = parse_plan(raw)
        assert plan is not None
        assert plan.tasks[0].id == "1"

    def test_tech_stack_as_string(self):
        """LLM 将 tech_stack 作为逗号分隔字符串返回"""
        raw = json.dumps({
            "project_name": "test",
            "tech_stack": "Python, Flask, SQLite",
            "tasks": [{
                "id": "t1", "title": "T", "description": "d",
                "files": ["a.py"], "verification_steps": ["python a.py"],
            }]
        })
        plan = parse_plan(raw)
        assert plan is not None
        assert "Python" in plan.tech_stack
        assert len(plan.tech_stack) == 3

    def test_architecture_as_dict(self):
        """LLM 将 architecture 作为 dict 返回"""
        raw = json.dumps({
            "architecture": {"pattern": "MVC", "layers": ["model", "view"]},
            "tasks": [{
                "id": "t1", "title": "T", "description": "d",
                "files": ["a.py"], "verification_steps": ["python a.py"],
            }]
        })
        plan = parse_plan(raw)
        assert plan is not None
        assert isinstance(plan.architecture, str)
        assert "MVC" in plan.architecture

    def test_all_numeric_ids_plan(self):
        """完整计划，所有 id 均为数字（glm-4 典型输出）"""
        raw = json.dumps({
            "project_name": "hello-app",
            "description": "打印你好的命令行程序",
            "tech_stack": ["Python"],
            "tasks": [
                {
                    "id": 1,
                    "title": "创建主程序",
                    "description": "创建 main.py 实现打印功能",
                    "priority": 0,
                    "files": ["main.py"],
                    "verification_steps": ["python main.py"],
                    "dependencies": [],
                },
            ]
        })
        plan = parse_plan(raw, requirement_text="打印你好")
        assert plan is not None
        assert plan.tasks[0].id == "1"
        issues = validate_plan(plan, complexity="simple")
        assert not issues


# =====================================================================
# validate_plan — 带类型转换的验证
# =====================================================================

class TestValidatePlanWithCoercion:

    def _make_plan(self, tasks_data: list[dict]) -> ProjectPlan:
        tasks = [Task(**t) for t in tasks_data]
        return ProjectPlan(tasks=tasks)

    def test_validate_after_int_coercion(self):
        plan = self._make_plan([{
            "id": 1,
            "title": "核心功能实现",
            "description": "实现项目核心业务逻辑，包含数据处理和输出",
            "files": ["main.py"],
            "verification_steps": ["python main.py"],
        }])
        issues = validate_plan(plan, complexity="simple")
        assert not issues

    def test_validate_topo_sort_with_int_deps(self):
        plan = self._make_plan([
            {
                "id": 1, "title": "基础模块搭建",
                "description": "创建基础设施和配置文件，初始化项目结构",
                "files": ["base.py"],
                "verification_steps": ["python base.py"],
            },
            {
                "id": 2, "title": "业务功能开发",
                "description": "基于基础模块开发核心业务功能",
                "dependencies": [1],
                "files": ["feature.py"],
                "verification_steps": ["python feature.py"],
            },
        ])
        issues = validate_plan(plan, complexity="medium")
        assert not any("循环" in i for i in issues)
        assert plan.tasks[0].id == "1"
