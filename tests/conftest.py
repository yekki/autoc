"""AutoC 测试基础设施

参考 Ralph 的 566 tests / 100% 通过率目标，
逐步建立 AutoC 自身的测试覆盖。
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def tmp_workspace(tmp_path):
    """创建临时工作区目录"""
    ws = tmp_path / "workspace"
    ws.mkdir()
    return str(ws)


@pytest.fixture
def sample_tasks():
    """示例任务数据"""
    return [
        {
            "id": "task-1", "title": "初始化项目",
            "description": "创建项目基础结构",
            "priority": 0, "verification_steps": ["目录存在"],
            "feature_tag": "core", "passes": False,
        },
        {
            "id": "task-2", "title": "实现核心功能",
            "description": "实现主要业务逻辑",
            "priority": 1, "verification_steps": ["功能可用"],
            "feature_tag": "core", "passes": False,
        },
    ]


# ==================== Agent 核心链路测试 fixtures ====================


@pytest.fixture
def mock_llm():
    """Mock LLMClient，支持 side_effect 多次调用"""
    llm = MagicMock()
    llm.total_tokens = 0
    llm.prompt_tokens = 0
    llm.cache_stats = {"hits": 0, "misses": 0}
    return llm


def _build_minimal_agent(tmp_workspace, mock_llm, max_iterations=5):
    """构造最小化 BaseAgent 子类实例"""
    from autoc.agents.base import BaseAgent

    mock_memory = MagicMock()
    mock_memory.project_plan = None
    mock_memory.tasks = {}
    mock_memory.requirement = ""
    mock_memory.to_context_string.return_value = ""

    mock_file_ops = MagicMock()
    mock_file_ops.workspace_dir = tmp_workspace

    mock_shell = MagicMock()

    class MinimalAgent(BaseAgent):
        agent_role = "test"

        def get_system_prompt(self) -> str:
            return "你是测试 Agent。"

        def get_tools(self) -> list[dict]:
            return [
                {"type": "function", "function": {
                    "name": "read_file",
                    "description": "读取文件",
                    "parameters": {"type": "object", "properties": {
                        "path": {"type": "string"}
                    }, "required": ["path"]},
                }},
                {"type": "function", "function": {
                    "name": "write_file",
                    "description": "写入文件",
                    "parameters": {"type": "object", "properties": {
                        "path": {"type": "string"}, "content": {"type": "string"}
                    }, "required": ["path", "content"]},
                }},
            ]

    agent = MinimalAgent(
        name="TestAgent",
        role_description="测试用 Agent",
        llm_client=mock_llm,
        memory=mock_memory,
        file_ops=mock_file_ops,
        shell=mock_shell,
        max_iterations=max_iterations,
        color="cyan",
    )
    return agent


@pytest.fixture
def minimal_agent(tmp_workspace, mock_llm):
    """最小化 BaseAgent 子类实例（5 轮迭代）"""
    return _build_minimal_agent(tmp_workspace, mock_llm, max_iterations=5)
