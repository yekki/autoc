"""API 验证协议 — HTTP 接口的验收测试执行"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from .protocol import VerificationProtocol, VerifyEvidence, VerifyResult
from ._semantic import is_natural_language, llm_semantic_check

if TYPE_CHECKING:
    from autoc.core.project.models import AcceptanceTest

logger = logging.getLogger("autoc.verification.api")

_HTTP_STATUS_RE = re.compile(r"\b([1-5]\d{2})\b")


class APIProtocol(VerificationProtocol):
    """API 服务验证 — 发 HTTP 请求验证响应

    适用于 domain='api' 的验收测试。
    actions 是 curl 命令或 "METHOD URL [body]" 格式。

    expected 字段处理策略:
    - 精确片段（如 '"id": 1', "200"）: 严格子串匹配
    - 自然语言描述: 委托 LLM 做 response vs expected 语义匹配
    """

    def can_handle(self, domain: str, workspace_dir: str) -> bool:
        return domain == "api"

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
                error="shell 不可用，跳过 API 验证",
                evidence=VerifyEvidence(diagnosis="shell_unavailable"),
            )

        outputs = []
        has_exec_error = False
        for action in (test.actions or []):
            cmd = action if action.strip().lower().startswith("curl") else f"curl -s {action}"
            try:
                out = shell.execute(cmd, timeout=15)
                outputs.append(f"$ {cmd}\n{out}")
            except Exception as e:
                has_exec_error = True
                outputs.append(f"$ {cmd}\n[ERROR] {e}")

        combined = "\n".join(outputs)

        http_status = 0
        m = _HTTP_STATUS_RE.search(combined)
        if m:
            http_status = int(m.group(1))

        concrete_failed: list[str] = []
        semantic_failed: list[str] = []
        llm = kwargs.get("llm")

        for exp in (test.expected or []):
            if not exp.strip():
                continue
            if is_natural_language(exp):
                if llm and not llm_semantic_check(llm, combined[:800], exp):
                    semantic_failed.append(exp)
            elif exp.strip() not in combined:
                concrete_failed.append(exp)

        has_http_error = 400 <= http_status < 600
        all_passed = (
            not concrete_failed and not semantic_failed
            and not has_exec_error and not has_http_error
        )

        diagnosis_parts = []
        if concrete_failed:
            diagnosis_parts.append(f"响应中缺少: {', '.join(concrete_failed[:3])}")
        if semantic_failed:
            diagnosis_parts.append(f"语义不匹配: {'; '.join(semantic_failed[:2])}")
        if has_exec_error:
            diagnosis_parts.append("curl 执行出错")
        if has_http_error:
            diagnosis_parts.append(f"HTTP {http_status} 错误")

        return VerifyResult(
            description=test.description,
            passed=all_passed,
            evidence=VerifyEvidence(
                raw_output=combined[:1000],
                http_status=http_status,
                response_body=combined[:500],
                diagnosis="; ".join(diagnosis_parts),
            ),
        )
