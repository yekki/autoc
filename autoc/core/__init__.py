"""AutoC Core - 核心模块

模块一览:
- project.models: 纯 Pydantic 数据模型 (Task, ProjectPlan, ProjectMetadata 等)
- project.memory: 共享记忆系统 (含 Task passes 验证)
- orchestrator: 多 Agent 编排器 (薄编排 + 迭代循环)
- llm: LLM 统一客户端 (多模型预设 + 缓存 + 路由)
- analysis: 复杂度评估 / 经验学习 / 失败分析 / 代码索引
- infra: 基础设施 (DB / CircuitBreaker / Presenter / Profile)
- runtime: 运行时 (Docker 沙箱 / Preview / VenvManager)
"""
