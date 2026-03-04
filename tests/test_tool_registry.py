"""ToolRegistry 工具分发路由测试

覆盖: dispatch 优先级（内置 → ToolError）、注册/注销生命周期。
"""

import pytest
from unittest.mock import MagicMock

from autoc.tools.registry import ToolRegistry
from autoc.exceptions import ToolError


class TestDispatch:
    """dispatch() 路由优先级"""

    def test_dispatch_builtin_handler(self):
        reg = ToolRegistry()
        reg.register_handler("read_file", lambda args: f"content of {args['path']}")
        result = reg.dispatch("read_file", {"path": "main.py"})
        assert result == "content of main.py"

    def test_dispatch_unknown_raises_tool_error(self):
        reg = ToolRegistry()
        with pytest.raises(ToolError, match="未知工具: xyz"):
            reg.dispatch("xyz", {})


class TestLifecycle:
    """注册/注销生命周期"""

    def test_register_unregister_lifecycle(self):
        reg = ToolRegistry()
        reg.register_handler("my_tool", lambda args: "ok", "test", "测试工具")
        assert reg.has("my_tool")
        assert "my_tool" in reg.list_names()

        reg.unregister("my_tool")
        assert not reg.has("my_tool")
        assert "my_tool" not in reg.list_names()
