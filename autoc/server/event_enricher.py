"""SSE 事件富化器 — 为每个事件注入 user_message 和 available_actions

所有事件在推送给前端之前经过此模块，确保：
1. 每个事件都有面向用户的中文可读描述（user_message）
2. 每个事件都声明当前用户可执行的操作列表（available_actions）
3. 技术细节（堆栈/内部错误）与用户摘要分离
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger("autoc.web.enricher")


def enrich_event(event: dict) -> dict:
    """为 SSE 事件注入 user_message 和 available_actions，原地修改并返回"""
    etype = event.get("type", "")
    data = event.get("data") or {}

    handler = _ENRICHMENT_MAP.get(etype)
    if handler:
        try:
            msg, actions = handler(data)
            data["user_message"] = msg
            data["available_actions"] = actions
            event["data"] = data
        except Exception as e:
            logger.debug("事件富化失败 (%s): %s", etype, e)

    return event


def _sanitize_error(raw: str, fallback: str = "执行过程中遇到异常") -> str:
    """将内部错误信息清洗为用户可读摘要：移除堆栈、路径等敏感信息"""
    if not raw:
        return fallback
    if "Traceback" in raw or "File \"/" in raw:
        match = re.search(r"(?:Error|Exception):\s*(.+?)(?:\n|$)", raw)
        return match.group(1).strip()[:120] if match else fallback
    return raw[:200]


# --------------- 各事件类型的富化函数 ---------------
# 每个函数接收 data dict，返回 (user_message, available_actions)


def _enrich_sandbox_preparing(data):
    step = data.get("step", "")
    msg = data.get("message", "")
    return msg or f"正在准备沙箱环境（{step}）...", ["stop"]


def _enrich_sandbox_ready(data):
    return data.get("message", "沙箱环境已就绪"), []


def _enrich_planning_analyzing(data):
    return data.get("message", "正在分析需求..."), ["stop"]


def _enrich_planning_progress(data):
    return data.get("message", "需求分析进行中..."), ["stop"]


def _enrich_complexity_assessed(data):
    levels = {"simple": "简单", "medium": "中等", "complex": "复杂"}
    c = data.get("complexity", "medium")
    return f"需求复杂度评估: {levels.get(c, c)}", []


def _enrich_phase_start(data):
    return data.get("title", data.get("phase", "进入新阶段")), ["stop"]


def _enrich_plan_ready(data):
    plan_md = data.get("plan_md", "")
    if plan_md:
        lines = plan_md.strip().split("\n")
        preview = lines[0] if lines else "PLAN.md 已生成"
        return f"项目规划完成 — {preview}", ["stop", "view_plan"]
    tasks = data.get("tasks", [])
    return f"项目规划完成，共 {len(tasks)} 个任务", ["stop", "view_plan"]


def _enrich_execution_start(data):
    count = data.get("task_count", 0)
    if count > 0:
        return f"开始执行 {count} 个任务", ["stop"]
    return "开始执行实现计划", ["stop"]


def _enrich_loop_start(data):
    max_iter = data.get("max_iterations", 0)
    return f"进入迭代循环（最多 {max_iter} 轮）", ["stop"]


def _enrich_iteration_start(data):
    it = data.get("iteration", 0)
    phase = data.get("phase", "")
    title = data.get("story_title", "")
    phase_zh = {"dev": "开发", "test": "测试", "fix": "修复"}.get(phase, phase)
    suffix = f"：{title}" if title else ""
    return f"第 {it} 轮迭代 — {phase_zh}{suffix}", ["stop"]


def _enrich_task_start(data):
    title = data.get("task_title") or data.get("title") or data.get("task_id", "")
    return f"正在开发: {title}", ["stop"]


def _enrich_task_complete(data):
    title = data.get("task_title") or data.get("task_id", "")
    if data.get("success") is False:
        reason = _sanitize_error(data.get("error", ""), "开发遇到困难")
        return f"任务「{title}」开发遇到困难: {reason}，系统将自动重试", ["view_logs", "stop"]
    return f"已完成: {title}", ["view_code"]


def _enrich_task_verified(data):
    tid = data.get("task_id", "")
    if data.get("passes"):
        return f"任务 {tid} 验证通过", ["view_code"]
    return f"任务 {tid} 验证未通过，等待修复", ["view_logs", "stop"]


def _enrich_file_created(data):
    fp = data.get("file") or data.get("path", "")
    return f"创建文件: {fp}", ["view_code"]


def _enrich_dev_self_test(data):
    passed = data.get("passed", False)
    task_id = data.get("task_id", "")
    if passed:
        return f"任务 {task_id} 开发者自测通过", []
    results = data.get("results", [])
    failed_steps = [r.get("step", "") for r in results if not r.get("passed")]
    detail = f"（失败: {', '.join(failed_steps[:3])}）" if failed_steps else ""
    return f"任务 {task_id} 开发者自测未通过{detail}", ["view_logs"]


def _enrich_smoke_check_failed(data):
    issues = data.get("issues", [])
    count = len(issues)
    return f"冒烟检查发现 {count} 个问题，跳过测试直接修复", ["view_logs"]


def _enrich_deploy_gate(data):
    status = data.get("status", "")
    if status == "starting":
        return "正在检查应用是否可启动...", ["stop"]
    if status == "success":
        url = data.get("url", "")
        return f"应用启动成功{f'（{url}）' if url else ''}", ["view_preview"]
    msg = data.get("message", "启动失败")
    return f"应用无法在容器中启动: {_sanitize_error(msg)}", ["view_logs", "stop"]


def _enrich_test_result(data):
    passed = data.get("tests_passed") or data.get("verified_tasks") or 0
    total = data.get("tests_total") or data.get("total_tasks") or 0
    bugs = data.get("bug_count", 0)
    if bugs > 0:
        return f"发现 {bugs} 个问题（通过 {passed}/{total}），正在自动修复", ["view_bugs", "stop"]
    return f"测试全部通过（{passed}/{total}）", ["view_preview", "view_code"]


def _enrich_failure_analysis(data):
    mode = data.get("mode", "")
    strategy = data.get("strategy", "")
    mode_zh = {"dev_no_output": "开发无产出", "test_regression": "测试回归",
               "persistent_failure": "持续失败"}.get(mode, mode)
    strategy_zh = {"retry": "重试", "rollback": "回滚", "simplify": "简化",
                   "skip": "跳过"}.get(strategy, strategy)
    return f"失败分析: {mode_zh}，推荐策略: {strategy_zh}", ["view_logs"]


def _enrich_bug_fix_start(data):
    count = data.get("count", 0)
    titles = data.get("titles", [])
    detail = f"（{', '.join(titles[:3])}）" if titles else ""
    return f"开始修复 {count} 个 Bug{detail}", ["stop"]


def _enrich_bug_fix_progress(data):
    title = data.get("bug_title", "")
    status = data.get("status", "")
    status_zh = {"fixing": "修复中", "fixed": "已修复", "failed": "修复失败"}.get(status, status)
    return f"Bug「{title}」{status_zh}", ["stop"]


def _enrich_bug_fix_done(data):
    fixed = data.get("fixed", 0)
    total = data.get("total", 0)
    return f"Bug 修复完成: {fixed}/{total} 已修复", ["view_code"]


def _enrich_reflection(data):
    content = data.get("content", "")[:100]
    return f"系统正在进行根因分析: {content}...", []


def _enrich_planning_review(data):
    status = data.get("status", "")
    if status == "starting":
        return "正在进行最终验收...", ["stop"]
    summary = data.get("summary", "")[:100]
    return f"验收评审中: {summary}", ["stop"]


def _enrich_planning_acceptance(data):
    if data.get("passed"):
        score = data.get("score", "")
        return f"验收通过{f'（评分: {score}）' if score else ''}", ["view_preview", "view_code"]
    reason = data.get("answer", "")[:100]
    return f"验收未通过: {reason}", ["view_logs", "stop"]


def _enrich_planning_decision(data):
    action = data.get("action", "")
    task_id = data.get("task_id", "")
    reason = data.get("reason", "")[:100]
    action_msg = {
        "retry": f"决定重试任务 {task_id}",
        "simplify": f"决定简化任务 {task_id}",
        "skip": f"决定跳过任务 {task_id}",
        "replan": "决定重新规划",
        "clarify": "请求澄清需求",
        "common_failure": "检测到共性失败模式",
    }.get(action, f"AI 决策: {action}")
    suffix = f"（原因: {reason}）" if reason else ""
    actions_map = {
        "retry": ["stop"],
        "simplify": ["stop"],
        "skip": ["modify_requirement"],
        "replan": ["modify_requirement"],
        "clarify": ["modify_requirement"],
        "common_failure": ["modify_requirement", "stop"],
    }
    return f"{action_msg}{suffix}", actions_map.get(action, ["stop"])


def _enrich_iteration_done(data):
    it = data.get("iteration", 0)
    success = data.get("success")
    if success is True:
        return f"第 {it} 轮迭代完成", []
    if success is False:
        err = _sanitize_error(data.get("error", ""), "迭代未通过")
        return f"第 {it} 轮迭代未通过: {err}", ["view_logs"]
    return f"第 {it} 轮迭代结束", []


def _enrich_execution_failed(data):
    reason = _sanitize_error(data.get("failure_reason", ""), "执行未能完成")
    return f"执行未能完成: {reason}", ["retry", "resume", "modify_requirement"]


def _enrich_preview_ready(data):
    url = data.get("url", "")
    if data.get("available") and url:
        return f"预览已就绪: {url}", ["view_preview"]
    return "预览准备中...", []


def _enrich_preview_stopped(data):
    return "预览已停止", []


def _enrich_summary(data):
    success = data.get("success")
    tokens = data.get("total_tokens", 0)
    if success:
        return f"执行完成，共消耗 {tokens:,} Token", ["view_preview", "view_code"]
    return f"执行未完全成功，共消耗 {tokens:,} Token", ["retry", "resume"]


def _enrich_token_session(data):
    tokens = data.get("total_tokens", 0)
    return f"本次消耗 {tokens:,} Token", []


def _enrich_error(data):
    msg = _sanitize_error(data.get("message", ""), "发生错误")
    return f"错误: {msg}", ["retry", "stop"]


def _enrich_done(data):
    if data.get("success"):
        return "项目开发完成！", ["view_preview", "view_code", "new_feature", "rerun"]
    reason = _sanitize_error(data.get("failure_reason", ""), "")
    if reason:
        return f"项目未完成: {reason}", ["resume", "retry", "quick_fix", "modify_requirement"]
    return "项目未完成，可点击重试", ["retry", "modify_requirement"]


def _enrich_resume_start(data):
    return "恢复执行中...", ["stop"]


def _enrich_quick_fix_start(data):
    count = data.get("bug_count", 0)
    return f"快速修复 {count} 个 Bug", ["stop"]


def _enrich_quick_fix_done(data):
    fixed = data.get("fixed", 0)
    total = data.get("total", 0)
    return f"快速修复完成: {fixed}/{total} 已修复", ["view_code", "retry"]


def _enrich_thinking_content(data):
    agent = data.get("agent", "")
    return f"{agent} 正在思考...", []


def _enrich_refiner_quality(data):
    score = data.get("score") or data.get("quality_score", "")
    return f"需求质量评分: {score}", []


def _enrich_refiner_enhanced(data):
    return "需求已优化增强", []


def _enrich_refiner_warning(data):
    msg = data.get("message", "")[:100]
    return f"需求警告: {msg}", ["modify_requirement"]


def _enrich_plan_approval_required(data):
    timeout = data.get("timeout_seconds", 600)
    return f"计划已生成，等待您确认后开始开发（{timeout // 60} 分钟内未确认将自动继续）", [
        "approve_plan", "reject_plan", "stop"
    ]


# --------------- 富化函数注册表 ---------------

_ENRICHMENT_MAP: dict[str, callable] = {
    "sandbox_preparing": _enrich_sandbox_preparing,
    "sandbox_ready": _enrich_sandbox_ready,
    "planning_analyzing": _enrich_planning_analyzing,
    "planning_progress": _enrich_planning_progress,
    "complexity_assessed": _enrich_complexity_assessed,
    "phase_start": _enrich_phase_start,
    "plan_ready": _enrich_plan_ready,
    "execution_start": _enrich_execution_start,
    "loop_start": _enrich_loop_start,
    "iteration_start": _enrich_iteration_start,
    "iteration_done": _enrich_iteration_done,
    "task_start": _enrich_task_start,
    "task_complete": _enrich_task_complete,
    "task_verified": _enrich_task_verified,
    "file_created": _enrich_file_created,
    "dev_self_test": _enrich_dev_self_test,
    "smoke_check_failed": _enrich_smoke_check_failed,
    "deploy_gate": _enrich_deploy_gate,
    "test_result": _enrich_test_result,
    "failure_analysis": _enrich_failure_analysis,
    "bug_fix_start": _enrich_bug_fix_start,
    "bug_fix_progress": _enrich_bug_fix_progress,
    "bug_fix_done": _enrich_bug_fix_done,
    "reflection": _enrich_reflection,
    "planning_review": _enrich_planning_review,
    "planning_acceptance": _enrich_planning_acceptance,
    "planning_decision": _enrich_planning_decision,
    "execution_failed": _enrich_execution_failed,
    "preview_ready": _enrich_preview_ready,
    "preview_stopped": _enrich_preview_stopped,
    "summary": _enrich_summary,
    "token_session": _enrich_token_session,
    "error": _enrich_error,
    "done": _enrich_done,
    "resume_start": _enrich_resume_start,
    "quick_fix_start": _enrich_quick_fix_start,
    "quick_fix_done": _enrich_quick_fix_done,
    "thinking_content": _enrich_thinking_content,
    "refiner_quality": _enrich_refiner_quality,
    "refiner_enhanced": _enrich_refiner_enhanced,
    "refiner_warning": _enrich_refiner_warning,
    "plan_approval_required": _enrich_plan_approval_required,
}
