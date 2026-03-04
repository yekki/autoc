"""Agent ReAct 主循环测试

覆盖: base.py run() 的基本流程、熔断器、SAIC 迭代控制、上下文管理。
"""

from unittest.mock import MagicMock, patch
from tests.conftest import _build_minimal_agent


def _llm_response(content="", tool_calls=None, reasoning_content=""):
    """构造 LLM chat() 返回值"""
    return {
        "content": content,
        "tool_calls": tool_calls or [],
        "finish_reason": "stop" if not tool_calls else "tool_calls",
        "reasoning_content": reasoning_content,
    }


def _tool_call(name, arguments, call_id="tc-1"):
    return {"id": call_id, "name": name, "arguments": arguments}


class TestBasicFlow:
    """run() 基本流程"""

    @patch("autoc.agents.base.console")
    def test_run_no_tool_calls_exits(self, mock_console, tmp_path, mock_llm):
        """LLM 直接返回文本 → 1 次迭代正常退出"""
        agent = _build_minimal_agent(str(tmp_path), mock_llm)
        mock_llm.chat.return_value = _llm_response(content="任务完成")

        output = agent.run("写一个 hello.py")
        assert output == "任务完成"
        assert agent._iteration_count == 1
        assert mock_llm.chat.call_count == 1

    @patch("autoc.agents.base.console")
    def test_run_tool_call_then_text(self, mock_console, tmp_path, mock_llm):
        """LLM 第 1 轮返回 tool_call → 第 2 轮返回文本 → 完成"""
        agent = _build_minimal_agent(str(tmp_path), mock_llm)
        agent._registry.register_handler(
            "read_file", lambda args: "file content here"
        )
        mock_llm.chat.side_effect = [
            _llm_response(tool_calls=[_tool_call("read_file", {"path": "main.py"})]),
            _llm_response(content="分析完成"),
        ]

        output = agent.run("分析 main.py")
        assert output == "分析完成"
        assert agent._iteration_count == 2

    @patch("autoc.agents.base.console")
    def test_run_content_plus_tool_calls(self, mock_console, tmp_path, mock_llm):
        """LLM 同时返回 content + tool_calls → 消息正确拼接"""
        agent = _build_minimal_agent(str(tmp_path), mock_llm)
        agent._registry.register_handler("read_file", lambda args: "ok")
        mock_llm.chat.side_effect = [
            _llm_response(
                content="让我先看看文件",
                tool_calls=[_tool_call("read_file", {"path": "a.py"})],
            ),
            _llm_response(content="完成"),
        ]

        output = agent.run("检查代码")
        assert output == "完成"
        assert agent._iteration_count == 2

    @patch("autoc.agents.base.console")
    def test_run_max_iterations_exhausted(self, mock_console, tmp_path, mock_llm):
        """LLM 持续返回 tool_call → 达到 max_iterations 上限 → 正常退出"""
        agent = _build_minimal_agent(str(tmp_path), mock_llm, max_iterations=3)
        agent._registry.register_handler("read_file", lambda args: "content")

        mock_llm.chat.return_value = _llm_response(
            tool_calls=[_tool_call("read_file", {"path": "x.py"})]
        )

        agent.run("分析项目")
        hard_cap = int(3 * 1.5)
        assert agent._iteration_count <= hard_cap + 1


class TestCircuitBreaker:
    """熔断器测试"""

    @patch("autoc.agents.base.console")
    def test_circuit_breaker_abort_on_fatal(self, mock_console, tmp_path, mock_llm):
        """工具返回致命错误 → 立即终止"""
        agent = _build_minimal_agent(str(tmp_path), mock_llm)
        agent._registry.register_handler(
            "read_file", lambda args: "[错误] 不在工作区: /etc/passwd"
        )
        mock_llm.chat.return_value = _llm_response(
            tool_calls=[_tool_call("read_file", {"path": "/etc/passwd"})]
        )

        agent.run("读取文件")
        assert agent._iteration_count == 1

    @patch("autoc.agents.base.console")
    def test_circuit_breaker_abort_consecutive(self, mock_console, tmp_path, mock_llm):
        """连续相同错误 → 熔断器先于 StuckDetector 触发终止

        行为：每次工具调用都返回错误 → 熔断器在 circuit_breaker_abort_at 次后 abort，
        stuck 检测被 _abort 保护门控住，不抛 AgentStuckError。
        """
        agent = _build_minimal_agent(str(tmp_path), mock_llm, max_iterations=10)
        agent._registry.register_handler(
            "execute_command", lambda args: "[错误] 命令执行超时"
        )
        mock_llm.chat.return_value = _llm_response(
            tool_calls=[_tool_call("execute_command", {"command": "sleep 999"})]
        )

        # 熔断器触发，Agent 正常退出（不抛异常）
        result = agent.run("执行任务")
        assert agent._consecutive_errors >= agent.circuit_breaker_abort_at

    @patch("autoc.agents.base.console")
    def test_circuit_breaker_warn_at_3(self, mock_console, tmp_path, mock_llm):
        """连续 3 次错误 → 注入警告消息（每次参数不同避免触发 StuckDetector）"""
        agent = _build_minimal_agent(str(tmp_path), mock_llm, max_iterations=10)

        def failing_handler(args):
            return "[错误] 临时错误"

        agent._registry.register_handler("execute_command", failing_handler)

        # 每次使用不同参数，防止 StuckDetector REPEAT_CALL 误触发；
        # ERROR_REPEAT 需要相同 error_message 连续 3 次，但这里 error_message 截取 result[:200]
        # 会相同，所以用不同 command 参数保证 args_hash 不同来规避 REPEAT_CALL，
        # 同时用不同错误内容来规避 ERROR_REPEAT。
        responses = []
        for i in range(10):
            responses.append(_llm_response(
                tool_calls=[_tool_call("execute_command", {"command": f"fail-{i}"}, f"tc-{i}")]
            ))
        mock_llm.chat.side_effect = responses

        import pytest
        from autoc.exceptions import AgentStuckError
        # 不同命令 + 不同错误（handler 返回固定字符串，但 args_hash 不同），
        # REPEAT_CALL 不触发；ERROR_REPEAT 阈值 3 且错误消息完全相同，仍可能触发
        # 在错误消息中加入索引使其不同，绕过 ERROR_REPEAT
        call_idx = {"n": 0}
        def varied_failing_handler(args):
            call_idx["n"] += 1
            return f"[错误] 临时错误 #{call_idx['n']}"
        agent._registry.register_handler("execute_command", varied_failing_handler)

        agent.run("执行任务")
        assert agent._circuit_breaker_warned is True
        warn_msgs = [
            m for m in agent.conversation_history
            if m.get("role") == "user" and "连续" in m.get("content", "")
        ]
        assert len(warn_msgs) >= 1


class TestSAICControl:
    """SAIC 迭代控制"""

    @patch("autoc.agents.base.console")
    def test_saic_degrade_strips_explore_tools(self, mock_console, tmp_path, mock_llm):
        """70%+ 预算纯探索 → 降级时工具列表被剥离（第4轮起无 read_file）"""
        # max_iterations=8 给 SAIC 降级逻辑足够空间，避免 StuckDetector L3 提前干预
        agent = _build_minimal_agent(str(tmp_path), mock_llm, max_iterations=8)
        agent._registry.register_handler("read_file", lambda args: "content")

        call_count = [0]
        def chat_side_effect(**kwargs):
            call_count[0] += 1
            tools = kwargs.get("tools")
            if call_count[0] >= 4 and tools:
                tool_names = [t["function"]["name"] for t in tools]
                assert "read_file" not in tool_names
            # 第 7 轮返回无工具调用的完成消息，终止循环
            if call_count[0] >= 7:
                return _llm_response(content="探索完成")
            return _llm_response(
                tool_calls=[_tool_call("read_file", {"path": f"x{call_count[0]}.py"}, f"tc-{call_count[0]}")]
            )

        mock_llm.chat.side_effect = chat_side_effect
        agent.run("探索项目")

    @patch("autoc.agents.base.console")
    def test_saic_auto_extend_when_producing(self, mock_console, tmp_path, mock_llm):
        """软上限到达 + 最近有写文件 → max_iterations 自动延伸"""
        agent = _build_minimal_agent(str(tmp_path), mock_llm, max_iterations=3)
        agent._registry.register_handler("write_file", lambda args: "文件已写入")
        agent._registry.register_handler("read_file", lambda args: "content")

        mock_llm.chat.side_effect = [
            _llm_response(tool_calls=[_tool_call("write_file", {"path": "a.py", "content": "x"}, "tc-1")]),
            _llm_response(tool_calls=[_tool_call("write_file", {"path": "b.py", "content": "y"}, "tc-2")]),
            _llm_response(tool_calls=[_tool_call("write_file", {"path": "c.py", "content": "z"}, "tc-3")]),
            _llm_response(content="完成"),
        ]

        output = agent.run("写代码")
        # H14 fix: max_iterations 在 run() 结束时恢复原始值；
        # 验证自动延伸真正发生：迭代次数应超过原始上限 3（需要第 4 轮输出"完成"）
        assert agent._iteration_count >= 4

    @patch("autoc.agents.base.console")
    def test_saic_hard_cap_terminates(self, mock_console, tmp_path, mock_llm):
        """达到 initial_max_iterations * 1.5 → 强制终止"""
        agent = _build_minimal_agent(str(tmp_path), mock_llm, max_iterations=4)
        agent._registry.register_handler("write_file", lambda args: "ok")

        responses = []
        for i in range(20):
            responses.append(_llm_response(
                tool_calls=[_tool_call("write_file", {"path": f"f{i}.py", "content": "x"}, f"tc-{i}")]
            ))
        responses.append(_llm_response(content="done"))
        mock_llm.chat.side_effect = responses

        agent.run("写大量文件")
        hard_cap = int(4 * 1.5)
        assert agent._iteration_count <= hard_cap

    @patch("autoc.agents.base.console")
    def test_saic_strip_tools_at_soft_limit(self, mock_console, tmp_path, mock_llm):
        """软上限 + 已停滞 → current_tools = None"""
        agent = _build_minimal_agent(str(tmp_path), mock_llm, max_iterations=3)
        agent._registry.register_handler("read_file", lambda args: "content")

        chat_calls = []
        def chat_side_effect(**kwargs):
            chat_calls.append(kwargs)
            tools = kwargs.get("tools")
            return _llm_response(
                tool_calls=[_tool_call("read_file", {"path": "x.py"}, f"tc-{len(chat_calls)}")]
            )

        mock_llm.chat.side_effect = chat_side_effect
        agent.run("分析项目")

        last_call_tools = chat_calls[-1].get("tools")
        assert last_call_tools is None


class TestContextManagement:
    """上下文管理"""

    @patch("autoc.agents.base.console")
    def test_truncate_prev_tool_results(self, mock_console, tmp_path, mock_llm):
        """超过 _MAX_TOOL_RESULT_CHARS 且超 40 行的工具结果在下一轮被截断"""
        agent = _build_minimal_agent(str(tmp_path), mock_llm)
        max_chars = agent._MAX_TOOL_RESULT_CHARS
        chars_per_line = max(300, max_chars // 60)
        long_content = "\n".join([f"line {i}: {'x' * chars_per_line}" for i in range(80)])
        assert len(long_content) > max_chars, f"测试数据({len(long_content)})必须超过阈值({max_chars})"
        agent._registry.register_handler("read_file", lambda args: long_content)

        mock_llm.chat.side_effect = [
            _llm_response(tool_calls=[_tool_call("read_file", {"path": "big.py"})]),
            _llm_response(tool_calls=[_tool_call("read_file", {"path": "small.py"}, "tc-2")]),
            _llm_response(content="done"),
        ]

        agent.run("读取文件")
        tool_msgs = [m for m in agent.conversation_history if m.get("role") == "tool"]
        first_tool = tool_msgs[0]
        assert len(first_tool["content"]) < len(long_content)
        assert first_tool.get("_truncated") is True

    @patch("autoc.agents.base.console")
    def test_below_threshold_not_truncated(self, mock_console, tmp_path, mock_llm):
        """低于 _MAX_TOOL_RESULT_CHARS 的工具结果不被截断"""
        agent = _build_minimal_agent(str(tmp_path), mock_llm)
        max_chars = agent._MAX_TOOL_RESULT_CHARS
        short_content = "x" * (max_chars - 100)
        agent._registry.register_handler("read_file", lambda args: short_content)

        mock_llm.chat.side_effect = [
            _llm_response(tool_calls=[_tool_call("read_file", {"path": "ok.py"})]),
            _llm_response(tool_calls=[_tool_call("read_file", {"path": "ok2.py"}, "tc-2")]),
            _llm_response(content="done"),
        ]

        agent.run("读取文件")
        tool_msgs = [m for m in agent.conversation_history if m.get("role") == "tool"]
        first_tool = tool_msgs[0]
        assert first_tool["content"] == short_content
        assert first_tool.get("_truncated") is None

    @patch("autoc.agents.base.console")
    def test_few_lines_long_chars_handled(self, mock_console, tmp_path, mock_llm):
        """超字符数但 ≤40 行的内容：_smart_line_truncate 不做行级裁剪，
        但 _truncated 仍标记为 True（内容可能被 hard_limit 截断）。
        """
        agent = _build_minimal_agent(str(tmp_path), mock_llm)
        max_chars = agent._MAX_TOOL_RESULT_CHARS
        line_len = max(1200, max_chars // 20)
        few_long_lines = "\n".join(["x" * line_len] * 30)
        assert len(few_long_lines) > max_chars, f"测试数据({len(few_long_lines)})必须超过阈值({max_chars})"
        assert few_long_lines.count("\n") < 40
        agent._registry.register_handler("read_file", lambda args: few_long_lines)

        mock_llm.chat.side_effect = [
            _llm_response(tool_calls=[_tool_call("read_file", {"path": "wide.py"})]),
            _llm_response(tool_calls=[_tool_call("read_file", {"path": "x.py"}, "tc-2")]),
            _llm_response(content="done"),
        ]

        agent.run("读取文件")
        tool_msgs = [m for m in agent.conversation_history if m.get("role") == "tool"]
        first_tool = tool_msgs[0]
        assert first_tool.get("_truncated") is True

    @patch("autoc.agents.base.console")
    def test_error_results_not_truncated(self, mock_console, tmp_path, mock_llm):
        """[错误] 前缀的工具结果不被截断"""
        agent = _build_minimal_agent(str(tmp_path), mock_llm)
        max_chars = agent._MAX_TOOL_RESULT_CHARS
        long_error = "[错误] " + "x" * (max_chars + 5000)
        agent._registry.register_handler("read_file", lambda args: long_error)

        mock_llm.chat.side_effect = [
            _llm_response(tool_calls=[_tool_call("read_file", {"path": "bad.py"})]),
            _llm_response(content="done"),
        ]

        agent.run("读取文件")
        tool_msgs = [m for m in agent.conversation_history if m.get("role") == "tool"]
        assert tool_msgs[0]["content"] == long_error
        assert tool_msgs[0].get("_truncated") is None

    @patch("autoc.agents.base.console")
    def test_session_startup_context_injected(self, mock_console, tmp_path, mock_llm):
        """_build_session_startup_context 返回非空 → 注入 user+assistant 消息"""
        agent = _build_minimal_agent(str(tmp_path), mock_llm)
        agent.memory.to_context_string.return_value = "## 项目上下文\n技术栈: Python"

        mock_llm.chat.return_value = _llm_response(content="收到")
        agent.run("开始工作")

        has_startup = any(
            "项目当前状态" in m.get("content", "")
            for m in agent.conversation_history
            if m.get("role") == "user"
        )
        assert has_startup
