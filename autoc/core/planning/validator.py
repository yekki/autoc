"""计划解析与质量验证 — 纯函数

质量门控体系:
- L5 自动清理: 移除 pytest 文件（测试由 CodeActAgent 自行完成）
- 快照: 保存 LLM 原始 verification_steps
- L4 自动补全: 补充 test -f / py_compile
- L1 结构完整性: task 必须有 description/files/verification_steps
- L2 规约质量: 基于快照判断
- L3 架构合理性: 垂直切片、DAG 拓扑排序
"""

import json
import logging
import os.path as _osp
import re
from typing import Any

from autoc.core.project.memory import ProjectPlan, Task, TaskStatus

logger = logging.getLogger("autoc.planning")

_EXECUTABLE_PATTERNS = re.compile(
    r"(python\s|curl\s|test\s+-[fde]|pip\s|npm\s|node\s|pytest|"
    r"py_compile|grep\s|cat\s|ls\s|cd\s|echo\s|sh\s|bash\s|"
    r"python3\s|\.\/|which\s|command\s|java\s|go\s|cargo\s|"
    r"http://|https://)",
    re.IGNORECASE,
)

_VAGUE_PATTERNS = re.compile(
    r"^(应用|程序|系统|页面|功能|数据|接口|服务|模块|组件|界面"
    r"|在浏览器|在终端|确认|检查|验证|确保|查看|打开|手动)"
    r".*(正常|正确|成功|完成|通过|运行|显示|工作|可用|没有|无|交互)",
)

_BABBLE_PATTERNS = re.compile(
    r"^(我来|让我|好的|我需要|我将|我会|我先|OK|Sure|Let me|Alright|I'll|I will)",
    re.IGNORECASE,
)

_TEST_FILE_RE = re.compile(r"(tests?/)?test_\w+\.py$|_test\.py$")

_DATA_MODEL_RE = re.compile(
    r"(class\s+\w+\(.*?(?:Model|Base)\)[\s\S]*?(?=\nclass\s|\n\n\n|\Z))"
    r"|(CREATE\s+TABLE\s+\w+\s*\([\s\S]*?\);)",
    re.IGNORECASE,
)
_API_ROUTE_RE = re.compile(
    r"((?:GET|POST|PUT|DELETE|PATCH)\s+/\S+.*)",
    re.IGNORECASE,
)

TASK_LIMITS: dict[str, tuple[int, int]] = {
    "simple": (1, 1),
    "medium": (2, 5),
    "complex": (3, 12),
}

_INFRA_LAYER_KW = ["数据库模型", "数据库设计", "表结构设计", "数据模型设计"]
_UI_LAYER_KW = ["前端集成", "UI美化", "界面美化", "样式设计", "CSS样式", "页面美化"]

_MAIN_ENTRY_FILES = {
    "app.py", "main.py", "index.py", "server.py", "manage.py",
    "__init__.py", "wsgi.py", "config.py", "settings.py",
    "requirements.txt", "package.json", "pyproject.toml",
    "App.tsx", "App.jsx", "App.vue", "main.tsx", "main.jsx", "main.ts",
    "index.tsx", "index.jsx", "index.ts", "index.html",
    "vite.config.ts", "vite.config.js", "tsconfig.json",
    "tailwind.config.js", "tailwind.config.ts",
    "router.tsx", "router.ts", "routes.tsx", "routes.ts",
    "app.js", "main.js", "script.js", "index.js",
    "app.css", "main.css", "style.css", "styles.css",
    "docker-compose.yml", "Dockerfile", ".env", ".env.example",
    "Makefile", "README.md",
}


def topo_sort_tasks(tasks: list[Task]) -> tuple[list[str], list[str]]:
    """拓扑排序，返回 (排序后 id 列表, 循环中的 id 列表)"""
    task_ids = {t.id for t in tasks}
    adj: dict[str, list[str]] = {t.id: [] for t in tasks}
    in_degree: dict[str, int] = {t.id: 0 for t in tasks}

    for t in tasks:
        for dep in t.dependencies:
            if dep in task_ids:
                adj[dep].append(t.id)
                in_degree[t.id] += 1

    queue = [tid for tid, deg in in_degree.items() if deg == 0]
    sorted_ids: list[str] = []

    while queue:
        queue.sort()
        sorted_ids.extend(queue)
        next_queue = []
        for tid in queue:
            for neighbor in adj[tid]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    next_queue.append(neighbor)
        queue = next_queue

    cycle_ids = [tid for tid in task_ids if tid not in set(sorted_ids)]
    return sorted_ids, cycle_ids


def auto_complete_verification(task: Task):
    """L4 自动补全：补充语法检查、文件存在性检查、Web 内容完整性检查"""
    existing = set(task.verification_steps)

    has_html = False
    for f in task.files:
        existence_check = f"test -f {f}"
        if existence_check not in existing and not _is_covered(existence_check, existing):
            task.verification_steps.append(existence_check)
            existing.add(existence_check)
        if f.endswith(".py"):
            syntax_check = f"python -m py_compile {f}"
            if syntax_check not in existing and not _is_covered(syntax_check, existing):
                task.verification_steps.append(syntax_check)
                existing.add(syntax_check)
        if f.endswith(".html"):
            has_html = True

    # Web 前端项目：验证 HTML 文件包含基本结构
    if has_html:
        html_files = [f for f in task.files if f.endswith(".html")]
        for hf in html_files:
            struct_check = f'grep -q "<!DOCTYPE\\|<html\\|<body" {hf}'
            if struct_check not in existing:
                task.verification_steps.append(struct_check)
                existing.add(struct_check)


def _is_covered(step: str, existing: set[str]) -> bool:
    target = step.split()[-1] if step.split() else ""
    if not target:
        return False
    cmd_prefix = " ".join(step.split()[:-1])
    for e in existing:
        if e == step:
            continue
        if e.startswith(cmd_prefix) and target in e:
            return True
    return False


def _extract_json(output: str) -> dict | None:
    """从 LLM 输出中提取 JSON 对象"""
    json_str = output.strip()
    if json_str.startswith("```"):
        lines = json_str.split("\n")
        start, end = 0, len(lines)
        for i, line in enumerate(lines):
            if line.strip().startswith("{"):
                start = i
                break
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].strip().startswith("}"):
                end = i + 1
                break
        json_str = "\n".join(lines[start:end])
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        start = output.find("{")
        end = output.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(output[start:end])
            except json.JSONDecodeError:
                pass
    return None


def _normalize_file_list(raw_files: list) -> list[str]:
    """LLM 可能返回 files 为字典列表 [{path, content}]，统一提取为纯路径字符串"""
    result = []
    for f in raw_files:
        if isinstance(f, dict):
            path = f.get("path") or f.get("name") or f.get("file", "")
            if path:
                result.append(str(path))
        elif isinstance(f, str):
            result.append(f)
        else:
            result.append(str(f))
    return result


def parse_plan(
    output: str,
    requirement_text: str = "",
    existing_task_ids: set[str] | None = None,
) -> ProjectPlan | None:
    """解析 LLM 输出为 ProjectPlan"""
    existing_task_ids = existing_task_ids or set()
    data = _extract_json(output)
    if data is None:
        logger.error(f"无法解析项目计划 JSON: {output[:200]}")
        return None

    if "tasks" not in data:
        logger.error("JSON 中缺少 tasks 字段")
        return None

    existing_max = 0
    for tid in existing_task_ids:
        try:
            existing_max = max(existing_max, int(tid.rsplit("-", 1)[-1]))
        except (ValueError, IndexError):
            pass

    used_ids = set(existing_task_ids)
    tasks = []
    for task_data in data.get("tasks", []):
        task_id = task_data.get("id") or f"task-{existing_max + len(tasks) + 1}"
        if task_id in used_ids:
            # 寻找本批次内未使用的 ID，避免批次内 ID 互相冲突
            candidate = existing_max + len(tasks) + 1
            while f"task-{candidate}" in used_ids:
                candidate += 1
            task_id = f"task-{candidate}"
        used_ids.add(task_id)
        tasks.append(Task(
            id=task_id,
            title=task_data.get("title", ""),
            description=task_data.get("description", ""),
            status=TaskStatus.PENDING,
            priority=task_data.get("priority", 1),
            dependencies=task_data.get("dependencies", []),
            files=_normalize_file_list(task_data.get("files", [])),
            verification_steps=task_data.get("verification_steps", []),
            acceptance_criteria=task_data.get("acceptance_criteria", []),
            acceptance_tests=task_data.get("acceptance_tests", []),
            passes=False,
            feature_tag=task_data.get("feature_tag", ""),
        ))

    from autoc.core.project.models import TechDecision
    raw_decisions = data.get("tech_decisions", [])
    tech_decisions = []
    for td in raw_decisions:
        if isinstance(td, dict):
            tech_decisions.append(TechDecision(
                tech=td.get("tech", ""),
                action=td.get("action", "added"),
                original=td.get("original", ""),
                reason=td.get("reason", ""),
            ))

    plan = ProjectPlan(
        project_name=data.get("project_name", ""),
        description=data.get("description", requirement_text or ""),
        tech_stack=data.get("tech_stack", []),
        tech_decisions=tech_decisions,
        architecture=data.get("architecture", ""),
        directory_structure=data.get("directory_structure", ""),
        tasks=tasks,
        risk_assessment=data.get("risk_assessment", ""),
        user_stories=data.get("user_stories", []),
        data_models=data.get("data_models", ""),
        api_design=data.get("api_design", ""),
    )

    if not plan.data_models:
        plan.data_models = _extract_data_models_from_tasks(plan.tasks)
    if not plan.api_design:
        plan.api_design = _extract_api_design_from_tasks(plan.tasks)

    logger.info(
        f"项目计划解析完成: {plan.project_name}, "
        f"技术栈: {', '.join(plan.tech_stack)}, 任务数: {len(plan.tasks)}"
    )
    return plan


def validate_plan(plan: ProjectPlan | None, complexity: str = "medium") -> list[str]:
    """验证计划质量，返回问题列表（空=通过）"""
    if plan is None:
        return ["计划解析失败: LLM 输出不是有效的 JSON"]

    issues: list[str] = []
    if not plan.tasks:
        return ["计划不含任何任务"]

    for task in plan.tasks:
        prefix = f"任务 [{task.id}] "

        # L5: 移除 pytest 文件
        test_files = [f for f in task.files if _TEST_FILE_RE.search(f)]
        if test_files:
            task.files = [f for f in task.files if f not in test_files]
            logger.info(f"{prefix}自动移除 pytest 文件 {test_files}")

        original_steps = list(task.verification_steps)
        auto_complete_verification(task)

        # L1: 结构完整性
        if not task.description or len(task.description.strip()) < 10:
            issues.append(f"{prefix}缺少有效描述")
        elif _BABBLE_PATTERNS.match(task.description.strip()):
            issues.append(f"{prefix}描述是 LLM 自言自语，不是实现指令")
        if not task.files:
            issues.append(f"{prefix}未指定需要创建的文件")
        if not original_steps:
            issues.append(f"{prefix}缺少 verification_steps")

        # L2: 可执行性
        if original_steps:
            executable_count = sum(
                1 for s in original_steps if _EXECUTABLE_PATTERNS.search(s)
            )
            vague_count = sum(
                1 for s in original_steps if _VAGUE_PATTERNS.match(s.strip())
            )
            if executable_count == 0 and len(original_steps) >= 2:
                issues.append(
                    f"{prefix}verification_steps 全部是自然语言描述，"
                    "必须包含可执行 shell 命令"
                )
            elif vague_count > executable_count:
                issues.append(
                    f"{prefix}verification_steps 中模糊描述 ({vague_count}) "
                    f"多于可执行命令 ({executable_count})"
                )

    min_tasks, max_tasks = TASK_LIMITS.get(complexity, (3, 12))
    if len(plan.tasks) > max_tasks:
        issues.append(
            f"任务数量过多: {len(plan.tasks)} 个"
            f"（{complexity} 复杂度上限 {max_tasks} 个）"
        )
    if complexity != "simple" and len(plan.tasks) < min_tasks:
        issues.append(
            f"任务数量不足: {len(plan.tasks)} 个"
            f"（{complexity} 复杂度至少 {min_tasks} 个）"
        )

    # 粒度量化
    _files_limit = {"simple": 6, "medium": 8, "complex": 10}
    max_files = _files_limit.get(complexity, 6)
    for task in plan.tasks:
        prefix = f"任务 [{task.id}] "
        if len(task.files) > max_files:
            issues.append(f"{prefix}涉及 {len(task.files)} 个文件（上限 {max_files}）")
        if len(task.dependencies) > 2:
            issues.append(f"{prefix}依赖 {len(task.dependencies)} 个任务（上限 2）")

    # 文件重叠检测
    file_to_tasks: dict[str, list[str]] = {}
    for task in plan.tasks:
        for f in task.files:
            file_to_tasks.setdefault(f, []).append(task.id)
    _entry_lower = {n.lower() for n in _MAIN_ENTRY_FILES}
    overlapping = {
        f: tids for f, tids in file_to_tasks.items()
        if len(tids) >= 4
        and _osp.basename(f).lower() not in _entry_lower
        and not f.endswith((".html", ".css", ".txt"))
    }
    if overlapping:
        samples = ", ".join(
            f"{f}({len(tids)}个任务)" for f, tids in list(overlapping.items())[:3]
        )
        issues.append(f"文件过度重叠: {samples}")

    # 水平切片检测
    if len(plan.tasks) >= 4:
        infra_tasks = [
            t for t in plan.tasks
            if any(kw in t.title for kw in _INFRA_LAYER_KW) and len(t.files) <= 2
        ]
        ui_tasks = [
            t for t in plan.tasks
            if any(kw in t.title for kw in _UI_LAYER_KW) and len(t.files) <= 2
        ]
        if infra_tasks and ui_tasks:
            issues.append("检测到水平切片反模式，应改为垂直切片")

    # DAG 拓扑排序 + 循环检测
    if len(plan.tasks) >= 2:
        sorted_ids, cycle_ids = topo_sort_tasks(plan.tasks)
        if cycle_ids:
            issues.append(f"依赖循环: {', '.join(cycle_ids)}")
        elif sorted_ids:
            id_to_task = {t.id: t for t in plan.tasks}
            plan.tasks = [id_to_task[tid] for tid in sorted_ids if tid in id_to_task]

    # 复杂度驱动粒度下限（仅在 TASK_LIMITS 硬约束未触发时补充更精准的建议）
    hard_min, _ = TASK_LIMITS.get(complexity, (3, 12))
    if complexity != "simple" and len(plan.tasks) >= hard_min:
        try:
            from autoc.core.analysis.complexity import estimate_scope
            req_text = plan.description or " ".join(t.description for t in plan.tasks)
            if req_text:
                scope = estimate_scope(req_text)
                soft_min = scope.get("min_tasks", 3)
                if complexity == "medium":
                    soft_min = max(2, soft_min - 1)
                if len(plan.tasks) < soft_min:
                    issues.append(
                        f"任务数量不足: {len(plan.tasks)} 个（建议至少 {soft_min} 个）"
                    )
        except Exception:
            pass

    return issues


def _extract_data_models_from_tasks(tasks: list[Task]) -> str:
    fragments: list[str] = []
    for t in tasks:
        for m in _DATA_MODEL_RE.finditer(t.description):
            text = (m.group(1) or m.group(2) or "").strip()
            if text and text not in fragments:
                fragments.append(text)
    return "\n\n".join(fragments)[:2000] if fragments else ""


def _extract_api_design_from_tasks(tasks: list[Task]) -> str:
    routes: list[str] = []
    seen: set[str] = set()
    for t in tasks:
        for m in _API_ROUTE_RE.finditer(t.description):
            line = m.group(1).strip()
            key = line.split()[1] if len(line.split()) > 1 else line
            if key not in seen:
                routes.append(line)
                seen.add(key)
    return "\n".join(routes)[:2000] if routes else ""
