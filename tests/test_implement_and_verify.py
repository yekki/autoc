"""implement_and_verify() 入口测试

覆盖: 正常流程、异常兜底、阻塞检测、无产出检测、兜底解析、工具注册。
"""

from unittest.mock import MagicMock, patch, ANY
from autoc.core.project.memory import Task, TaskStatus


def _make_code_act_agent(tmp_path, mock_llm):
    import os
    ws = str(tmp_path / "ws")
    os.makedirs(ws, exist_ok=True)

    from autoc.agents.code_act_agent import CodeActAgent

    mock_memory = MagicMock()
    mock_memory.project_plan = None
    mock_memory.tasks = {}
    mock_memory.requirement = ""
    mock_memory.to_context_string.return_value = ""
    mock_memory.update_task = MagicMock()

    mock_file_ops = MagicMock()
    mock_file_ops.workspace_dir = ws

    agent = CodeActAgent(
        name="TestImpl",
        role_description="测试实现者",
        llm_client=mock_llm,
        memory=mock_memory,
        file_ops=mock_file_ops,
        shell=MagicMock(),
        max_iterations=5,
    )
    return agent


def _make_task():
    return Task(
        id="task-1",
        title="实现登录",
        description="实现用户登录功能",
        priority=0,
        verification_steps=["curl localhost:5000/login 返回 200"],
        feature_tag="auth",
    )


class TestNormalFlow:

    @patch("autoc.agents.base.console")
    def test_normal_flow_with_report_tool(self, mock_console, tmp_path, mock_llm):
        """run() 成功 + _submitted_report 被设置 → 返回结构化报告"""
        agent = _make_code_act_agent(tmp_path, mock_llm)
        task = _make_task()

        submitted_report = {
            "pass": True,
            "summary": "登录功能实现完毕",
            "task_verification": [{"task_id": "task-1", "passes": True}],
        }

        def fake_run(prompt):
            agent._changed_files.add("app.py")
            agent._submitted_report = submitted_report
            return "任务完成"

        with patch.object(agent, "run", side_effect=fake_run):
            report = agent.implement_and_verify(task)

        assert report["pass"] is True
        assert report["summary"] == "登录功能实现完毕"

    @patch("autoc.agents.base.console")
    def test_run_exception_returns_error_report(self, mock_console, tmp_path, mock_llm):
        """run() 抛异常 → _build_error_report 兜底"""
        agent = _make_code_act_agent(tmp_path, mock_llm)
        task = _make_task()

        with patch.object(agent, "run", side_effect=RuntimeError("API 超时")):
            report = agent.implement_and_verify(task)

        assert report.get("pass") is False

    @patch("autoc.agents.base.console")
    def test_blocked_output_marks_task(self, mock_console, tmp_path, mock_llm):
        """输出含 [BLOCKED] → 返回失败报告"""
        agent = _make_code_act_agent(tmp_path, mock_llm)
        task = _make_task()

        def fake_run(prompt):
            agent._changed_files.add("app.py")
            return "[BLOCKED] 需要数据库但 Docker 未启动"

        with patch.object(agent, "run", side_effect=fake_run):
            report = agent.implement_and_verify(task)

        assert report.get("pass") is False
        agent.memory.update_task.assert_any_call(
            "task-1",
            status=TaskStatus.BLOCKED,
            block_reason=ANY,
            block_attempts=ANY,
        )

    @patch("autoc.agents.base.console")
    def test_no_files_changed_fails(self, mock_console, tmp_path, mock_llm):
        """_changed_files 为空 → 返回失败报告"""
        agent = _make_code_act_agent(tmp_path, mock_llm)
        task = _make_task()

        with patch.object(agent, "run", return_value="分析完成但没写代码"):
            report = agent.implement_and_verify(task)

        assert report.get("pass") is False
        assert "未产出" in report.get("summary", "")

    @patch("autoc.agents.base.console")
    def test_fallback_parse_from_output(self, mock_console, tmp_path, mock_llm):
        """无 _submitted_report → 从 output 解析报告"""
        agent = _make_code_act_agent(tmp_path, mock_llm)
        task = _make_task()

        def fake_run(prompt):
            agent._changed_files.add("app.py")
            return "## 验收报告\n所有测试通过"

        with patch.object(agent, "run", side_effect=fake_run):
            report = agent.implement_and_verify(task)

        assert isinstance(report, dict)
        assert "summary" in report or "pass" in report

    @patch("autoc.agents.base.console")
    def test_submit_test_report_tool_registered(self, mock_console, tmp_path, mock_llm):
        """首次调用注册 submit_test_report 工具"""
        agent = _make_code_act_agent(tmp_path, mock_llm)
        task = _make_task()

        with patch.object(agent, "run", return_value="done"):
            agent._changed_files.add("x.py")
            with patch.object(agent, "run", side_effect=lambda p: (
                agent._changed_files.add("x.py") or "done"
            )):
                agent.implement_and_verify(task)

        assert agent._registry.has("submit_test_report")
