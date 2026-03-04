"""诊断报告生成器 — 收集迭代指标、状态转换、一致性检查，输出结构化报告"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("autoc.testing.report")


@dataclass
class IterationMetric:
    """单次迭代的指标"""
    iteration: int = 0
    phase: str = ""
    task_id: str = ""
    task_title: str = ""
    success: bool = False
    error: str = ""
    tokens_used: int = 0
    elapsed_s: float = 0.0
    files_changed: list[str] = field(default_factory=list)


@dataclass
class StateCheck:
    """状态一致性检查结果"""
    check_name: str = ""
    passed: bool = False
    details: str = ""


@dataclass
class Issue:
    """发现的问题"""
    severity: str = "P2"   # P0 / P1 / P2
    component: str = ""    # orchestrator / sandbox / state / agent
    summary: str = ""
    details: str = ""


class DiagnosticReport:
    """诊断报告收集器 + 输出器"""

    def __init__(self, test_case: str, mode: str):
        self.test_case = test_case
        self.mode = mode  # "mock-planning" / "real-planning"
        self.start_time: float = 0
        self.end_time: float = 0

        # 各阶段指标
        self.planning_elapsed_s: float = 0
        self.planning_tasks_count: int = 0
        self.planning_error: str = ""

        self.sandbox_available: bool = False
        self.sandbox_container: str = ""
        self.sandbox_error: str = ""

        self.iterations: list[IterationMetric] = []
        self.state_checks: list[StateCheck] = []
        self.phase_transitions: list[tuple[str, str, str]] = []
        self.issues: list[Issue] = []

        # 总计
        self.total_tokens: int = 0
        self.exit_reason: str = ""
        self.final_success: bool = False

    def start(self):
        self.start_time = time.time()

    def finish(self):
        self.end_time = time.time()

    def record_planning(self, elapsed: float, tasks_count: int, error: str = ""):
        self.planning_elapsed_s = elapsed
        self.planning_tasks_count = tasks_count
        self.planning_error = error

    def record_sandbox(self, available: bool, container: str = "", error: str = ""):
        self.sandbox_available = available
        self.sandbox_container = container
        self.sandbox_error = error

    def record_iteration(self, metric: IterationMetric):
        self.iterations.append(metric)
        self.total_tokens += metric.tokens_used

    def check_state_consistency(self, state_manager) -> list[StateCheck]:
        """检查 StateManager 的读写一致性"""
        checks = []

        # 检查 1: prd.json 读写一致性
        try:
            prd = state_manager.load_prd()
            state_manager.save_prd(prd)
            prd2 = state_manager.load_prd()
            task_ids_1 = sorted(t.id for t in prd.tasks)
            task_ids_2 = sorted(t.id for t in prd2.tasks)
            passes_1 = {t.id: t.passes for t in prd.tasks}
            passes_2 = {t.id: t.passes for t in prd2.tasks}
            consistent = (task_ids_1 == task_ids_2 and passes_1 == passes_2)
            checks.append(StateCheck(
                check_name="prd.json 读写一致性",
                passed=consistent,
                details=(
                    "保存后重新加载，任务 ID 和 passes 一致"
                    if consistent else
                    f"不一致！IDs: {task_ids_1} vs {task_ids_2}, "
                    f"passes: {passes_1} vs {passes_2}"
                ),
            ))
        except Exception as e:
            checks.append(StateCheck(
                check_name="prd.json 读写一致性",
                passed=False,
                details=f"异常: {e}",
            ))

        # 检查 2: progress.txt 可写
        try:
            from autoc.core.project.models import Task as _Task
            _dummy_task = _Task(id="diag-check", title="诊断检查")
            state_manager.append_progress(
                story=_dummy_task, iteration=0,
                summary="诊断测试写入检查",
                files_changed=[], learnings=[],
            )
            checks.append(StateCheck(
                check_name="progress.txt 可写",
                passed=True,
                details="写入成功",
            ))
        except Exception as e:
            checks.append(StateCheck(
                check_name="progress.txt 可写",
                passed=False,
                details=f"写入失败: {e}",
            ))

        # 检查 3: prd.json 字段完整性（verification_steps / files 不丢失）
        try:
            prd = state_manager.load_prd()
            missing_fields = []
            for task in prd.tasks:
                if not task.files:
                    missing_fields.append(f"{task.id}: files 为空")
                if not task.verification_steps:
                    missing_fields.append(f"{task.id}: verification_steps 为空")
            passed = len(missing_fields) == 0
            checks.append(StateCheck(
                check_name="prd.json 字段完整性",
                passed=passed,
                details=(
                    f"所有 {len(prd.tasks)} 个任务字段完整"
                    if passed else
                    f"缺失: {'; '.join(missing_fields[:5])}"
                ),
            ))
        except Exception as e:
            checks.append(StateCheck(
                check_name="prd.json 字段完整性",
                passed=False,
                details=f"异常: {e}",
            ))

        # 检查 4: 并发读写安全（快速连续 save→load 10 次）
        try:
            prd = state_manager.load_prd()
            all_consistent = True
            for i in range(10):
                state_manager.save_prd(prd)
                prd_reload = state_manager.load_prd()
                if sorted(t.id for t in prd_reload.tasks) != sorted(t.id for t in prd.tasks):
                    all_consistent = False
                    break
            checks.append(StateCheck(
                check_name="prd.json 快速连续读写 (10次)",
                passed=all_consistent,
                details="10 次连续 save→load 全部一致" if all_consistent else "出现不一致",
            ))
        except Exception as e:
            checks.append(StateCheck(
                check_name="prd.json 快速连续读写 (10次)",
                passed=False,
                details=f"异常: {e}",
            ))

        self.state_checks = checks
        return checks

    def validate_phase_transitions(self, transitions: list[tuple[str, str, str]]):
        """验证阶段转换是否合法"""
        self.phase_transitions = transitions
        valid_transitions = {
            "plan": {"dev"},
            "dev": {"test"},
            "test": {"dev", "fix", "planning_review"},
            "fix": {"test", "fix", "plan"},
            "planning_review": {"plan", "dev"},
        }
        for frm, to, reason in transitions:
            valid = valid_transitions.get(frm, set())
            if to not in valid and frm != to:
                self.issues.append(Issue(
                    severity="P1",
                    component="orchestrator",
                    summary=f"非法阶段转换: {frm} → {to}",
                    details=f"reason: {reason}",
                ))

    def add_issue(self, severity: str, component: str, summary: str,
                  details: str = ""):
        self.issues.append(Issue(
            severity=severity, component=component,
            summary=summary, details=details,
        ))

    # ── 输出 ──

    def render_text(self) -> str:
        """生成人类可读的文本报告"""
        total_s = self.end_time - self.start_time if self.end_time else 0
        lines = [
            "=" * 60,
            "  AutoC 系统诊断报告",
            "=" * 60,
            f"测试用例: {self.test_case}",
            f"运行模式: {self.mode}",
            f"总耗时: {total_s:.1f}s",
            f"总 Token: {self.total_tokens}",
            f"退出原因: {self.exit_reason or 'N/A'}",
            f"最终结果: {'PASS' if self.final_success else 'FAIL'}",
            "",
        ]

        # Planning 阶段
        planning_status = "OK" if not self.planning_error else f"FAIL ({self.planning_error})"
        lines.append(
            f"Planning 阶段: {planning_status} "
            f"(耗时 {self.planning_elapsed_s:.1f}s, "
            f"生成 {self.planning_tasks_count} 个任务)"
        )

        # Sandbox
        sb_status = "OK" if self.sandbox_available else (
            f"FAIL ({self.sandbox_error})" if self.sandbox_error else "FAIL (未检测)"
        )
        lines.append(
            f"Sandbox: {sb_status}"
            + (f" (容器 {self.sandbox_container})" if self.sandbox_container else "")
        )
        lines.append("")

        # 迭代详情
        lines.append("--- 迭代详情 ---")
        for m in self.iterations:
            status = "OK" if m.success else "FAIL"
            task_info = f"{m.task_id}" if m.task_id else "N/A"
            lines.append(
                f"  迭代 {m.iteration}: [{m.phase.upper():4s}] {status} "
                f"({task_info}, {len(m.files_changed)} files, "
                f"{m.elapsed_s:.1f}s, {m.tokens_used} tok)"
            )
            if m.error:
                lines.append(f"    → 错误: {m.error[:120]}")
        lines.append("")

        # 状态一致性
        lines.append("--- 状态一致性检查 ---")
        for sc in self.state_checks:
            status = "PASS" if sc.passed else "FAIL"
            lines.append(f"  [{status}] {sc.check_name}: {sc.details[:100]}")
        lines.append("")

        # 阶段转换
        if self.phase_transitions:
            chain = " → ".join(
                f"{to}" for _, to, _ in self.phase_transitions
            )
            lines.append(f"阶段转换链: {chain}")
            lines.append("")

        # 发现的问题
        if self.issues:
            lines.append("--- 发现的问题 ---")
            by_severity = sorted(self.issues, key=lambda i: i.severity)
            for i, issue in enumerate(by_severity, 1):
                lines.append(
                    f"  {i}. [{issue.severity}] [{issue.component}] "
                    f"{issue.summary}"
                )
                if issue.details:
                    lines.append(f"     {issue.details[:150]}")
        else:
            lines.append("--- 未发现问题 ---")

        lines.append("")
        lines.append("=" * 60)
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典（可 JSON 导出）"""
        return {
            "test_case": self.test_case,
            "mode": self.mode,
            "total_elapsed_s": round(self.end_time - self.start_time, 2) if self.end_time else 0,
            "total_tokens": self.total_tokens,
            "exit_reason": self.exit_reason,
            "final_success": self.final_success,
            "planning": {
                "elapsed_s": self.planning_elapsed_s,
                "tasks_count": self.planning_tasks_count,
                "error": self.planning_error,
            },
            "sandbox": {
                "available": self.sandbox_available,
                "container": self.sandbox_container,
                "error": self.sandbox_error,
            },
            "iterations": [
                {
                    "iteration": m.iteration,
                    "phase": m.phase,
                    "task_id": m.task_id,
                    "success": m.success,
                    "error": m.error,
                    "tokens_used": m.tokens_used,
                    "elapsed_s": m.elapsed_s,
                    "files_changed": m.files_changed,
                }
                for m in self.iterations
            ],
            "state_checks": [
                {"name": sc.check_name, "passed": sc.passed, "details": sc.details}
                for sc in self.state_checks
            ],
            "phase_transitions": [
                {"from": f, "to": t, "reason": r}
                for f, t, r in self.phase_transitions
            ],
            "issues": [
                {
                    "severity": i.severity, "component": i.component,
                    "summary": i.summary, "details": i.details,
                }
                for i in self.issues
            ],
        }

    def save_json(self, path: str):
        """保存 JSON 报告到文件"""
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        logger.info(f"诊断报告已保存: {path}")
