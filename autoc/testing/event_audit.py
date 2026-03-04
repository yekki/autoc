"""SSE 事件契约测试 — 验证前后端事件对齐

基于 Mock Agent 录制的完整事件序列，逐条验证：
1. 前端期望的事件是否至少出现一次
2. 每个事件的 data 字段是否包含前端需要的 key
3. 事件时序是否合法（如 task_start 必须在 task_complete 之前）
4. user_message 和 available_actions 是否非空（enricher 是否生效）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger("autoc.testing.event_audit")

# ── 前端事件契约：前端期望接收的事件类型及其必需字段 ──

FRONTEND_EVENT_CONTRACT: dict[str, list[str]] = {
    # 基础流程
    "sandbox_preparing": ["step", "message", "progress"],
    "sandbox_ready": ["message"],
    "planning_analyzing": ["message"],
    "planning_progress": ["step", "message"],
    "phase_start": ["phase"],
    "plan_ready": ["tasks"],
    "execution_start": ["task_count"],
    "loop_start": ["max_iterations"],
    "iteration_start": ["iteration", "phase"],
    "iteration_done": ["iteration"],
    "task_start": ["task_id"],
    "task_complete": ["task_id"],
    "task_verified": ["task_id", "passes"],
    "file_created": [],
    "test_result": [],
    "preview_ready": [],
    "execution_failed": ["failure_reason"],
    "token_session": [],
    "summary": [],
    "error": ["message"],
    "done": ["success"],

    # 之前的"沉默事件"（现已补齐消费）
    "complexity_assessed": ["complexity"],
    "dev_self_test": ["task_id", "passed"],
    "smoke_check_failed": ["issues"],
    "deploy_gate": ["status"],
    "failure_analysis": ["mode", "strategy"],
    "bug_fix_start": ["count"],
    "reflection": ["content"],
    "planning_review": ["status"],
    "planning_acceptance": ["passed"],
    "planning_decision": ["action"],

    # enricher 增强字段（所有事件都应该有）
    # 这些不在此处硬编码，而是通过 enricher_check 统一验证
}

# ── 事件时序约束 ──

TEMPORAL_CONSTRAINTS: list[tuple[str, str]] = [
    ("sandbox_preparing", "sandbox_ready"),
    ("plan_ready", "task_start"),
    ("task_start", "task_complete"),
    ("execution_start", "done"),
]


@dataclass
class AuditIssue:
    severity: str  # "error" | "warning"
    category: str  # "missing" | "field" | "temporal" | "enricher"
    message: str


@dataclass
class EventAuditReport:
    events_recorded: int = 0
    events_by_type: dict[str, int] = field(default_factory=dict)
    issues: list[AuditIssue] = field(default_factory=list)
    coverage: float = 0.0

    @property
    def passed(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)

    def render(self) -> str:
        lines = [
            "=" * 60,
            "  SSE 事件契约审计报告",
            "=" * 60,
            f"  录制事件总数: {self.events_recorded}",
            f"  事件类型覆盖: {self.coverage:.0%} "
            f"({len(self.events_by_type)}/{len(FRONTEND_EVENT_CONTRACT)})",
            f"  结果: {'✅ PASS' if self.passed else '❌ FAIL'}",
            "",
        ]

        if self.events_by_type:
            lines.append("  事件分布:")
            for etype, count in sorted(self.events_by_type.items()):
                lines.append(f"    {etype}: {count}")
            lines.append("")

        if self.issues:
            errors = [i for i in self.issues if i.severity == "error"]
            warnings = [i for i in self.issues if i.severity == "warning"]
            if errors:
                lines.append(f"  错误 ({len(errors)}):")
                for i in errors:
                    lines.append(f"    ❌ [{i.category}] {i.message}")
            if warnings:
                lines.append(f"  警告 ({len(warnings)}):")
                for i in warnings:
                    lines.append(f"    ⚠️ [{i.category}] {i.message}")
        else:
            lines.append("  无问题")

        lines.append("=" * 60)
        return "\n".join(lines)


def audit_events(events: list[dict]) -> EventAuditReport:
    """对录制的事件序列执行完整的契约审计"""
    report = EventAuditReport(events_recorded=len(events))

    type_counts: dict[str, int] = {}
    type_first_seq: dict[str, int] = {}

    for idx, event in enumerate(events):
        etype = event.get("type", "")
        if not etype or etype == "heartbeat":
            continue
        type_counts[etype] = type_counts.get(etype, 0) + 1
        if etype not in type_first_seq:
            type_first_seq[etype] = idx

        data = event.get("data") or {}

        # 字段完整性检查
        required_fields = FRONTEND_EVENT_CONTRACT.get(etype)
        if required_fields is not None:
            for f in required_fields:
                if f not in data:
                    report.issues.append(AuditIssue(
                        severity="error",
                        category="field",
                        message=f"事件 {etype}[seq={idx}] 缺少字段 '{f}'",
                    ))

        # enricher 检查：user_message 和 available_actions 应存在
        if etype in FRONTEND_EVENT_CONTRACT:
            if "user_message" not in data:
                report.issues.append(AuditIssue(
                    severity="warning",
                    category="enricher",
                    message=f"事件 {etype}[seq={idx}] 缺少 user_message（enricher 未生效）",
                ))
            if "available_actions" not in data:
                report.issues.append(AuditIssue(
                    severity="warning",
                    category="enricher",
                    message=f"事件 {etype}[seq={idx}] 缺少 available_actions",
                ))

    report.events_by_type = type_counts

    # 覆盖率：前端契约中有多少事件类型至少出现了一次
    covered = sum(1 for et in FRONTEND_EVENT_CONTRACT if et in type_counts)
    report.coverage = covered / len(FRONTEND_EVENT_CONTRACT) if FRONTEND_EVENT_CONTRACT else 0

    # 缺失事件检查（分为必须 / 可选）
    critical_events = {
        "sandbox_preparing", "sandbox_ready", "phase_start", "plan_ready",
        "task_start", "task_complete", "done",
    }
    for etype in FRONTEND_EVENT_CONTRACT:
        if etype not in type_counts:
            severity = "error" if etype in critical_events else "warning"
            report.issues.append(AuditIssue(
                severity=severity,
                category="missing",
                message=f"前端期望的事件 '{etype}' 未出现",
            ))

    # 时序约束检查
    for before, after in TEMPORAL_CONSTRAINTS:
        before_seq = type_first_seq.get(before)
        after_seq = type_first_seq.get(after)
        if before_seq is not None and after_seq is not None:
            if before_seq > after_seq:
                report.issues.append(AuditIssue(
                    severity="error",
                    category="temporal",
                    message=f"时序违规: '{before}'(seq={before_seq}) 应在 "
                            f"'{after}'(seq={after_seq}) 之前",
                ))

    return report
