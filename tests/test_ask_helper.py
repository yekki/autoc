"""ask_helper 工具链路测试

覆盖: _helper_llm 注入 → get_tools 暴露 → _handle_ask_helper 执行 → clone 保留。
"""

from unittest.mock import MagicMock
from tests.conftest import _build_minimal_agent


def _make_code_act_agent(tmp_path, mock_llm):
    """构造 CodeActAgent 实例"""
    import os
    os.makedirs(str(tmp_path / "ws"), exist_ok=True)

    from autoc.agents.code_act_agent import CodeActAgent

    mock_memory = MagicMock()
    mock_memory.project_plan = None
    mock_memory.tasks = {}
    mock_memory.requirement = ""
    mock_memory.to_context_string.return_value = ""

    mock_file_ops = MagicMock()
    mock_file_ops.workspace_dir = str(tmp_path / "ws")

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


class TestAskHelperToolExposure:
    """ask_helper 工具定义是否正确暴露"""

    def test_helper_llm_none_tool_not_exposed(self, tmp_path):
        """_helper_llm=None → get_tools() 不含 ask_helper"""
        agent = _make_code_act_agent(tmp_path, MagicMock())
        assert agent._helper_llm is None
        tool_names = [t["function"]["name"] for t in agent.get_tools()]
        assert "ask_helper" not in tool_names

    def test_helper_llm_injected_tool_exposed(self, tmp_path):
        """_helper_llm 注入后 → get_tools() 含 ask_helper"""
        agent = _make_code_act_agent(tmp_path, MagicMock())
        agent._helper_llm = MagicMock()
        tool_names = [t["function"]["name"] for t in agent.get_tools()]
        assert "ask_helper" in tool_names


class TestHandleAskHelper:
    """_handle_ask_helper() 执行逻辑"""

    def test_handle_ask_helper_success(self, tmp_path):
        agent = _make_code_act_agent(tmp_path, MagicMock())
        helper_llm = MagicMock()
        helper_llm.chat.return_value = {"content": "用 Flask 的 app.run(debug=True)"}
        agent._helper_llm = helper_llm

        result = agent._handle_ask_helper({"question": "怎么启动 Flask？"})
        assert result.startswith("[辅助 AI 回复]")
        assert "Flask" in result

    def test_handle_ask_helper_no_llm_skip(self, tmp_path):
        agent = _make_code_act_agent(tmp_path, MagicMock())
        result = agent._handle_ask_helper({"question": "test"})
        assert "[跳过]" in result

    def test_handle_ask_helper_llm_error(self, tmp_path):
        agent = _make_code_act_agent(tmp_path, MagicMock())
        helper_llm = MagicMock()
        helper_llm.chat.side_effect = RuntimeError("API timeout")
        agent._helper_llm = helper_llm

        result = agent._handle_ask_helper({"question": "test"})
        assert "[错误]" in result


class TestCloneHelperLlm:
    """clone() 对 _helper_llm 的保留"""

    def test_clone_preserves_helper_llm(self, tmp_path):
        agent = _make_code_act_agent(tmp_path, MagicMock())
        helper_llm = MagicMock()
        agent._helper_llm = helper_llm

        cloned = agent.clone()
        assert cloned._helper_llm is helper_llm

    def test_clone_ask_helper_binds_to_clone(self, tmp_path):
        """克隆实例的 ask_helper handler 应绑定到克隆对象"""
        agent = _make_code_act_agent(tmp_path, MagicMock())
        helper_llm = MagicMock()
        helper_llm.chat.return_value = {"content": "answer"}
        agent._helper_llm = helper_llm

        cloned = agent.clone()
        assert cloned._registry.has("ask_helper")
        result = cloned._registry.dispatch("ask_helper", {"question": "test"})
        assert "[辅助 AI 回复]" in result
