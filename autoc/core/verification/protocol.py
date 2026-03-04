"""验证协议抽象层 — 验收驱动架构的核心接口

验证协议适配器将行为级 AcceptanceTest 翻译为可执行验证，
按 domain 路由到不同协议：browser / api / cli / llm_judge。
"""

from __future__ import annotations

import abc
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from autoc.core.project.models import AcceptanceTest


class VerifyEvidence(BaseModel):
    """验证过程产生的证据 — 用于精准的失败反馈"""
    raw_output: str = ""          # 命令/API 原始输出
    dom_diff: str = ""            # 浏览器场景：DOM 变化摘要
    console_errors: list[str] = Field(default_factory=list)   # JS 控制台错误
    screenshot_before: str = ""  # 操作前截图路径（沙箱内 /tmp/）
    screenshot_after: str = ""   # 操作后截图路径
    http_status: int = 0          # API 场景：HTTP 状态码
    response_body: str = ""       # API 场景：响应体
    diagnosis: str = ""           # 协议自动推断的失败诊断


class VerifyResult(BaseModel):
    """单个验收测试的执行结果"""
    test_id: str = ""
    description: str = ""
    passed: bool = False
    evidence: VerifyEvidence = Field(default_factory=VerifyEvidence)
    error: str = ""               # 执行异常（非断言失败）


class VerificationProtocol(abc.ABC):
    """验证协议基类 — 子类实现具体执行逻辑"""

    @abc.abstractmethod
    def can_handle(self, domain: str, workspace_dir: str) -> bool:
        """判断本协议是否能处理该 domain + 工作区组合"""

    @abc.abstractmethod
    def execute(
        self,
        test: "AcceptanceTest",
        workspace_dir: str,
        shell=None,
        **kwargs,
    ) -> VerifyResult:
        """执行单个验收测试，返回带证据的结果"""
