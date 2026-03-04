"""测试 ModelConfigManager — 配置加载、legacy key 迁移、LLMConfig 构建"""

import json
import pytest

from autoc.core.llm.model_config import ModelConfigManager, _default_config, _mask_key


class TestLoad:
    """_load() 配置加载与 legacy key 迁移"""

    def test_missing_file_returns_defaults(self, tmp_path):
        mcm = ModelConfigManager(tmp_path)
        data = mcm.data
        assert set(data["active"].keys()) == {"coder", "critique", "helper", "planner"}
        assert data["active"]["coder"]["provider"] == ""

    def test_new_keys_kept_as_is(self, tmp_path):
        """已使用新版键名的配置直接保留"""
        raw = {
            "version": 2,
            "active": {
                "coder": {"provider": "glm", "model": "glm-5"},
                "critique": {"provider": "glm", "model": "glm-4.7"},
                "helper": {"provider": "qwen", "model": "qwen-plus"},
            },
            "credentials": {},
            "advanced": {},
        }
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "models.json").write_text(json.dumps(raw))

        mcm = ModelConfigManager(tmp_path)
        assert mcm.data["active"]["coder"]["model"] == "glm-5"
        assert mcm.data["active"]["critique"]["model"] == "glm-4.7"

    def test_invalid_json_returns_defaults(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "models.json").write_text("}{broken json")

        mcm = ModelConfigManager(tmp_path)
        data = mcm.data
        assert data["active"]["coder"]["provider"] == ""

    def test_credentials_preserved(self, tmp_path):
        raw = {
            "version": 2,
            "active": {"coder": {"provider": "glm", "model": "glm-5"}},
            "credentials": {
                "glm": {"api_key": "sk-test-123", "base_url": "https://api.example.com"},
            },
            "advanced": {},
        }
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "models.json").write_text(json.dumps(raw))

        mcm = ModelConfigManager(tmp_path)
        assert mcm.data["credentials"]["glm"]["api_key"] == "sk-test-123"

    def test_advanced_merges_with_defaults(self, tmp_path):
        raw = {
            "version": 2,
            "active": {},
            "credentials": {},
            "advanced": {"temperature": 0.9},
        }
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "models.json").write_text(json.dumps(raw))

        mcm = ModelConfigManager(tmp_path)
        adv = mcm.data["advanced"]
        assert adv["temperature"] == 0.9
        assert adv["max_tokens"] == 32768
        assert adv["timeout"] == 120

    def test_extra_top_level_keys_preserved(self, tmp_path):
        raw = {
            "version": 2,
            "custom_flag": True,
            "active": {},
            "credentials": {},
            "advanced": {},
        }
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "models.json").write_text(json.dumps(raw))

        mcm = ModelConfigManager(tmp_path)
        assert mcm.data["version"] == 2
        assert mcm.data["custom_flag"] is True


class TestBuildLLMConfig:
    """build_llm_config_for_agent() 构建 LLMConfig"""

    def _make_mcm(self, tmp_path, active, credentials=None):
        raw = {
            "version": 2,
            "active": active,
            "credentials": credentials or {},
            "advanced": {"temperature": 0.7, "max_tokens": 4096, "timeout": 60},
        }
        config_dir = tmp_path / "config"
        config_dir.mkdir(exist_ok=True)
        (config_dir / "models.json").write_text(json.dumps(raw))
        return ModelConfigManager(tmp_path)

    def test_build_with_coder(self, tmp_path):
        mcm = self._make_mcm(
            tmp_path,
            active={"coder": {"provider": "glm", "model": "glm-5"}},
            credentials={"glm": {"api_key": "sk-test"}},
        )
        llm = mcm.build_llm_config_for_agent("coder")
        assert llm is not None
        assert llm.model == "glm-5"
        assert llm.api_key == "sk-test"

    def test_build_returns_none_for_unconfigured(self, tmp_path):
        mcm = self._make_mcm(tmp_path, active={})
        assert mcm.build_llm_config_for_agent("coder") is None

    def test_build_returns_none_for_empty_provider(self, tmp_path):
        mcm = self._make_mcm(
            tmp_path,
            active={"coder": {"provider": "", "model": "glm-5"}},
        )
        assert mcm.build_llm_config_for_agent("coder") is None

    def test_advanced_params_propagated(self, tmp_path):
        mcm = self._make_mcm(
            tmp_path,
            active={"coder": {"provider": "glm", "model": "glm-5"}},
            credentials={"glm": {"api_key": "k"}},
        )
        llm = mcm.build_llm_config_for_agent("coder")
        assert llm.max_tokens == 4096
        assert llm.timeout == 60


class TestActiveConfig:
    """get/set/has_active_config"""

    def test_has_active_config_false_on_empty(self, tmp_path):
        mcm = ModelConfigManager(tmp_path)
        assert mcm.has_active_config() is False

    def test_has_active_config_true_after_set(self, tmp_path):
        mcm = ModelConfigManager(tmp_path)
        mcm.set_active("coder", "glm", "glm-5")
        assert mcm.has_active_config() is True

    def test_set_active_rejects_unknown_agent(self, tmp_path):
        mcm = ModelConfigManager(tmp_path)
        with pytest.raises(ValueError, match="未知 agent"):
            mcm.set_active("unknown_agent", "glm", "glm-5")


class TestMaskKey:
    def test_short_key(self):
        assert _mask_key("abc") == "***"

    def test_empty_key(self):
        assert _mask_key("") == ""

    def test_normal_key(self):
        result = _mask_key("sk-1234567890abcdef")
        assert result.startswith("sk-123")
        assert result.endswith("cdef")
        assert "..." in result


class TestSaveAndReload:
    def test_save_and_reload_roundtrip(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "models.json").write_text(json.dumps(_default_config()))

        mcm = ModelConfigManager(tmp_path)
        mcm.set_active("coder", "glm", "glm-5")
        mcm.save()

        mcm2 = ModelConfigManager(tmp_path)
        assert mcm2.data["active"]["coder"]["model"] == "glm-5"
