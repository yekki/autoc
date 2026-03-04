"""Token 优化行为测试

覆盖: Benchmark 瓶颈分析报告中优化的行为正确性。
- P0-2: schemas.BugReport 字段删减
- P1-1: SlidingWindowCondenser 新阈值
- P1-3: PlanningAgent 空目录快速路径判断
- P2-1: _get_iteration_tools 延迟注入
"""

from unittest.mock import MagicMock, patch

import pytest


# ==================== P0-2: schemas.BugReport 字段删减 ====================


class TestBugReportSchemaFields:
    """验证 schemas.BugReport 保留了 fix prompt 需要的字段，删除了冗余字段"""

    def test_has_root_cause_and_suggested_fix(self):
        from autoc.tools.schemas import BugReport
        fields = set(BugReport.model_fields.keys())
        assert "root_cause" in fields, "root_cause 被 _build_fix_prompt 使用，不能删"
        assert "suggested_fix" in fields, "suggested_fix 被 fix prompt 和 SharedMemory 使用，不能删"

    def test_no_fix_strategy_and_affected_functions(self):
        from autoc.tools.schemas import BugReport
        fields = set(BugReport.model_fields.keys())
        assert "fix_strategy" not in fields, "fix_strategy 未出现在 fix prompt 中，应删除以省 token"
        assert "affected_functions" not in fields, "affected_functions 未出现在 fix prompt 中，应删除以省 token"

    def test_schema_token_reduction(self):
        """精简后的 schema JSON 不含已删字段，保留必要字段"""
        from autoc.tools.schemas import BugReport, tool_schema
        import json
        schema = tool_schema("test_report", "test", BugReport)
        schema_str = json.dumps(schema)
        assert "fix_strategy" not in schema_str
        assert "affected_functions" not in schema_str
        assert "root_cause" in schema_str


# ==================== P1-1: SlidingWindowCondenser 阈值 ====================


class TestCondenserThresholds:
    """SlidingWindowCondenser 新默认阈值(12,10)的行为"""

    def test_default_thresholds(self):
        from autoc.core.llm.condenser import SlidingWindowCondenser
        c = SlidingWindowCondenser()
        assert c._trigger == 12
        assert c._window_size == 10

    def test_no_compress_under_threshold(self):
        from autoc.core.llm.condenser import SlidingWindowCondenser
        c = SlidingWindowCondenser()
        msgs = [{"role": "system", "content": "sys"}] + [
            {"role": "user", "content": f"msg{i}"} for i in range(11)
        ]
        result = c.condense(msgs, "test", 1)
        assert len(result) == 12  # 12 <= 12, 不压缩

    def test_compress_over_threshold(self):
        from autoc.core.llm.condenser import SlidingWindowCondenser
        c = SlidingWindowCondenser()
        msgs = [{"role": "system", "content": "sys"}]
        for i in range(14):
            msgs.append({"role": "user", "content": f"question {i}"})
            msgs.append({"role": "assistant", "content": f"answer {i}"})
        # 29 条消息 > 12，应触发压缩
        result = c.condense(msgs, "test", 5)
        assert len(result) < len(msgs)
        # 压缩后保留窗口大小附近的消息
        assert len(result) <= 10 + 3  # window + system + summary + ack


# ==================== P1-3: 空目录快速路径 ====================


class TestSingleShotPlanTrigger:
    """PlanningAgent._single_shot_plan 触发条件"""

    def test_empty_workspace_info_triggers_fast_path(self):
        """workspace_info="" 时应尝试快速路径"""
        from autoc.agents.planner import PlanningAgent

        with patch.object(PlanningAgent, '_single_shot_plan', return_value="# Fast Plan") as mock_fast:
            with patch.object(PlanningAgent, '__init__', return_value=None):
                agent = object.__new__(PlanningAgent)
                agent.conversation_history = []
                agent._submitted_plan = None
                result = agent.execute_plan("make a todo app", workspace_info="")
                mock_fast.assert_called_once_with("make a todo app")
                assert result == "# Fast Plan"

    def test_non_empty_workspace_info_skips_fast_path(self):
        """workspace_info 非空时不走快速路径"""
        from autoc.agents.planner import PlanningAgent

        with patch.object(PlanningAgent, '_single_shot_plan') as mock_fast:
            with patch.object(PlanningAgent, 'run', return_value="output"):
                with patch.object(PlanningAgent, '__init__', return_value=None):
                    agent = object.__new__(PlanningAgent)
                    agent.conversation_history = []
                    agent._submitted_plan = "# Full Plan"
                    agent.execute_plan("make a todo app", workspace_info="工作区已有文件:\n  - main.py")
                    mock_fast.assert_not_called()


# ==================== P2-1: _get_iteration_tools 延迟注入 ====================


class TestDelayedToolInjection:
    """CodeActAgent._get_iteration_tools 延迟注入 submit_test_report"""

    def _make_tools(self):
        return [
            {"type": "function", "function": {"name": "read_file"}},
            {"type": "function", "function": {"name": "write_file"}},
            {"type": "function", "function": {"name": "submit_test_report"}},
        ]

    def _make_agent_stub(self, initial_max=15):
        from autoc.agents.code_act_agent import CodeActAgent
        agent = object.__new__(CodeActAgent)
        agent._initial_max_iterations = initial_max
        agent.max_iterations = initial_max
        agent._submitted_report = None
        # 使用类级别定义的比率（0.35）
        return agent

    def test_early_iteration_hides_submit_report(self):
        """iteration < earliest_iter 时不含 submit_test_report"""
        agent = self._make_agent_stub(initial_max=15)
        # ratio=0.35, earliest_iter = max(1, int(15*0.65)) = max(1, 9) = 9
        # iteration=5 < 9 → 不含
        tools = agent._get_iteration_tools(5, self._make_tools())
        names = [t["function"]["name"] for t in tools]
        assert "submit_test_report" not in names
        assert "read_file" in names

    def test_late_iteration_shows_submit_report(self):
        """iteration >= earliest_iter 时含 submit_test_report"""
        agent = self._make_agent_stub(initial_max=15)
        # ratio=0.35, earliest_iter = 9, iteration=9 >= 9 → 含
        tools = agent._get_iteration_tools(9, self._make_tools())
        names = [t["function"]["name"] for t in tools]
        assert "submit_test_report" in names

    def test_monotonic_once_visible_stays_visible(self):
        """一旦 submit_test_report 出现，后续轮次不会消失"""
        agent = self._make_agent_stub(initial_max=15)
        appeared = False
        for i in range(1, 25):
            tools = agent._get_iteration_tools(i, self._make_tools())
            names = {t["function"]["name"] for t in tools}
            if "submit_test_report" in names:
                appeared = True
            if appeared:
                assert "submit_test_report" in names, f"消失于 iteration {i}"

    def test_saic_extend_does_not_affect_threshold(self):
        """SAIC 动态延伸 max_iterations 不影响注入阈值（基于 _initial_max_iterations）"""
        agent = self._make_agent_stub(initial_max=15)
        # 模拟 SAIC 延伸
        agent.max_iterations = 20
        # earliest_iter 仍基于 _initial_max_iterations=15 → max(1, int(15*0.65))=9
        tools_iter8 = agent._get_iteration_tools(8, self._make_tools())
        tools_iter9 = agent._get_iteration_tools(9, self._make_tools())
        assert "submit_test_report" not in [t["function"]["name"] for t in tools_iter8]
        assert "submit_test_report" in [t["function"]["name"] for t in tools_iter9]

    def test_short_task_max5_injects_at_iter3(self):
        """max_iterations=5 时 earliest_iter=max(1, int(5*0.65))=3, 第 3 轮注入"""
        agent = self._make_agent_stub(initial_max=5)
        # iter 2 不含
        tools_2 = agent._get_iteration_tools(2, self._make_tools())
        assert "submit_test_report" not in [t["function"]["name"] for t in tools_2]
        # iter 3 含
        tools_3 = agent._get_iteration_tools(3, self._make_tools())
        assert "submit_test_report" in [t["function"]["name"] for t in tools_3]


# ==================== Shell 命令感知输出压缩 ====================


class TestShellCompression:
    """_compress_shell_output / _compress_pip_output 行为验证"""

    def _compress(self, output, command=""):
        from autoc.tools.shell import _compress_shell_output
        return _compress_shell_output(output, command=command)

    def _compress_pip(self, output):
        from autoc.tools.shell import _compress_pip_output
        return _compress_pip_output(output)

    # --- py_compile ---

    def test_py_compile_success_returns_checkmark(self):
        """py_compile 无输出时返回 '✓ 编译通过'"""
        result = self._compress("", command="python -m py_compile app.py")
        assert result == "✓ 编译通过"

    def test_py_compile_success_whitespace_only(self):
        """py_compile 仅空白符时也返回 '✓ 编译通过'"""
        result = self._compress("  \n  ", command="python -m py_compile app.py")
        assert result == "✓ 编译通过"

    def test_py_compile_error_preserved_intact(self):
        """py_compile 失败时完整保留错误（不截断）"""
        err = "  File \"app.py\", line 5\n    def foo(\n          ^\nSyntaxError: invalid syntax"
        result = self._compress(err, command="python3 -m py_compile app.py")
        assert "SyntaxError" in result
        assert result.strip() == err.strip()

    def test_py_compile_command_variant_python3(self):
        """python3 -m py_compile 也被识别"""
        result = self._compress("", command="python3 -m py_compile models.py")
        assert result == "✓ 编译通过"

    # --- pip install ---

    def test_pip_success_returns_single_line(self):
        """pip install 成功：只返回 Successfully installed 行"""
        output = (
            "Collecting flask\n"
            "  Downloading Flask-3.0.0-py3-none-any.whl\n"
            "Installing collected packages: flask\n"
            "Successfully installed flask-3.0.0\n"
        )
        result = self._compress(output, command="pip install flask")
        assert result == "Successfully installed flask-3.0.0"

    def test_pip_all_satisfied_returns_summary(self):
        """pip install 全部已满足：返回统计摘要行而非 N 行原文"""
        output = (
            "Requirement already satisfied: flask in /usr/lib/python3\n"
            "Requirement already satisfied: jinja2 in /usr/lib/python3\n"
            "Requirement already satisfied: werkzeug in /usr/lib/python3\n"
        )
        result = self._compress_pip(output)
        assert "3 个包" in result
        assert "Requirement already satisfied" not in result  # 不能原样透传

    def test_pip_failure_keeps_last_5_lines(self):
        """pip install 失败：保留最后 5 行错误信息"""
        lines = [f"line{i}" for i in range(20)]
        lines.append("ERROR: Could not find a version that satisfies the requirement badpkg")
        output = "\n".join(lines)
        result = self._compress_pip(output)
        assert "ERROR" in result
        assert len(result.splitlines()) <= 5

    def test_pip_command_not_matched_uses_generic(self):
        """非 pip/py_compile 命令走通用压缩路径（短输出直接返回）"""
        short_output = "Hello World"
        result = self._compress(short_output, command="python -c 'print(\"Hello World\")'")
        assert result == short_output

    def test_generic_long_output_truncated(self):
        """超出字符限制的通用输出应被截断"""
        long_output = "x" * 20000
        result = self._compress(long_output, command="cat bigfile.txt")
        assert len(result) < 20000
        assert "截断" in result or "省略" in result


# ==================== _get_submit_hint 兜底提示行为 ====================


class TestSubmitHint:
    """_get_submit_hint 的一次性注入 + SAIC 延伸后的窗口判断"""

    def _make_agent(self, initial_max=20, current_max=None):
        from autoc.agents.code_act_agent import CodeActAgent
        agent = object.__new__(CodeActAgent)
        agent._initial_max_iterations = initial_max
        agent.max_iterations = current_max if current_max is not None else initial_max
        agent._submitted_report = None
        agent._submit_hint_injected = False
        return agent

    def test_before_window_no_hint(self):
        """未进入最后 3 轮窗口时不注入"""
        agent = self._make_agent(initial_max=20)
        assert agent._get_submit_hint(16) == ""

    def test_at_window_start_injects_hint(self):
        """第 17 轮（max=20）进入窗口，返回提示文本"""
        agent = self._make_agent(initial_max=20)
        hint = agent._get_submit_hint(17)
        assert "submit_test_report" in hint
        assert hint != ""

    def test_hint_injected_only_once(self):
        """多次调用只注入一次，后续返回空字符串"""
        agent = self._make_agent(initial_max=20)
        first = agent._get_submit_hint(17)
        second = agent._get_submit_hint(18)
        third = agent._get_submit_hint(19)
        assert first != ""
        assert second == ""
        assert third == ""

    def test_no_hint_after_report_submitted(self):
        """已提交报告后不注入（_submitted_report 已设置）"""
        agent = self._make_agent(initial_max=20)
        agent._submitted_report = {"status": "ok"}
        hint = agent._get_submit_hint(18)
        assert hint == ""

    def test_saic_extension_uses_dynamic_max(self):
        """SAIC 将 max_iterations 延伸至 28 时，窗口应从第 25 轮开始（而非第 17 轮）"""
        agent = self._make_agent(initial_max=20, current_max=28)
        # 第 17 轮（原 initial_max 的最后 3 轮）不应触发
        assert agent._get_submit_hint(17) == ""
        # 第 25 轮（动态 max=28 的最后 3 轮）应触发
        hint = agent._get_submit_hint(25)
        assert "submit_test_report" in hint


# ==================== Condenser 错误提取 ====================


class TestCondenserErrorExtraction:
    """_build_structural_summary 中 Traceback 异常行提取正确性"""

    def _extract_error(self, tool_name: str, tool_output: str) -> str:
        """构造最小 msgs 序列并运行 _build_structural_summary，返回摘要中的错误文本"""
        import json as json_mod
        from autoc.core.llm.condenser import _build_structural_summary

        tc_id = "tc-1"
        msgs = [
            {
                "role": "assistant",
                "tool_calls": [{
                    "id": tc_id,
                    "function": {
                        "name": tool_name,
                        "arguments": json_mod.dumps({"command": "python app.py"}),
                    },
                }],
            },
            {
                "role": "tool",
                "tool_call_id": tc_id,
                "content": tool_output,
            },
        ]
        summary = _build_structural_summary("", msgs, "TestAgent", 1)
        return summary

    def test_extracts_standard_exception_line(self):
        """标准 Traceback 末行 ImportError 被正确提取"""
        tb = (
            "Traceback (most recent call last):\n"
            "  File \"app.py\", line 3, in <module>\n"
            "    import nonexistent\n"
            "ImportError: No module named 'nonexistent'\n"
        )
        summary = self._extract_error("execute_command", tb)
        assert "ImportError" in summary
        assert "No module named" in summary

    def test_extracts_value_error(self):
        """ValueError 被提取"""
        tb = (
            "Traceback (most recent call last):\n"
            "  File \"app.py\", line 10\n"
            "ValueError: invalid literal for int() with base 10: 'abc'\n"
        )
        summary = self._extract_error("execute_command", tb)
        assert "ValueError" in summary

    def test_extracts_third_party_exception(self):
        """第三方带点号全限定异常类名被正则直接提取（不依赖 fallback）"""
        tb = (
            "Traceback (most recent call last):\n"
            "  File \"app.py\", line 5\n"
            "    db.connect()\n"
            "sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) no such table\n"
        )
        summary = self._extract_error("execute_command", tb)
        # 正则 [\w.]+ 现在能匹配 sqlalchemy.exc.OperationalError，应精确提取该行
        assert "sqlalchemy.exc.OperationalError" in summary
        assert "no such table" in summary

    def test_extracts_requests_exception(self):
        """requests 库的带点号异常也能被提取"""
        tb = (
            "Traceback (most recent call last):\n"
            "  File \"client.py\", line 8\n"
            "    r = requests.get(url)\n"
            "requests.exceptions.ConnectionError: HTTPSConnectionPool: Max retries exceeded\n"
        )
        summary = self._extract_error("execute_command", tb)
        assert "requests.exceptions.ConnectionError" in summary

    def test_syntax_error_preserved(self):
        """SyntaxError 被提取"""
        tb = (
            "  File \"app.py\", line 12\n"
            "    def foo(:\n"
            "           ^\n"
            "SyntaxError: invalid syntax\n"
        )
        summary = self._extract_error("execute_command", tb)
        assert "SyntaxError" in summary

    def test_no_traceback_uses_content_fallback(self):
        """无 Traceback 的纯错误输出 fallback 到 content[:200]"""
        plain_err = "[错误] Connection refused on port 5000"
        summary = self._extract_error("execute_command", plain_err)
        assert "Connection refused" in summary

    def test_write_file_records_size(self):
        """write_file 摘要包含文件大小"""
        import json as json_mod
        from autoc.core.llm.condenser import _build_structural_summary

        tc_id = "tc-2"
        content_str = "x" * 500
        msgs = [
            {
                "role": "assistant",
                "tool_calls": [{
                    "id": tc_id,
                    "function": {
                        "name": "write_file",
                        "arguments": json_mod.dumps({"path": "app.py", "content": content_str}),
                    },
                }],
            },
            {
                "role": "tool",
                "tool_call_id": tc_id,
                "content": "文件已写入: app.py (500 bytes)",
            },
        ]
        summary = _build_structural_summary("", msgs, "TestAgent", 1)
        assert "500B" in summary
        assert "app.py" in summary

    def test_edit_file_recorded_in_summary(self):
        """edit_file 操作出现在摘要的文件字段中（而非被忽略）"""
        import json as json_mod
        from autoc.core.llm.condenser import _build_structural_summary

        tc_id = "tc-3"
        msgs = [
            {
                "role": "assistant",
                "tool_calls": [{
                    "id": tc_id,
                    "function": {
                        "name": "edit_file",
                        "arguments": json_mod.dumps({
                            "path": "app.py",
                            "old_str": "def foo():",
                            "new_str": "def foo(x: int):",
                        }),
                    },
                }],
            },
            {
                "role": "tool",
                "tool_call_id": tc_id,
                "content": "文件已编辑: app.py",
            },
        ]
        summary = _build_structural_summary("", msgs, "TestAgent", 1)
        # edit_file 应出现在 "文件:" 字段
        assert "app.py" in summary
        assert "[edit," in summary  # 带 edit 标记，区别于 write_file

    def test_edit_file_not_confused_with_write_file(self):
        """同一次 run 中 write_file 和 edit_file 均被记录，且可区分"""
        import json as json_mod
        from autoc.core.llm.condenser import _build_structural_summary

        msgs = [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "tc-w",
                        "function": {
                            "name": "write_file",
                            "arguments": json_mod.dumps({"path": "models.py", "content": "x" * 300}),
                        },
                    },
                    {
                        "id": "tc-e",
                        "function": {
                            "name": "edit_file",
                            "arguments": json_mod.dumps({
                                "path": "app.py", "old_str": "old", "new_str": "new code here",
                            }),
                        },
                    },
                ],
            },
            {"role": "tool", "tool_call_id": "tc-w", "content": "文件已写入: models.py"},
            {"role": "tool", "tool_call_id": "tc-e", "content": "文件已编辑: app.py"},
        ]
        summary = _build_structural_summary("", msgs, "TestAgent", 2)
        assert "models.py" in summary
        assert "app.py" in summary
        assert "[edit," in summary   # edit_file 有 edit 标记
        assert "300B" in summary     # write_file 有大小


class TestPipWarningFiltering:
    """_compress_pip_output 对 WARNING / NOTICE 干扰行的处理"""

    def _compress_pip(self, output):
        from autoc.tools.shell import _compress_pip_output
        return _compress_pip_output(output)

    def test_warning_mixed_with_satisfied_not_treated_as_partial(self):
        """WARNING 行混入 already-satisfied 时不被误计为部分满足"""
        output = (
            "Requirement already satisfied: flask in /usr/lib/python3\n"
            "Requirement already satisfied: jinja2 in /usr/lib/python3\n"
            "WARNING: Running pip as the 'root' user can result in broken permissions\n"
        )
        result = self._compress_pip(output)
        # 过滤掉 WARNING 后，实际是 2 个包都满足
        assert "满足" in result
        assert "WARNING" not in result

    def test_notice_line_filtered_out(self):
        """NOTICE 行被过滤，不影响满足判断"""
        output = (
            "Requirement already satisfied: requests\n"
            "NOTICE: New pip version available\n"
        )
        result = self._compress_pip(output)
        assert "NOTICE" not in result

    def test_downloading_lines_filtered(self):
        """Downloading / Using cached 辅助行被过滤"""
        output = (
            "Collecting flask\n"
            "  Downloading Flask-3.0.0-py3-none-any.whl (92 kB)\n"
            "  Using cached Flask-3.0.0-py3-none-any.whl\n"
            "Successfully installed flask-3.0.0\n"
        )
        result = self._compress_pip(output)
        assert result == "Successfully installed flask-3.0.0"

    def test_pure_failure_output_preserved(self):
        """纯错误输出（无满足行）保留最后 5 个内容行"""
        output = "\n".join([
            "ERROR: Could not find a version that satisfies the requirement badlib==9.9.9",
            "ERROR: No matching distribution found for badlib==9.9.9",
        ])
        result = self._compress_pip(output)
        assert "ERROR" in result
        assert "badlib" in result
