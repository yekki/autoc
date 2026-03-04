"""CritiqueAgent 评审链路测试

覆盖：review_task 评分逻辑 / 强制不通过规则 / 异常回退 / review_project 聚合
"""

from unittest.mock import MagicMock, patch

import pytest

from autoc.agents.critique import (
    CritiqueAgent,
    CRITIQUE_DIMENSIONS,
    PASS_THRESHOLD,
    MAX_SCORE_PER_DIM,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.total_tokens = 0
    llm.prompt_tokens = 0
    llm.cache_stats = {"hits": 0, "misses": 0}
    return llm


def _make_critique_agent(mock_llm, tmp_path):
    mock_memory = MagicMock()
    mock_memory.project_plan = None
    mock_memory.tasks = {}
    mock_memory.requirement = ""
    mock_memory.to_context_string.return_value = ""

    mock_file_ops = MagicMock()
    mock_file_ops.workspace_dir = str(tmp_path)

    mock_shell = MagicMock()

    return CritiqueAgent(
        name="CritiqueAgent",
        role_description="代码评审专家",
        llm_client=mock_llm,
        memory=mock_memory,
        file_ops=mock_file_ops,
        shell=mock_shell,
        max_iterations=5,
        color="magenta",
    )


# ======================= 常量验证 =======================


class TestConstants:

    def test_four_dimensions(self):
        assert len(CRITIQUE_DIMENSIONS) == 4
        assert "correctness" in CRITIQUE_DIMENSIONS
        assert "quality" in CRITIQUE_DIMENSIONS

    def test_pass_threshold(self):
        assert PASS_THRESHOLD == 85

    def test_max_score(self):
        assert MAX_SCORE_PER_DIM == 25


# ======================= review_task =======================


class TestReviewTask:

    def test_pass_when_high_scores(self, mock_llm, tmp_path):
        """总分 >= 85 且无维度 < 10 → passed=True"""
        agent = _make_critique_agent(mock_llm, tmp_path)

        def fake_run(prompt):
            agent._submitted_critique = {
                "scores": {
                    "correctness": 23, "quality": 22,
                    "completeness": 21, "best_practices": 22,
                },
                "summary": "优秀实现",
                "issues": [],
                "passed": True,
            }

        with patch.object(agent, "run", side_effect=fake_run):
            report = agent.review_task(
                task_id="task-1",
                task_title="实现用户注册",
                task_description="用户注册功能",
                task_files=["auth.py"],
                verification_steps=["注册成功"],
            )
        assert report["passed"] is True
        assert report["total_score"] == 88

    def test_fail_when_low_total(self, mock_llm, tmp_path):
        """总分 < 85 → passed=False"""
        agent = _make_critique_agent(mock_llm, tmp_path)

        def fake_run(prompt):
            agent._submitted_critique = {
                "scores": {
                    "correctness": 15, "quality": 15,
                    "completeness": 15, "best_practices": 15,
                },
                "summary": "有改进空间",
                "issues": [{"file": "main.py", "line": 10, "issue": "缺少错误处理"}],
                "passed": False,
            }

        with patch.object(agent, "run", side_effect=fake_run):
            report = agent.review_task(
                task_id="task-1",
                task_title="实现用户注册",
                task_description="测试",
                task_files=["main.py"],
                verification_steps=["OK"],
            )
        assert report["passed"] is False
        assert report["total_score"] == 60

    def test_force_fail_when_any_dim_below_10(self, mock_llm, tmp_path):
        """任何维度 < 10 → 强制不通过，即使总分 >= 85"""
        agent = _make_critique_agent(mock_llm, tmp_path)

        def fake_run(prompt):
            agent._submitted_critique = {
                "scores": {
                    "correctness": 25, "quality": 25,
                    "completeness": 25, "best_practices": 9,  # < 10
                },
                "summary": "best_practices 有问题",
                "issues": [],
                "passed": True,  # LLM 说通过了
            }

        with patch.object(agent, "run", side_effect=fake_run):
            report = agent.review_task(
                task_id="task-1",
                task_title="测试",
                task_description="测试",
                task_files=[],
                verification_steps=[],
            )
        assert report["passed"] is False  # 强制覆盖
        assert report["total_score"] == 84

    def test_fallback_when_no_submission(self, mock_llm, tmp_path):
        """Agent 未提交结构化报告 → 回退到默认报告"""
        agent = _make_critique_agent(mock_llm, tmp_path)
        with patch.object(agent, "run"):
            report = agent.review_task(
                task_id="task-1",
                task_title="测试",
                task_description="测试",
                task_files=[],
                verification_steps=[],
            )
        assert report["passed"] is False
        assert "task_id" in report

    def test_exception_returns_fallback(self, mock_llm, tmp_path):
        """Agent.run() 异常 → 回退报告"""
        agent = _make_critique_agent(mock_llm, tmp_path)
        with patch.object(agent, "run", side_effect=Exception("LLM timeout")):
            report = agent.review_task(
                task_id="task-1",
                task_title="测试",
                task_description="测试",
                task_files=[],
                verification_steps=[],
            )
        assert report["passed"] is False
        assert report["task_id"] == "task-1"


# ======================= _handle_submit_critique =======================


class TestSubmitCritique:

    def test_stores_critique_data(self, mock_llm, tmp_path):
        agent = _make_critique_agent(mock_llm, tmp_path)
        result = agent._handle_submit_critique({
            "scores": {"correctness": 20, "quality": 20, "completeness": 20, "best_practices": 20},
            "summary": "良好",
            "issues": [{"file": "a.py", "line": 1, "issue": "test"}],
            "passed": False,
        })
        assert agent._submitted_critique is not None
        assert agent._submitted_critique["scores"]["correctness"] == 20
        assert "80/100" in result


# ======================= review_project =======================


class TestReviewProject:

    def test_aggregates_multiple_tasks(self, mock_llm, tmp_path):
        """review_project 聚合多个任务"""
        agent = _make_critique_agent(mock_llm, tmp_path)

        def fake_run(prompt):
            agent._submitted_critique = {
                "scores": {
                    "correctness": 22, "quality": 22,
                    "completeness": 22, "best_practices": 22,
                },
                "summary": "整体良好",
                "issues": [],
                "passed": True,
            }

        with patch.object(agent, "run", side_effect=fake_run):
            report = agent.review_project(
                tasks=[
                    {"id": "t1", "title": "任务1", "description": "desc",
                     "files": ["a.py"], "verification_steps": ["ok"]},
                    {"id": "t2", "title": "任务2", "description": "desc",
                     "files": ["b.py"], "verification_steps": ["ok"]},
                ],
                requirement="创建一个API服务",
            )
        assert report["total_score"] == 88
        assert report["passed"] is True
