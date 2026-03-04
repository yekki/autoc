"""RequirementRefiner 单元测试

覆盖：质量评估（纯规则）/ refine 主流程 / 模式切换 / 澄清判断
"""

from unittest.mock import MagicMock, patch

import pytest

from autoc.core.analysis.refiner import RequirementRefiner
from autoc.core.project.models import QualityScore, RefinedRequirement


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.total_tokens = 0
    llm.chat.return_value = {"content": "enhanced requirement text"}
    return llm


@pytest.fixture
def refiner(mock_llm):
    return RequirementRefiner(mock_llm, mode="auto")


# ======================= assess_quality（纯规则，无 LLM） =======================


class TestAssessQuality:

    def test_short_requirement_low_score(self, refiner):
        quality = refiner.assess_quality("做app")
        assert quality.score < 0.5
        assert quality.level == "low"
        assert any(i.category == "vague" for i in quality.issues)

    def test_good_requirement_high_score(self, refiner):
        quality = refiner.assess_quality(
            "创建一个基于 Python Flask 的 RESTful API 服务，"
            "实现用户注册、登录和 JWT Token 认证功能，"
            "使用 SQLite 存储用户数据，不需要前端界面"
        )
        assert quality.score >= 0.7
        assert quality.level == "high"
        assert quality.has_clear_goal is True
        assert quality.has_tech_context is True

    def test_medium_requirement(self, refiner):
        quality = refiner.assess_quality("开发一个简单的 Todo 应用，支持增删改查")
        assert quality.score >= 0.5
        assert quality.has_clear_goal is True

    def test_tech_mention_in_text_boosts_score(self, refiner):
        """需求文本中提及技术栈时，评分更高"""
        without = refiner.assess_quality("创建一个博客系统")
        with_tech = refiner.assess_quality("用 python flask 创建一个博客系统")
        assert with_tech.score >= without.score

    def test_very_long_requirement_flags_too_broad(self, refiner):
        long_req = "实现一个完整的电商平台，" * 100
        quality = refiner.assess_quality(long_req)
        assert any(i.category == "too_broad" for i in quality.issues)


# ======================= refine 主流程 =======================


class TestRefine:

    def test_off_mode_passthrough(self, mock_llm):
        refiner = RequirementRefiner(mock_llm, mode="off")
        result = refiner.refine("做个网站")
        assert result.skipped is True
        assert result.refined == "做个网站"
        mock_llm.chat.assert_not_called()

    def test_high_quality_skips_enhance(self, mock_llm):
        refiner = RequirementRefiner(mock_llm, mode="auto", quality_threshold_high=0.5)
        good_req = (
            "创建一个基于 Python Flask 的 RESTful API，"
            "实现用户注册登录和 JWT 认证，使用 SQLite 数据库，不需要前端"
        )
        result = refiner.refine(good_req)
        assert result.skipped is True
        mock_llm.chat.assert_not_called()

    def test_low_quality_triggers_enhance(self, mock_llm):
        """质量低于阈值时，触发 _enhance 调用"""
        refiner = RequirementRefiner(mock_llm, mode="auto", quality_threshold_high=0.99)
        with patch.object(refiner, "_enhance") as mock_enhance:
            mock_enhance.return_value = RefinedRequirement(
                original="做app", refined="enhanced app requirement",
                enhancements=["补充了技术栈"],
            )
            result = refiner.refine("做app")
        assert not result.skipped
        assert result.refined == "enhanced app requirement"
        mock_enhance.assert_called_once()

    def test_enhance_failure_falls_back(self, mock_llm):
        """_enhance 异常时回退到原始需求"""
        refiner = RequirementRefiner(mock_llm, mode="auto", quality_threshold_high=0.99)
        with patch.object(refiner, "_enhance", side_effect=Exception("LLM error")):
            result = refiner.refine("做app")
        assert result.skipped is True
        assert result.refined == "做app"

    def test_enhance_mode_forces_enhancement(self, mock_llm):
        """mode=enhance 即使质量高也强制增强"""
        refiner = RequirementRefiner(mock_llm, mode="enhance")
        with patch.object(refiner, "_enhance") as mock_enhance:
            mock_enhance.return_value = RefinedRequirement(
                original="good req", refined="better req",
            )
            result = refiner.refine(
                "创建一个 Python Flask API，实现 JWT 认证，使用 SQLite，不需要前端"
            )
        mock_enhance.assert_called_once()

    def test_emits_quality_event(self, mock_llm):
        """refine 过程中发出 refiner_quality 事件"""
        refiner = RequirementRefiner(mock_llm, mode="auto")
        events = []
        refiner.refine("做app", on_event=lambda e: events.append(e))
        assert any(e["type"] == "refiner_quality" for e in events)


# ======================= needs_clarification =======================


class TestNeedsClarification:

    def test_off_mode_always_false(self, mock_llm):
        refiner = RequirementRefiner(mock_llm, mode="off")
        assert refiner.needs_clarification("x") is False

    def test_very_short_needs_clarification(self, mock_llm):
        refiner = RequirementRefiner(mock_llm, mode="auto", quality_threshold_low=0.4)
        assert refiner.needs_clarification("做") is True

    def test_good_requirement_no_clarification(self, mock_llm):
        refiner = RequirementRefiner(mock_llm, mode="auto", quality_threshold_low=0.3)
        assert refiner.needs_clarification(
            "创建一个 Python Flask REST API 实现用户认证"
        ) is False


# ======================= merge_clarification（静态方法） =======================


class TestMergeClarification:

    def test_merges_answers(self):
        result = RequirementRefiner.merge_clarification(
            "做个网站",
            ["目标是什么?", "技术栈?"],
            ["学习项目", "React"],
        )
        assert "做个网站" in result
        assert "React" in result
        assert "学习项目" in result
