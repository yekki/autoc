"""Critic 可插拔框架测试"""

import pytest
from autoc.core.critic.base import (
    BaseCritic, CriticResult, CriticContext, CriticIssue,
    CompositeCritic, CodeQualityCritic, SecurityCritic,
)


class MockCritic(BaseCritic):
    def __init__(self, name: str, score: float, issues: list | None = None, weight: float = 1.0):
        self._name = name
        self._score = score
        self._issues = issues or []
        self._weight = weight

    @property
    def name(self) -> str:
        return self._name

    @property
    def weight(self) -> float:
        return self._weight

    def evaluate(self, context: CriticContext) -> CriticResult:
        return CriticResult(
            critic_name=self._name,
            score=self._score,
            passed=self._score >= 0.7,
            issues=self._issues,
        )


class TestCriticResult:
    def test_score_100(self):
        r = CriticResult(critic_name="test", score=0.85, passed=True)
        assert r.score_100 == 85

    def test_score_100_rounding(self):
        r = CriticResult(critic_name="test", score=0.867, passed=True)
        assert r.score_100 == 87


class TestCompositeCritic:
    def test_empty_critics(self):
        composite = CompositeCritic()
        result = composite.evaluate(CriticContext())
        assert result.passed
        assert result.score == 1.0

    def test_single_critic(self):
        composite = CompositeCritic([MockCritic("test", 0.9)])
        result = composite.evaluate(CriticContext())
        assert result.passed
        assert result.score == 0.9

    def test_weighted_average(self):
        composite = CompositeCritic([
            MockCritic("a", 1.0, weight=1.0),
            MockCritic("b", 0.5, weight=1.0),
        ])
        result = composite.evaluate(CriticContext())
        assert abs(result.score - 0.75) < 0.01

    def test_weighted_average_unequal(self):
        composite = CompositeCritic([
            MockCritic("a", 1.0, weight=2.0),
            MockCritic("b", 0.0, weight=1.0),
        ])
        result = composite.evaluate(CriticContext())
        assert abs(result.score - 0.667) < 0.01

    def test_critical_issue_forces_fail(self):
        issues = [CriticIssue(file_path="a.py", severity="critical", category="test", description="bad")]
        composite = CompositeCritic([MockCritic("test", 1.0, issues=issues)])
        result = composite.evaluate(CriticContext())
        assert not result.passed

    def test_pass_threshold(self):
        composite = CompositeCritic([MockCritic("test", 0.84)], pass_threshold=0.85)
        result = composite.evaluate(CriticContext())
        assert not result.passed

    def test_add_fluent_api(self):
        composite = CompositeCritic()
        composite.add(MockCritic("a", 0.9)).add(MockCritic("b", 0.8))
        assert len(composite.critics) == 2

    def test_individual_results_in_metadata(self):
        composite = CompositeCritic([
            MockCritic("quality", 0.9),
            MockCritic("security", 0.8),
        ])
        result = composite.evaluate(CriticContext())
        assert "individual_results" in result.metadata
        assert result.metadata["individual_results"]["quality"] == 90
        assert result.metadata["individual_results"]["security"] == 80


class TestCodeQualityCritic:
    def test_clean_code(self):
        ctx = CriticContext(files={"app.py": "import logging\nlogger = logging.getLogger()\n"})
        result = CodeQualityCritic().evaluate(ctx)
        assert result.score > 0.9
        assert result.passed

    def test_bare_except(self):
        ctx = CriticContext(files={"app.py": "try:\n    pass\nexcept:\n    pass\n"})
        result = CodeQualityCritic().evaluate(ctx)
        assert any(i.description == "bare except（应捕获具体异常）" for i in result.issues)

    def test_hardcoded_password(self):
        ctx = CriticContext(files={"config.py": 'password = "secret123"\n'})
        result = CodeQualityCritic().evaluate(ctx)
        critical_issues = [i for i in result.issues if i.severity == "critical"]
        assert len(critical_issues) > 0


class TestSecurityCritic:
    def test_eval_detected(self):
        ctx = CriticContext(files={"app.py": "result = eval(user_input)\n"})
        result = SecurityCritic().evaluate(ctx)
        assert not result.passed
        assert any("eval" in i.description for i in result.issues)

    def test_clean_code(self):
        ctx = CriticContext(files={"app.py": "import subprocess\nsubprocess.run(['ls'])\n"})
        result = SecurityCritic().evaluate(ctx)
        assert result.passed

    def test_weight_is_1_5(self):
        assert SecurityCritic().weight == 1.5
