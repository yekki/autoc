"""User Profile 单元测试"""
import os
import tempfile
import pytest
from autoc.core.infra.user_profile import UserProfileManager, UserPreference


@pytest.fixture
def tmp_profile():
    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
        path = f.name
    yield path
    if os.path.exists(path):
        os.unlink(path)


class TestUserProfileManager:
    """UserProfileManager 核心功能"""

    def test_record_tech_stack(self, tmp_profile):
        mgr = UserProfileManager(tmp_profile)
        mgr.record_tech_stack(["Python", "Flask"])
        mgr.record_tech_stack(["Python", "FastAPI"])

        pref = mgr.get_preferences()
        freq = pref.project_history["tech_stack_frequency"]
        assert freq["python"] == 2
        assert freq["flask"] == 1
        assert "python" in pref.tech_preferences["preferred_languages"]

    def test_record_project_result(self, tmp_profile):
        mgr = UserProfileManager(tmp_profile)
        mgr.record_project_result(True)
        mgr.record_project_result(True)
        mgr.record_project_result(False)

        pref = mgr.get_preferences()
        assert pref.project_history["total_projects"] == 3
        assert 0 < pref.project_history["success_rate"] < 1

    def test_set_preference(self, tmp_profile):
        mgr = UserProfileManager(tmp_profile)
        mgr.set_preference("code_style.comment_language", "chinese")
        pref = mgr.get_preferences()
        assert pref.code_style["comment_language"] == "chinese"

    def test_set_preference_invalid_key(self, tmp_profile):
        mgr = UserProfileManager(tmp_profile)
        mgr.set_preference("invalid_section.key", "value")
        # 不应报错


class TestPersistence:
    """持久化"""

    def test_save_and_load(self, tmp_profile):
        mgr1 = UserProfileManager(tmp_profile)
        mgr1.set_preference("code_style.naming_convention", "snake_case")
        mgr1.record_tech_stack(["python"])

        mgr2 = UserProfileManager(tmp_profile)
        pref = mgr2.get_preferences()
        assert pref.code_style["naming_convention"] == "snake_case"
        assert pref.project_history["tech_stack_frequency"]["python"] == 1

    def test_load_nonexistent(self, tmp_profile):
        os.unlink(tmp_profile)
        mgr = UserProfileManager(tmp_profile)
        pref = mgr.get_preferences()
        assert isinstance(pref, UserPreference)


class TestPromptGeneration:
    """prompt 生成"""

    def test_with_preferences(self, tmp_profile):
        mgr = UserProfileManager(tmp_profile)
        mgr.set_preference("code_style.naming_convention", "snake_case")
        mgr.set_preference("code_style.comment_language", "chinese")
        mgr.record_tech_stack(["python", "flask"])

        prompt = mgr.for_agent_prompt("coder")
        assert "snake_case" in prompt
        assert "chinese" in prompt
        assert "python" in prompt

    def test_role_filtering(self, tmp_profile):
        mgr = UserProfileManager(tmp_profile)
        mgr.set_preference("work_patterns.planning_style", "detailed")

        prompt_helper = mgr.for_agent_prompt("helper")
        prompt_coder = mgr.for_agent_prompt("coder")
        assert "规划偏好" in prompt_helper
        assert "规划偏好" not in prompt_coder or prompt_coder == ""

    def test_stats(self, tmp_profile):
        mgr = UserProfileManager(tmp_profile)
        mgr.record_tech_stack(["python"])
        stats = mgr.stats
        assert stats["exists"] is True
        assert stats["tech_stack_count"] == 1
