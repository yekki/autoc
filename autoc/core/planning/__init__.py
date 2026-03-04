"""Planning 模块 — 纯函数式规划，不依赖 Agent 基类

提供结构化项目计划生成能力（由调用方决定使用哪个 LLM）：
- generate_plan(): 新项目完整规划
- generate_simple_plan(): 简单需求快速规划
- generate_incremental_plan(): 已有项目增量规划
- generate_next_batch(): 批次增量规划
- parse_plan() / validate_plan(): 计划解析与质量验证
"""

from autoc.core.planning.generator import (
    generate_plan,
    generate_simple_plan,
    generate_incremental_plan,
    generate_next_batch,
)
from autoc.core.planning.validator import (
    parse_plan,
    validate_plan,
    auto_complete_verification,
    topo_sort_tasks,
)

__all__ = [
    "generate_plan",
    "generate_simple_plan",
    "generate_incremental_plan",
    "generate_next_batch",
    "parse_plan",
    "validate_plan",
    "auto_complete_verification",
    "topo_sort_tasks",
]
