"""Security Analyzer — 基于 Tool Annotations 的零开销安全评估

参考 OpenHands Security Analyzer 设计：
- 每次工具调用前，基于 annotations + 参数内容做安全评估
- 零 LLM 开销：纯规则引擎，不消耗 token
- 可插拔确认策略：sandbox（全自动）/ cautious（高风险需确认）/ strict（全部需确认）
- 命令内容分析：对 execute_command 做更细粒度的风险评估

处置决策：
- ALLOW: 直接执行，不记录
- ALLOW_WITH_LOG: 直接执行，记录到安全日志
- WARN: 执行但发出警告事件
- DENY: 拒绝执行，返回错误信息
"""

import logging
import re
from dataclasses import dataclass, field
from enum import Enum

from autoc.tools.annotations import (
    ToolAnnotation, RiskLevel, ConfirmAction,
    get_annotation, is_high_risk,
)

logger = logging.getLogger("autoc.security")


class ConfirmationPolicy(str, Enum):
    """安全确认策略"""
    SANDBOX = "sandbox"
    CAUTIOUS = "cautious"
    STRICT = "strict"


class Decision(str, Enum):
    ALLOW = "allow"
    ALLOW_WITH_LOG = "allow_with_log"
    WARN = "warn"
    DENY = "deny"


@dataclass
class SecurityDecision:
    """安全评估结果"""
    decision: Decision
    tool_name: str
    risk_level: RiskLevel
    reason: str = ""
    matched_pattern: str = ""

    @property
    def allowed(self) -> bool:
        return self.decision in (Decision.ALLOW, Decision.ALLOW_WITH_LOG, Decision.WARN)


# Shell 命令内容的细粒度风险模式
_SHELL_RISK_PATTERNS: list[tuple[str, RiskLevel, str]] = [
    # critical: 绝对不允许（仅删除根目录本身才是 CRITICAL，删除其他绝对路径降为 HIGH）
    (r"rm\s+(-[a-z]*r[a-z]*f|-[a-z]*f[a-z]*r|--force|--recursive).*\s+/\s*$", RiskLevel.CRITICAL, "删除根目录"),
    (r"rm\s+-rf\s+/\s*$", RiskLevel.CRITICAL, "删除根目录（短选项）"),
    (r"mkfs", RiskLevel.CRITICAL, "格式化文件系统"),
    (r"dd\s+(if|of)=", RiskLevel.CRITICAL, "磁盘原始读写"),
    (r":\(\)\s*\{.*\}", RiskLevel.CRITICAL, "Fork Bomb"),
    (r"chmod\s+(-[a-zA-Z]*R|-R|-recursive)\s+777\s+/", RiskLevel.CRITICAL, "修改根目录权限"),
    (r"(shutdown|reboot|init\s+[06]|systemctl\s+(poweroff|halt|reboot))", RiskLevel.CRITICAL, "系统关机/重启"),

    # 命令替换/注入（$() 和 `` 反引号）
    (r"\$\(.*\)", RiskLevel.HIGH, "命令替换 $(...)"),
    (r"`[^`]+`", RiskLevel.HIGH, "命令替换反引号"),

    # high: 需要特别关注
    (r"curl\s+.*\|\s*(bash|sh)", RiskLevel.HIGH, "远程脚本执行"),
    (r"wget\s+.*\|\s*(bash|sh)", RiskLevel.HIGH, "远程脚本执行"),
    (r"rm\s+(-[a-z]*r[a-z]*f|-[a-z]*f[a-z]*r)\s", RiskLevel.HIGH, "递归强制删除（长/短选项）"),
    (r"rm\s+-rf\s", RiskLevel.HIGH, "递归强制删除"),
    (r"pip\s+install\s+.*(--index-url|--extra-index-url|--find-links)\s", RiskLevel.HIGH, "非标准 pip 源"),
    (r"npm\s+install\s+.*--registry\s", RiskLevel.MEDIUM, "非标准 npm 源"),
    (r"\beval\s+\S|\beval\(", RiskLevel.HIGH, "动态代码执行"),
    (r"\bexec\s+\S|\bexec\(", RiskLevel.HIGH, "进程替换"),
    # 环境变量篡改危险路径
    (r"(PATH|LD_PRELOAD|LD_LIBRARY_PATH)\s*=", RiskLevel.HIGH, "环境变量篡改"),

    # medium: 正常但需记录
    (r"pip\s+install", RiskLevel.MEDIUM, "安装 Python 包"),
    (r"npm\s+install", RiskLevel.MEDIUM, "安装 Node 包"),
    (r"apt(-get)?\s+install", RiskLevel.MEDIUM, "安装系统包"),
    (r"git\s+push", RiskLevel.MEDIUM, "Git 推送"),
    (r"git\s+reset\s+--hard", RiskLevel.HIGH, "Git 硬重置"),

    # low: 常规命令
    (r"python\s", RiskLevel.LOW, "执行 Python"),
    (r"node\s", RiskLevel.LOW, "执行 Node.js"),
    (r"pytest", RiskLevel.LOW, "运行测试"),
    (r"curl\s", RiskLevel.LOW, "HTTP 请求"),
    (r"test\s+-[fde]", RiskLevel.NONE, "文件检查"),
]

_COMPILED_PATTERNS = [
    (re.compile(pattern, re.IGNORECASE), level, desc)
    for pattern, level, desc in _SHELL_RISK_PATTERNS
]


class SecurityAnalyzer:
    """工具调用安全评估器

    在工具执行前调用 evaluate()，根据 annotations + 参数内容返回处置决策。
    全程零 LLM 消耗。

    典型用法：
        analyzer = SecurityAnalyzer(policy=ConfirmationPolicy.SANDBOX)
        decision = analyzer.evaluate("execute_command", {"command": "pip install flask"})
        if decision.allowed:
            result = registry.dispatch(tool_name, arguments)
        else:
            result = f"[安全] 拒绝: {decision.reason}"
    """

    def __init__(self, policy: ConfirmationPolicy = ConfirmationPolicy.SANDBOX):
        self._policy = policy
        self._stats = SecurityStats()

    def evaluate(self, tool_name: str, arguments: dict) -> SecurityDecision:
        """评估工具调用的安全性"""
        annotation = get_annotation(tool_name)

        if tool_name == "execute_command":
            command = arguments.get("command", "")
            decision = self._evaluate_shell_command(command, annotation)
        else:
            decision = self._evaluate_by_annotation(tool_name, annotation)

        self._stats.record(decision)
        if decision.decision == Decision.DENY:
            logger.warning(
                f"安全拒绝: {tool_name} — {decision.reason} "
                f"(risk={decision.risk_level.value})"
            )
        elif decision.decision == Decision.WARN:
            logger.info(
                f"安全警告: {tool_name} — {decision.reason} "
                f"(risk={decision.risk_level.value})"
            )

        return decision

    _RISK_ORDER = {
        RiskLevel.NONE: 0, RiskLevel.LOW: 1, RiskLevel.MEDIUM: 2,
        RiskLevel.HIGH: 3, RiskLevel.CRITICAL: 4,
    }

    def _evaluate_shell_command(
        self, command: str, annotation: ToolAnnotation,
    ) -> SecurityDecision:
        """Shell 命令的细粒度安全评估 — 遍历全部模式取最高风险"""
        cmd_lower = command.lower().strip()

        highest_level: RiskLevel | None = None
        highest_desc = ""
        highest_pattern = ""

        for pattern, level, desc in _COMPILED_PATTERNS:
            if pattern.search(cmd_lower):
                if level == RiskLevel.CRITICAL:
                    return SecurityDecision(
                        decision=Decision.DENY,
                        tool_name="execute_command",
                        risk_level=RiskLevel.CRITICAL,
                        reason=f"危险命令: {desc}",
                        matched_pattern=pattern.pattern,
                    )
                if highest_level is None or self._RISK_ORDER[level] > self._RISK_ORDER[highest_level]:
                    highest_level = level
                    highest_desc = desc
                    highest_pattern = pattern.pattern

        if highest_level is not None:
            action = self._policy_action(highest_level)
            return SecurityDecision(
                decision=action,
                tool_name="execute_command",
                risk_level=highest_level,
                reason=f"高风险命令: {highest_desc}" if highest_level == RiskLevel.HIGH else highest_desc,
                matched_pattern=highest_pattern,
            )

        return SecurityDecision(
            decision=self._policy_action(RiskLevel.MEDIUM),
            tool_name="execute_command",
            risk_level=RiskLevel.MEDIUM,
            reason="未匹配的 Shell 命令",
        )

    def _evaluate_by_annotation(
        self, tool_name: str, annotation: ToolAnnotation,
    ) -> SecurityDecision:
        """基于 annotation 的通用安全评估"""
        if annotation.readonly:
            return SecurityDecision(
                decision=Decision.ALLOW,
                tool_name=tool_name,
                risk_level=RiskLevel.NONE,
                reason="只读操作",
            )

        if annotation.risk_level == RiskLevel.CRITICAL:
            return SecurityDecision(
                decision=Decision.DENY,
                tool_name=tool_name,
                risk_level=RiskLevel.CRITICAL,
                reason=annotation.description or "极高风险操作",
            )

        action = self._policy_action(annotation.risk_level)
        return SecurityDecision(
            decision=action,
            tool_name=tool_name,
            risk_level=annotation.risk_level,
            reason=annotation.description,
        )

    def _policy_action(self, risk_level: RiskLevel) -> Decision:
        """根据策略和风险等级决定处置方式"""
        if self._policy == ConfirmationPolicy.SANDBOX:
            if risk_level == RiskLevel.CRITICAL:
                return Decision.DENY
            if risk_level == RiskLevel.HIGH:
                return Decision.WARN
            return Decision.ALLOW_WITH_LOG

        if self._policy == ConfirmationPolicy.CAUTIOUS:
            if risk_level == RiskLevel.CRITICAL:
                return Decision.DENY
            if risk_level in (RiskLevel.HIGH, RiskLevel.MEDIUM):
                return Decision.WARN  # CAUTIOUS 对 MEDIUM 风险也发出警告
            return Decision.ALLOW_WITH_LOG

        # strict
        if risk_level in (RiskLevel.NONE,):
            return Decision.ALLOW
        if risk_level == RiskLevel.CRITICAL:
            return Decision.DENY
        return Decision.WARN

    @property
    def stats(self) -> "SecurityStats":
        return self._stats

    @property
    def policy(self) -> ConfirmationPolicy:
        return self._policy


@dataclass
class SecurityStats:
    """安全评估统计"""
    total_evaluations: int = 0
    allowed: int = 0
    warned: int = 0
    denied: int = 0
    by_risk: dict = field(default_factory=lambda: {
        "none": 0, "low": 0, "medium": 0, "high": 0, "critical": 0,
    })

    def record(self, decision: SecurityDecision) -> None:
        self.total_evaluations += 1
        self.by_risk[decision.risk_level.value] = (
            self.by_risk.get(decision.risk_level.value, 0) + 1
        )
        if decision.decision == Decision.DENY:
            self.denied += 1
        elif decision.decision == Decision.WARN:
            self.warned += 1
        else:
            self.allowed += 1

    def summary(self) -> str:
        return (
            f"Security: {self.total_evaluations} evals, "
            f"{self.allowed} allowed, {self.warned} warned, {self.denied} denied | "
            f"Risk: {self.by_risk}"
        )
