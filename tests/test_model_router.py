"""测试智能模型路由"""
import pytest
from autoc.core.llm.router import ModelRouter, PROVIDER_TIERS, AGENT_ROUTING


class TestModelRouter:
    def test_basic_routing_glm(self):
        router = ModelRouter("glm")
        model = router.route("helper", "simple")
        assert model == "glm-4.5-air"

    def test_helper_complex_uses_strongest(self):
        router = ModelRouter("glm")
        model = router.route("helper", "complex")
        assert model == "glm-5"

    def test_coder_simple_uses_cheap(self):
        router = ModelRouter("glm")
        model = router.route("coder", "simple")
        assert model == "glm-4.7-flash"

    def test_disabled_returns_empty(self):
        router = ModelRouter("glm", config={"enabled": False})
        assert router.route("helper", "complex") == ""

    def test_override_takes_priority(self):
        router = ModelRouter("glm", config={
            "enabled": True,
            "override": {"helper": {"simple": "glm-5"}},
        })
        assert router.route("helper", "simple") == "glm-5"

    def test_unknown_provider_returns_empty(self):
        router = ModelRouter("nonexistent")
        assert router.route("helper", "simple") == ""

    def test_routing_table(self):
        router = ModelRouter("glm")
        table = router.get_routing_table()
        assert "coder" in table
        assert "helper" in table
        assert "critique" in table
        for agent in table:
            for complexity in ("simple", "medium", "complex"):
                assert complexity in table[agent]

    def test_is_enabled(self):
        router = ModelRouter("glm")
        assert router.is_enabled
        router2 = ModelRouter("glm", config={"enabled": False})
        assert not router2.is_enabled

    def test_is_enabled_false_for_unknown_provider(self):
        router = ModelRouter("nonexistent")
        assert not router.is_enabled

    def test_critique_routing(self):
        router = ModelRouter("glm")
        model = router.route("critique", "medium")
        assert model

    def test_all_providers_have_four_tiers(self):
        for provider, tiers in PROVIDER_TIERS.items():
            for tier in ("strongest", "strong", "medium", "cheap"):
                assert tier in tiers, f"{provider} missing tier {tier}"

    def test_agent_routing_covers_all_complexities(self):
        for agent, routing in AGENT_ROUTING.items():
            for complexity in ("simple", "medium", "complex"):
                assert complexity in routing, f"{agent} missing complexity {complexity}"
