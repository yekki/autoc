"""测试 LLM 响应缓存"""
import time

import pytest
from autoc.core.llm.cache import LLMCache


@pytest.fixture
def cache(tmp_path):
    return LLMCache(cache_dir=str(tmp_path), ttl=3600)


class TestLLMCache:
    def test_put_and_get(self, cache):
        cache.put("key1", {"content": "hello"}, model="test", tokens_used=100)
        result = cache.get("key1")
        assert result is not None
        assert result["content"] == "hello"

    def test_get_nonexistent(self, cache):
        assert cache.get("nonexistent") is None

    def test_clear(self, cache):
        cache.put("k1", {"content": "a"})
        cache.put("k2", {"content": "b"})
        cache.clear()
        assert cache.get("k1") is None
        assert cache.get("k2") is None

    def test_stats(self, cache):
        cache.put("k1", {"content": "a"}, tokens_used=50)
        cache.get("k1")  # hit
        cache.get("k2")  # miss
        stats = cache.stats()
        assert stats["cached_responses"] == 1
        assert stats["session_hits"] == 1
        assert stats["session_misses"] == 1

    def test_make_key_deterministic(self):
        k1 = LLMCache.make_key([{"role": "user", "content": "hi"}], "model", 0.1)
        k2 = LLMCache.make_key([{"role": "user", "content": "hi"}], "model", 0.1)
        assert k1 == k2

    def test_make_key_different_for_different_input(self):
        k1 = LLMCache.make_key([{"role": "user", "content": "hi"}], "model", 0.1)
        k2 = LLMCache.make_key([{"role": "user", "content": "bye"}], "model", 0.1)
        assert k1 != k2

    def test_should_cache(self):
        assert LLMCache.should_cache(0.0)
        assert LLMCache.should_cache(0.3)
        assert not LLMCache.should_cache(0.5)
        assert not LLMCache.should_cache(0.7)

    def test_expired_entry(self, tmp_path):
        cache = LLMCache(cache_dir=str(tmp_path), ttl=0)
        cache.put("k1", {"content": "old"})
        time.sleep(0.1)
        assert cache.get("k1") is None

    def test_cleanup_expired(self, tmp_path):
        cache = LLMCache(cache_dir=str(tmp_path), ttl=0)
        cache.put("k1", {"content": "a"})
        cache.put("k2", {"content": "b"})
        time.sleep(0.1)
        removed = cache.cleanup_expired()
        assert removed == 2

    def test_stats_tokens_saved(self, cache):
        cache.put("k1", {"content": "a"}, tokens_used=100)
        cache.get("k1")
        cache.get("k1")
        stats = cache.stats()
        assert stats["tokens_saved"] >= 100

    def test_overwrite_key(self, cache):
        cache.put("k1", {"content": "old"})
        cache.put("k1", {"content": "new"})
        result = cache.get("k1")
        assert result["content"] == "new"
