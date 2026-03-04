"""BaseCritic — 可插拔评审框架

设计：
  - BaseCritic 定义评审接口：evaluate(context) → CriticResult
  - CriticResult 统一评审结果：score + passed + issues + metadata
  - CompositeCritic 组合多个 Critic 的评审结果（加权平均）
  - CritiqueAgent 使用 Critic 框架替代硬编码评审逻辑

内置 Critic：
  - CodeQualityCritic: 代码质量评审（可读性/错误处理/类型标注）
  - SecurityCritic: 安全漏洞扫描（硬编码密钥/SQL 注入/路径穿越）
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("autoc.critic")


@dataclass
class CriticIssue:
    """评审问题"""
    file_path: str
    severity: str  # critical / high / medium / low
    category: str
    description: str
    line_number: int = 0
    suggestion: str = ""


@dataclass
class CriticResult:
    """评审结果"""
    critic_name: str
    score: float  # 0.0 ~ 1.0
    passed: bool
    issues: list[CriticIssue] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def score_100(self) -> int:
        return round(self.score * 100)


@dataclass
class CriticContext:
    """评审上下文 — 传递给 Critic 的输入数据"""
    task_id: str = ""
    task_title: str = ""
    task_description: str = ""
    files: dict[str, str] = field(default_factory=dict)
    git_patch: str = ""
    test_output: str = ""
    requirement: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseCritic(ABC):
    """评审器基类"""

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    def weight(self) -> float:
        """在 CompositeCritic 中的权重（默认 1.0）"""
        return 1.0

    @abstractmethod
    def evaluate(self, context: CriticContext) -> CriticResult:
        """执行评审"""
        ...


class CompositeCritic:
    """组合多个 Critic，加权聚合评审结果"""

    def __init__(self, critics: list[BaseCritic] | None = None, pass_threshold: float = 0.85):
        self._critics: list[BaseCritic] = critics or []
        self._pass_threshold = pass_threshold

    def add(self, critic: BaseCritic) -> "CompositeCritic":
        self._critics.append(critic)
        return self

    def evaluate(self, context: CriticContext) -> CriticResult:
        """运行所有 Critic 并聚合结果"""
        if not self._critics:
            return CriticResult(critic_name="composite", score=1.0, passed=True)

        results: list[CriticResult] = []
        all_issues: list[CriticIssue] = []

        for critic in self._critics:
            try:
                result = critic.evaluate(context)
                results.append(result)
                all_issues.extend(result.issues)
                logger.debug(
                    f"Critic '{critic.name}': score={result.score_100}/100, "
                    f"issues={len(result.issues)}"
                )
            except Exception as e:
                logger.error(f"Critic '{critic.name}' 执行失败: {e}")
                results.append(CriticResult(
                    critic_name=critic.name, score=0.5, passed=True,
                    metadata={"error": str(e)},
                ))

        total_weight = sum(c.weight for c in self._critics)
        if total_weight == 0:
            weighted_score = 0.0
        else:
            weighted_score = sum(
                r.score * c.weight for r, c in zip(results, self._critics)
            ) / total_weight

        passed = weighted_score >= self._pass_threshold
        has_critical = any(i.severity == "critical" for i in all_issues)
        if has_critical:
            passed = False

        return CriticResult(
            critic_name="composite",
            score=weighted_score,
            passed=passed,
            issues=all_issues,
            metadata={
                "individual_results": {r.critic_name: r.score_100 for r in results},
                "pass_threshold": self._pass_threshold,
                "has_critical_issue": has_critical,
            },
        )

    @property
    def critics(self) -> list[BaseCritic]:
        return list(self._critics)


class CodeQualityCritic(BaseCritic):
    """代码质量评审 — 基于静态规则检查"""

    _PATTERNS = [
        (r"except\s*:", "bare except（应捕获具体异常）", "medium"),
        (r"# ?TODO", "未完成的 TODO 标记", "low"),
        (r"print\(", "生产代码中的 print（应使用 logging）", "low"),
        (r"password\s*=\s*['\"]", "硬编码密码", "critical"),
        (r"api_key\s*=\s*['\"]", "硬编码 API Key", "critical"),
    ]

    @property
    def name(self) -> str:
        return "code_quality"

    def evaluate(self, context: CriticContext) -> CriticResult:
        import re
        issues: list[CriticIssue] = []
        total_lines = 0

        for file_path, content in context.files.items():
            lines = content.split("\n")
            total_lines += len(lines)
            for line_num, line in enumerate(lines, 1):
                for pattern, desc, severity in self._PATTERNS:
                    if re.search(pattern, line):
                        issues.append(CriticIssue(
                            file_path=file_path,
                            severity=severity,
                            category="code_quality",
                            description=desc,
                            line_number=line_num,
                        ))

        issue_penalty = sum(
            {"critical": 0.15, "high": 0.08, "medium": 0.03, "low": 0.01}.get(i.severity, 0)
            for i in issues
        )
        score = max(0.0, 1.0 - issue_penalty)

        return CriticResult(
            critic_name=self.name,
            score=score,
            passed=score >= 0.7,
            issues=issues,
            metadata={"total_lines": total_lines},
        )


class SecurityCritic(BaseCritic):
    """安全评审 — 检测常见安全漏洞"""

    _SECURITY_PATTERNS = [
        (r"eval\(", "使用 eval（代码注入风险）", "critical"),
        (r"exec\(", "使用 exec（代码注入风险）", "high"),
        (r"os\.system\(", "使用 os.system（应使用 subprocess）", "high"),
        (r"shell\s*=\s*True", "subprocess shell=True（命令注入风险）", "high"),
        (r"SELECT.*\+.*['\"]\s*\+", "字符串拼接 SQL（SQL 注入风险）", "critical"),
        (r"\.\./\.\./", "路径穿越模式", "high"),
    ]

    @property
    def name(self) -> str:
        return "security"

    @property
    def weight(self) -> float:
        return 1.5

    def evaluate(self, context: CriticContext) -> CriticResult:
        import re
        issues: list[CriticIssue] = []

        for file_path, content in context.files.items():
            lines = content.split("\n")
            for line_num, line in enumerate(lines, 1):
                for pattern, desc, severity in self._SECURITY_PATTERNS:
                    if re.search(pattern, line):
                        issues.append(CriticIssue(
                            file_path=file_path,
                            severity=severity,
                            category="security",
                            description=desc,
                            line_number=line_num,
                        ))

        critical_count = sum(1 for i in issues if i.severity == "critical")
        high_count = sum(1 for i in issues if i.severity == "high")
        score = max(0.0, 1.0 - critical_count * 0.3 - high_count * 0.1)

        return CriticResult(
            critic_name=self.name,
            score=score,
            passed=critical_count == 0 and score >= 0.6,
            issues=issues,
        )
