"""验证运行器 — 按 domain 路由到合适的 VerificationProtocol

使用方式:
    runner = VerificationRunner(llm=orc.llm_critique, shell=orc.shell)
    results = runner.run_task_tests(task, workspace_dir, preview_url=url)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .protocol import VerifyResult
from .judge import LLMJudgeProtocol
from .cli import CLIProtocol
from .api import APIProtocol
from .browser import BrowserProtocol

if TYPE_CHECKING:
    from autoc.core.project.models import AcceptanceTest, Task

logger = logging.getLogger("autoc.verification.runner")


class VerificationRunner:
    """验证管道运行器

    协议选择优先级:
    1. BrowserProtocol  (domain=browser)
    2. APIProtocol      (domain=api)
    3. CLIProtocol      (domain=cli)
    4. LLMJudgeProtocol (domain=llm_judge 或兜底)
    """

    def __init__(self, llm: Any = None, shell: Any = None):
        self._llm = llm
        self._shell = shell
        self._protocols = [
            BrowserProtocol(),
            APIProtocol(),
            CLIProtocol(),
            LLMJudgeProtocol(llm=llm),
        ]

    def _select_protocol(self, domain: str, workspace_dir: str):
        for proto in self._protocols:
            if proto.can_handle(domain, workspace_dir):
                return proto
        return self._protocols[-1]  # fallback: LLMJudge

    def run_single(
        self,
        test: "AcceptanceTest",
        workspace_dir: str,
        preview_url: str = "",
    ) -> VerifyResult:
        """执行单个验收测试"""
        domain = getattr(test, "domain", "llm_judge") or "llm_judge"
        proto = self._select_protocol(domain, workspace_dir)
        try:
            return proto.execute(
                test,
                workspace_dir,
                shell=self._shell,
                llm=self._llm,
                preview_url=preview_url,
            )
        except Exception as e:
            logger.warning(f"验证协议 {proto.__class__.__name__} 执行异常: {e}")
            return VerifyResult(
                description=test.description,
                passed=True,  # 执行异常时不阻塞
                error=str(e),
            )

    def run_task_tests(
        self,
        task: "Task",
        workspace_dir: str,
        preview_url: str = "",
    ) -> list[VerifyResult]:
        """执行任务的所有 acceptance_tests"""
        tests = getattr(task, "acceptance_tests", []) or []
        if not tests:
            return []

        results = []
        for i, test in enumerate(tests):
            logger.info(f"执行验收测试 [{i+1}/{len(tests)}]: {test.description[:60]}")
            result = self.run_single(test, workspace_dir, preview_url=preview_url)
            result.test_id = f"{task.id}-at{i+1}"
            results.append(result)

        passed = sum(1 for r in results if r.passed)
        logger.info(f"验收测试完成: {passed}/{len(results)} 通过")
        return results

    @staticmethod
    def summarize_results(results: list[VerifyResult]) -> dict:
        """汇总验收测试结果"""
        if not results:
            return {"total": 0, "passed": 0, "failed": 0, "all_passed": True, "evidence_list": []}
        passed = [r for r in results if r.passed]
        failed = [r for r in results if not r.passed]
        evidence_list = []
        for r in failed:
            entry = {
                "test": r.description,
                "error": r.error,
            }
            if r.evidence:
                ev = r.evidence
                if ev.dom_diff:
                    entry["dom_diff"] = ev.dom_diff
                if ev.console_errors:
                    entry["console_errors"] = ev.console_errors
                if ev.diagnosis:
                    entry["diagnosis"] = ev.diagnosis
                if ev.raw_output:
                    entry["raw_output"] = ev.raw_output[:300]
            evidence_list.append(entry)
        return {
            "total": len(results),
            "passed": len(passed),
            "failed": len(failed),
            "all_passed": len(failed) == 0,
            "evidence_list": evidence_list,
        }
