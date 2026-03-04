"""计划生成模块 — 纯函数式，不依赖 Agent 基类

将需求转化为结构化 ProjectPlan（由调用方决定使用哪个 LLM）:
- generate_plan(): 新项目完整规划（直接 LLM 调用）
- generate_simple_plan(): 简单需求快速规划（单任务）
- generate_incremental_plan(): 已有项目增量规划（直接 LLM 调用 + 文件上下文）
- generate_next_batch(): 批次增量规划
"""

import json
import logging
import os
import re
from typing import Callable

from autoc.core.project.memory import ProjectPlan, SharedMemory

from .validator import parse_plan, validate_plan, TASK_LIMITS

logger = logging.getLogger("autoc.planning")

_MARKDOWN_FENCE = re.compile(r"^```\w*\n?|```\s*$", re.MULTILINE)
_CLASS_DEF = re.compile(r"class\s+\w+")
_ROUTE_DEF = re.compile(r"(GET|POST|PUT|DELETE|PATCH)\s+/", re.IGNORECASE)
_DB_KEYWORDS = re.compile(
    r"(sql|sqlite|postgres|mysql|mongo|database|数据库|db\.Model|ORM|model|模型)",
    re.IGNORECASE,
)
_API_KEYWORDS = re.compile(
    r"(api|rest|endpoint|路由|接口|flask|fastapi|express|django)",
    re.IGNORECASE,
)

_AUTOC_INTERNAL = {
    ".autoc.db", ".autoc.db-shm", ".autoc.db-wal",
    "autoc-progress.txt", "autoc-tasks.json", "project-plan.json",
}


def _get_system_prompt() -> str:
    try:
        from autoc.prompts import PromptEngine
        engine = PromptEngine()
        if engine.has_template("planner"):
            return engine.render("planner")
    except Exception:
        pass
    return (
        "你是规划者。输出纯 JSON 项目计划，不要解释。"
        "每个 task 必须有 description、files、verification_steps。"
    )


def _emit(on_event: Callable | None, event_type: str, **data):
    if on_event:
        on_event({"type": event_type, "agent": "planner", "data": data})


def _list_workspace_files(file_ops) -> str:
    try:
        raw = file_ops.list_files(".", recursive=True)
    except Exception:
        raw = ""
    return "\n".join(
        line for line in raw.splitlines()
        if os.path.basename(line.strip()) not in _AUTOC_INTERNAL
    ) or "（空目录）"


def _strip_fence(text: str) -> str:
    return _MARKDOWN_FENCE.sub("", text).strip()


def _needs_database(plan: ProjectPlan) -> bool:
    text = " ".join([plan.description] + plan.tech_stack +
                    [t.description for t in plan.tasks])
    return bool(_DB_KEYWORDS.search(text))


def _needs_api(plan: ProjectPlan) -> bool:
    text = " ".join([plan.description] + plan.tech_stack +
                    [t.description for t in plan.tasks])
    return bool(_API_KEYWORDS.search(text))


def _summarize_tasks(plan: ProjectPlan) -> str:
    return "\n".join(
        f"- [{t.id}] {t.title}: {t.description[:120]}" for t in plan.tasks
    )


def _supplement_data_models(llm, plan: ProjectPlan, requirement: str) -> str:
    tech = ", ".join(plan.tech_stack)
    tasks_summary = _summarize_tasks(plan)
    for attempt in range(1, 4):
        resp = llm.chat(
            messages=[
                {"role": "system", "content": "你是数据库建模专家。只输出代码，不要 JSON 包装。"},
                {"role": "user", "content": (
                    f"根据以下项目需求和任务列表，输出所有数据模型定义。\n\n"
                    f"需求: {requirement[:300]}\n技术栈: {tech}\n任务:\n{tasks_summary}\n\n"
                    f"请输出完整的 Python ORM class 定义或 CREATE TABLE 语句。只输出代码。"
                )},
            ],
            temperature=0.1,
        )
        raw = _strip_fence(resp.get("content", ""))
        if _CLASS_DEF.search(raw) or "CREATE TABLE" in raw.upper():
            return raw[:2000]
        logger.warning(f"data_models 不合格 (第{attempt}次)")
    return ""


def _supplement_api_design(llm, plan: ProjectPlan, requirement: str) -> str:
    tech = ", ".join(plan.tech_stack)
    tasks_summary = _summarize_tasks(plan)
    for attempt in range(1, 4):
        resp = llm.chat(
            messages=[
                {"role": "system", "content": "你是 API 设计专家。只输出 API 契约列表。"},
                {"role": "user", "content": (
                    f"根据以下项目需求，输出所有 API 端点契约。\n\n"
                    f"需求: {requirement[:300]}\n技术栈: {tech}\n任务:\n{tasks_summary}\n\n"
                    f"每行格式: METHOD /path: 请求体 → 成功响应 | 错误响应\n只输出 API 列表。"
                )},
            ],
            temperature=0.1,
        )
        raw = _strip_fence(resp.get("content", ""))
        if _ROUTE_DEF.search(raw):
            return raw[:2000]
        logger.warning(f"api_design 不合格 (第{attempt}次)")
    return ""


def _retry_plan(
    llm, requirement: str, issues: list[str],
    complexity: str, user_tech_stack: list[str] | None = None,
) -> ProjectPlan | None:
    """计划验证失败后重试"""
    task_min, task_max = TASK_LIMITS.get(complexity, (3, 8))
    _files_limit = {"simple": 6, "medium": 8, "complex": 10}
    max_files = _files_limit.get(complexity, 6)
    issues_text = "\n".join(f"- {i}" for i in issues)
    tech_constraint = ""
    if user_tech_stack:
        tech_constraint = f"**技术栈硬约束**: {', '.join(user_tech_stack)}。"
    resp = llm.chat(
        messages=[
            {"role": "system", "content": (
                "你是规划者。输出纯 JSON 项目计划，不要解释。"
                f"需求复杂度: {complexity}，"
                f"任务数量: {task_min}-{task_max} 个，"
                f"每个任务文件数不超过 {max_files} 个。"
                + tech_constraint +
                "**垂直切片**: 每个任务端到端可验证。"
                "**verification_steps 必须是 shell 命令**。"
            )},
            {"role": "user", "content": (
                f"用户需求: {requirement}\n\n"
                f"上次问题:\n{issues_text}\n\n"
                f"重新生成（{task_min}-{task_max} 个任务）。输出纯 JSON。"
            )},
        ],
        temperature=0.1,
    )
    output = resp.get("content", "")
    return parse_plan(output, requirement_text=requirement)


# ===================== 主入口函数 =====================

def generate_plan(
    llm,
    requirement: str,
    file_ops=None,
    memory: SharedMemory | None = None,
    complexity: str = "medium",
    experience_context: str = "",
    refiner_hints: dict | None = None,
    user_tech_stack: list[str] | None = None,
    on_event: Callable | None = None,
) -> ProjectPlan:
    """新项目完整规划 — 直接 LLM 调用生成结构化计划"""
    user_tech_stack = user_tech_stack or []
    _emit(on_event, "planning_progress", step="prepare", progress=5,
          message="正在准备需求上下文...")

    parts = [f"请分析以下需求并生成详细的项目计划:\n\n## 用户需求\n{requirement}"]

    if experience_context:
        parts.append(experience_context)

    if refiner_hints and refiner_hints.get("too_broad"):
        splits = refiner_hints.get("suggested_split", [])
        hint_lines = [
            "## ⚠️ 需求评估预警",
            "此需求范围偏大，请注意任务拆分粒度：",
            "- 每个任务涉及的文件数不超过 5 个",
            f"- 建议至少拆分为 {max(6, len(splits) + 2)} 个任务",
        ]
        if splits:
            hint_lines.append("建议的功能模块拆分：")
            for i, s in enumerate(splits[:5], 1):
                hint_lines.append(f"  {i}. {s}")
        parts.append("\n".join(hint_lines))

    if file_ops:
        existing_files = _list_workspace_files(file_ops)
        parts.append(
            f"## 工作区信息\n- 工作目录: {file_ops.workspace_dir}\n- 现有文件:\n{existing_files}"
        )

    if memory and memory.tasks:
        task_ctx_lines = ["## 已有任务"]
        for t in memory.tasks.values():
            status = "PASS" if t.passes else t.status.value
            files = ", ".join(t.files[:3]) if t.files else "无"
            task_ctx_lines.append(f"- [{t.id}] {t.title} ({status}) — 文件: {files}")
        parts.append("\n".join(task_ctx_lines))

    if user_tech_stack:
        stack_str = ", ".join(user_tech_stack)
        parts.append(
            f"## ⚠️ 技术栈硬约束\n"
            f"用户指定技术栈: **{stack_str}**\n"
            f"严格使用这些技术，禁止替换核心框架。"
        )
    else:
        parts.append(
            "## 技术栈\n"
            "用户未指定技术栈，请根据需求选择成熟稳定的技术。\n"
            "**沙箱约束**: Docker (python3.12 + nodejs22 全栈镜像)，Python / Node.js 项目均可直接运行。"
        )

    task_min, task_max = TASK_LIMITS.get(complexity, (3, 8))
    parts.append(
        f"## 任务数量约束\n"
        f"复杂度 **{complexity}**，任务数 **{task_min}-{task_max} 个**。\n"
        "输出纯 JSON 项目计划。"
    )

    _emit(on_event, "planning_progress", step="llm_call", progress=10,
          message="正在调用 LLM 生成开发计划...")
    task_prompt = "\n\n".join(parts)
    resp = llm.chat(
        messages=[
            {"role": "system", "content": _get_system_prompt()},
            {"role": "user", "content": task_prompt},
        ],
        temperature=0.1,
    )
    output = resp.get("content", "")
    logger.info(f"Planning LLM 响应长度: {len(output)}")

    _emit(on_event, "planning_progress", step="parse", progress=40,
          message="正在解析任务列表...")
    existing_ids = set(memory.tasks.keys()) if memory else set()
    plan = parse_plan(output, requirement_text=requirement, existing_task_ids=existing_ids)

    _emit(on_event, "planning_progress", step="validate", progress=50,
          message="正在验证计划质量...")
    issues = validate_plan(plan, complexity=complexity)
    if issues:
        logger.warning(f"计划质量问题: {issues}")
        _emit(on_event, "planning_progress", step="retry", progress=55,
              message="计划质量不达标，正在重试...")
        plan = _retry_plan(llm, requirement, issues, complexity, user_tech_stack)
        retry_issues = validate_plan(plan, complexity=complexity)
        if retry_issues:
            raise ValueError(f"无法生成有效计划: {'; '.join(retry_issues)}")

    # 补充 data_models
    if not plan.data_models and _needs_database(plan):
        _emit(on_event, "planning_progress", step="data_models", progress=65,
              message="正在生成数据模型规约...")
        plan.data_models = _supplement_data_models(llm, plan, requirement)

    # 补充 api_design
    if not plan.api_design and _needs_api(plan):
        _emit(on_event, "planning_progress", step="api_design", progress=80,
              message="正在生成 API 契约...")
        plan.api_design = _supplement_api_design(llm, plan, requirement)

    # 保存到 memory
    if memory:
        memory.set_project_plan(plan)
        memory.send_message(
            from_agent="Planner", to_agent="all",
            content=f"项目计划已完成: {plan.project_name}, 任务: {len(plan.tasks)} 个",
            msg_type="plan_ready",
        )

    _emit(on_event, "planning_progress", step="complete", progress=100,
          message=f"需求分析完成，共 {len(plan.tasks)} 个任务")
    return plan


def generate_simple_plan(
    llm,
    requirement: str,
    memory: SharedMemory | None = None,
    on_event: Callable | None = None,
) -> ProjectPlan:
    """简单需求快速规划 — 强制单任务"""
    _emit(on_event, "planning_progress", step="llm_call", progress=15,
          message="[轻量模式] 正在快速生成计划...")

    resp = llm.chat(
        messages=[
            {"role": "system", "content": "你是规划者。直接输出 JSON，不要解释。"},
            {"role": "user", "content": (
                f"请为以下需求生成精简项目计划。\n\n## 用户需求\n{requirement}\n\n"
                f"**约束:** 严格只允许 **1 个任务**。输出纯 JSON。"
            )},
        ],
        temperature=0.1,
    )
    output = resp.get("content", "")
    existing_ids = set(memory.tasks.keys()) if memory else set()

    _emit(on_event, "planning_progress", step="parse", progress=50,
          message="[轻量模式] 正在解析计划...")
    plan = parse_plan(output, requirement_text=requirement, existing_task_ids=existing_ids)

    _emit(on_event, "planning_progress", step="validate", progress=65,
          message="[轻量模式] 正在验证计划...")
    issues = validate_plan(plan, complexity="simple")
    if issues:
        plan = _retry_plan(llm, requirement, issues, "simple")
        retry_issues = validate_plan(plan, complexity="simple")
        if retry_issues:
            raise ValueError(f"无法生成有效计划: {'; '.join(retry_issues)}")

    if memory:
        memory.set_project_plan(plan)
        memory.send_message(
            from_agent="Planner", to_agent="all",
            content=f"[轻量模式] 计划完成: {plan.project_name}",
            msg_type="plan_ready",
        )

    _emit(on_event, "planning_progress", step="complete", progress=100,
          message=f"[轻量模式] 完成，共 {len(plan.tasks)} 个任务")
    return plan


def generate_incremental_plan(
    llm,
    requirement: str,
    file_ops=None,
    memory: SharedMemory | None = None,
    complexity: str = "medium",
    on_event: Callable | None = None,
) -> ProjectPlan:
    """已有项目增量规划 — 直接 LLM 调用 + 文件上下文"""
    _emit(on_event, "planning_progress", step="prepare", progress=5,
          message="[增量模式] 正在分析现有项目...")

    existing_files = _list_workspace_files(file_ops) if file_ops else "（无文件信息）"

    task_prompt = (
        f"## 增量开发任务\n\n"
        f"### 现有项目文件\n{existing_files}\n\n"
        f"### 新需求\n{requirement}\n\n"
        f"请分析现有项目结构，规划增量实现新需求的任务。\n"
        f"注意: 不要重写已有功能，只添加/修改需要的部分。\n\n"
        f"输出纯 JSON 格式项目计划。"
    )

    if memory and memory.tasks:
        task_lines = ["\n### 已有任务"]
        for t in memory.tasks.values():
            status = "PASS" if t.passes else t.status.value
            task_lines.append(f"- [{t.id}] {t.title} ({status})")
        task_prompt += "\n".join(task_lines)

    _emit(on_event, "planning_progress", step="llm_call", progress=10,
          message="[增量模式] 正在调用 LLM 生成增量计划...")
    resp = llm.chat(
        messages=[
            {"role": "system", "content": _get_system_prompt()},
            {"role": "user", "content": task_prompt},
        ],
        temperature=0.1,
    )
    output = resp.get("content", "")

    _emit(on_event, "planning_progress", step="parse", progress=45,
          message="[增量模式] 正在解析任务列表...")
    existing_ids = set(memory.tasks.keys()) if memory else set()
    plan = parse_plan(output, requirement_text=requirement, existing_task_ids=existing_ids)

    _emit(on_event, "planning_progress", step="validate", progress=60,
          message="[增量模式] 正在验证计划质量...")
    issues = validate_plan(plan, complexity=complexity)
    if issues:
        _emit(on_event, "planning_progress", step="retry", progress=65,
              message="[增量模式] 正在重试...")
        plan = _retry_plan(llm, requirement, issues, complexity)
        retry_issues = validate_plan(plan, complexity=complexity)
        if retry_issues:
            raise ValueError(f"无法生成有效计划: {'; '.join(retry_issues)}")

    if memory:
        memory.set_project_plan(plan)
        memory.send_message(
            from_agent="Planner", to_agent="all",
            content=f"增量计划完成: {plan.project_name}, 新增 {len(plan.tasks)} 个任务",
            msg_type="plan_ready",
        )

    _emit(on_event, "planning_progress", step="complete", progress=100,
          message=f"[增量模式] 完成，新增 {len(plan.tasks)} 个任务")
    return plan


def generate_next_batch(
    llm,
    requirement: str,
    file_ops=None,
    memory: SharedMemory | None = None,
    batch_num: int = 1,
    batch_size: int = 5,
    tech_stack: list[str] | None = None,
    project_name: str = "",
    complexity: str = "medium",
    on_event: Callable | None = None,
) -> ProjectPlan | None:
    """批次增量规划 — 生成下一批任务"""
    _emit(on_event, "planning_progress", step="prepare", progress=5,
          message=f"[增量规划] 正在准备第 {batch_num} 批任务上下文...")

    existing_files = _list_workspace_files(file_ops) if file_ops else "（空目录）"

    task_context = ""
    if memory and memory.tasks:
        lines = []
        for t in memory.tasks.values():
            status = "PASS" if t.passes else t.status.value
            lines.append(f"- [{t.id}] {t.title} ({status})")
        task_context = "\n## 已有任务\n" + "\n".join(lines)

    tech_str = ", ".join(tech_stack) if tech_stack else "由你决定"
    tech_constraint = ""
    if tech_stack:
        tech_constraint = (
            f"\n\n## 【硬约束】技术栈\n"
            f"用户指定: **{tech_str}**\n"
            f"必须使用且仅使用指定框架。"
        )

    user_msg = (
        f"## 原始需求\n{requirement}\n"
        f"\n## 技术栈\n{tech_str}\n"
        f"{tech_constraint}"
        f"\n## 当前项目文件\n{existing_files}\n"
        f"{task_context}\n"
        f"\n## 任务\n"
        f"请规划接下来 **最多 {batch_size} 个** 任务（第 {batch_num} 批）。\n"
        f"如果所有功能已覆盖，设置 \"plan_complete\": true。\n"
        f"输出纯 JSON。"
    )

    _emit(on_event, "planning_progress", step="llm_call", progress=15,
          message=f"[增量规划] 正在调用 LLM 规划第 {batch_num} 批任务...")
    resp = llm.chat(
        messages=[
            {"role": "system", "content": "你是规划师，每次只规划一批任务。直接输出纯 JSON。"},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.1,
    )
    output = resp.get("content", "")

    # 提取 plan_complete 标记
    plan_complete = False
    try:
        raw_json = output.strip()
        if raw_json.startswith("```"):
            start = raw_json.find("{")
            end = raw_json.rfind("}") + 1
            if start >= 0 and end > start:
                raw_json = raw_json[start:end]
        parsed = json.loads(raw_json)
        plan_complete = parsed.get("plan_complete", False)
    except Exception:
        pass

    _emit(on_event, "planning_progress", step="parse", progress=50,
          message=f"[增量规划] 正在解析第 {batch_num} 批任务...")
    existing_ids = set(memory.tasks.keys()) if memory else set()
    plan = parse_plan(output, requirement_text=requirement, existing_task_ids=existing_ids)

    if plan is None or not plan.tasks:
        _emit(on_event, "planning_progress", step="complete", progress=100,
              message="[增量规划] 需求已全部覆盖")
        return None

    issues = validate_plan(plan, complexity=complexity)
    if issues:
        plan = _retry_plan(llm, requirement, issues, complexity)
        if plan is None:
            raise ValueError("规划重试失败：无法解析有效计划")
        retry_issues = validate_plan(plan, complexity=complexity)
        if retry_issues:
            raise ValueError(f"批次规划验证失败（重试后仍不通过）: {'; '.join(retry_issues[:3])}")

    plan.plan_complete = plan_complete

    _emit(on_event, "planning_progress", step="complete", progress=100,
          message=f"[增量规划] 第 {batch_num} 批完成: {len(plan.tasks)} 个新任务")
    return plan
