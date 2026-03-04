"""验收驱动架构 — Verification 模块

验证层级:
  L1 verification_steps  — shell 命令结构验证（已有）
  L2 acceptance_tests    — 行为级验收测试（本模块新增）
  L3 judge_task_completion — LLM-as-Judge 任务守门员（P0 最高优先级）

使用方式:
    # P0: 任务完成后的 LLM 守门员
    from autoc.core.verification import judge_task_completion
    result = judge_task_completion(llm, task_title, ..., changed_files, workspace_dir)

    # P1/P2: 运行 acceptance_tests
    from autoc.core.verification import VerificationRunner
    runner = VerificationRunner(llm=orc.llm_critique, shell=orc.shell)
    results = runner.run_task_tests(task, workspace_dir)
"""

from .protocol import VerificationProtocol, VerifyResult, VerifyEvidence
from .judge import LLMJudgeProtocol, JudgeResult, judge_task_completion
from .runner import VerificationRunner
from .browser import BrowserProtocol
from .cli import CLIProtocol
from .api import APIProtocol

__all__ = [
    "VerificationProtocol",
    "VerifyResult",
    "VerifyEvidence",
    "LLMJudgeProtocol",
    "JudgeResult",
    "judge_task_completion",
    "VerificationRunner",
    "BrowserProtocol",
    "CLIProtocol",
    "APIProtocol",
]
