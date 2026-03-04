"""安全检查模块 — Token 预算检查 / Git 回滚推断 / Planning 审批门

从 orchestrator.py 拆分，负责安全拦截相关逻辑。
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .facade import Orchestrator

logger = logging.getLogger("autoc.gates")

# ==================== S-002: Planning 审批门 ====================
# 跨线程通信：orchestrator 工作线程等待，FastAPI 主线程通知

_plan_approval_events: dict[str, threading.Event] = {}
_plan_approval_results: dict[str, dict] = {}
_plan_approval_lock = threading.Lock()


def register_approval_gate(session_id: str) -> threading.Event:
    """注册一个审批门，返回 threading.Event（orchestrator 等待此事件）"""
    evt = threading.Event()
    with _plan_approval_lock:
        _plan_approval_events[session_id] = evt
    return evt


def set_approval_result(session_id: str, approved: bool, feedback: str = "") -> bool:
    """从 API 层通知审批结果，唤醒等待中的 orchestrator 线程。

    Returns True if gate exists, False if no gate registered.
    """
    with _plan_approval_lock:
        evt = _plan_approval_events.get(session_id)
        if evt is None:
            return False
        _plan_approval_results[session_id] = {"approved": approved, "feedback": feedback}
    evt.set()
    return True


def get_approval_result(session_id: str) -> dict | None:
    with _plan_approval_lock:
        return _plan_approval_results.get(session_id)


def cleanup_approval_gate(session_id: str):
    with _plan_approval_lock:
        _plan_approval_events.pop(session_id, None)
        _plan_approval_results.pop(session_id, None)


def has_approval_gate(session_id: str) -> bool:
    with _plan_approval_lock:
        return session_id in _plan_approval_events

# AutoC 内部文件集合（工作区清理时保留）
AUTOC_INTERNAL_FILES = {
    ".autoc.db", ".autoc.db-shm", ".autoc.db-wal",
    "autoc-progress.txt", "autoc-tasks.json", "project-plan.json",
    ".gitignore", ".git",
}

_WARNING_THRESHOLD = 0.8


def check_token_budget(orc: Orchestrator, phase: str) -> bool:
    """检查当前 Token 消耗是否在预算内。

    返回 True 表示可继续，False 表示预算已耗尽应跳过当前阶段。
    达到 80% 时输出黄色警告但仍允许继续。
    budget 为 0 表示不限预算。
    """
    budget = getattr(orc, "_token_budget", 0)
    if not budget:
        return True

    used = getattr(orc, "total_tokens", 0)

    if used >= budget:
        logger.warning(
            "Token 预算耗尽: %d/%d (%.0f%%)，跳过 %s 阶段",
            used, budget, used / budget * 100, phase,
        )
        return False

    if used >= budget * _WARNING_THRESHOLD:
        logger.warning(
            "⚠️ Token 预算已用 %.0f%%: %d/%d，%s 阶段继续但请注意",
            used / budget * 100, used, budget, phase,
        )

    return True


def infer_rollback_commit(orc: Orchestrator, task_ids: list[str]) -> str:
    """从 git log 推断回滚点（按优先级尝试多种策略）

    策略优先级:
      1. 查找与本需求任务 ID 相关的最早 commit 的前一个
      2. 查找最近的 "project plan" commit
      3. 查找最近的 "project complete" commit
      4. 查找最早的 feat commit 的前一个
    """
    if not orc.git_ops:
        return ""
    code, log_output = orc.git_ops._run_git("log", "--oneline", "--reverse")
    if code != 0 or not log_output.strip():
        return ""

    lines = log_output.strip().split("\n")

    # 策略1：查找包含本需求任务 ID 的最早 commit 的前一个
    if task_ids:
        for i, line in enumerate(lines):
            for tid in task_ids:
                if tid in line:
                    if i > 0:
                        commit_hash = lines[i - 1].split()[0]
                        logger.info(f"回滚策略1命中: task {tid} → {commit_hash}")
                        return commit_hash
                    return ""

    # 策略2-4 使用逆序日志（最近在前）
    code2, log_rev = orc.git_ops._run_git("log", "--oneline")
    if code2 != 0 or not log_rev.strip():
        return ""
    rev_lines = log_rev.strip().split("\n")

    # 策略2：找最近的 "project plan" commit
    for line in rev_lines:
        if "feat: project plan" in line:
            commit_hash = line.split()[0]
            logger.info(f"回滚策略2命中: project plan → {commit_hash}")
            return commit_hash

    # 策略3：找最近的 "project complete" commit
    for line in rev_lines:
        if "feat: project complete" in line:
            commit_hash = line.split()[0]
            logger.info(f"回滚策略3命中: project complete → {commit_hash}")
            return commit_hash

    # 策略4：找最早的 feat commit 的前一个
    for i, line in enumerate(lines):
        if line.strip() and ("feat:" in line or "plan:" in line):
            if i > 0:
                commit_hash = lines[i - 1].split()[0]
                logger.info(f"回滚策略4命中: first feat → {commit_hash}")
                return commit_hash
            break

    logger.warning("所有回滚策略均未命中，将使用工作区清理兜底")
    return ""
