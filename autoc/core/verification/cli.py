"""CLI 验证协议 — 命令行应用的验收测试执行"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from .protocol import VerificationProtocol, VerifyEvidence, VerifyResult
from ._semantic import is_natural_language, llm_semantic_check

if TYPE_CHECKING:
    from autoc.core.project.models import AcceptanceTest

logger = logging.getLogger("autoc.verification.cli")


class CLIProtocol(VerificationProtocol):
    """CLI 应用验证 — 执行命令检查 stdout/exitcode

    适用于 domain='cli' 的验收测试。

    expected 字段处理策略:
    - 精确片段（如 "ok", "200"）: 严格子串匹配
    - 自然语言描述（如 "列表中出现新条目"）: 委托 LLM 做 stdout vs expected 语义匹配
    """

    def can_handle(self, domain: str, workspace_dir: str) -> bool:
        return domain == "cli"

    def execute(
        self,
        test: "AcceptanceTest",
        workspace_dir: str,
        shell=None,
        **kwargs,
    ) -> VerifyResult:
        if shell is None:
            return VerifyResult(
                description=test.description,
                passed=True,
                error="shell 不可用，跳过 CLI 验证",
                evidence=VerifyEvidence(diagnosis="shell_unavailable"),
            )

        outputs = []
        has_exec_error = False
        for action in (test.actions or []):
            try:
                out = shell.execute(action, timeout=30)
                outputs.append(f"$ {action}\n{out}")
            except Exception as e:
                has_exec_error = True
                outputs.append(f"$ {action}\n[ERROR] {e}")

        combined = "\n".join(outputs)

        concrete_failed: list[str] = []
        semantic_failed: list[str] = []
        llm = kwargs.get("llm")

        for exp in (test.expected or []):
            if not exp.strip():
                continue
            if is_natural_language(exp):
                # LLM 语义匹配：stdout 是否满足自然语言期望
                if llm and not llm_semantic_check(llm, combined[:800], exp):
                    semantic_failed.append(exp)
            elif exp.strip() not in combined:
                concrete_failed.append(exp)

        all_passed = not concrete_failed and not semantic_failed and not has_exec_error

        diagnosis_parts = []
        if concrete_failed:
            diagnosis_parts.append(f"输出中缺少: {', '.join(concrete_failed[:3])}")
        if semantic_failed:
            diagnosis_parts.append(
                f"语义不匹配: {'; '.join(semantic_failed[:2])}"
            )
        if has_exec_error:
            diagnosis_parts.append("命令执行出错（见 raw_output）")

        return VerifyResult(
            description=test.description,
            passed=all_passed,
            evidence=VerifyEvidence(
                raw_output=combined[:1000],
                diagnosis="; ".join(diagnosis_parts),
            ),
        )
