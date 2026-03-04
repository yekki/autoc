"""LLM 响应缓存 — SQLite 持久化缓存

相同 prompt 的响应缓存到本地 SQLite，开发调试时直接重放，零 Token 消耗。

缓存策略：
- 仅缓存 temperature ≤ 0.3 的请求（确保结果确定性）
- 基于 prompt hash 做 key
- TTL 7 天自动过期
- 支持手动清除
"""

import hashlib
import json
import logging
import os
import sqlite3
import threading
import time

logger = logging.getLogger("autoc.llm_cache")

DEFAULT_TTL = 7 * 24 * 3600  # 7 天
MAX_CACHE_TEMP = 0.3


class LLMCache:
    """SQLite 持久化的 LLM 响应缓存"""

    def __init__(self, cache_dir: str = ".autoc", ttl: int = DEFAULT_TTL):
        db_path = os.path.join(cache_dir, "llm_cache.db")
        os.makedirs(cache_dir, exist_ok=True)
        self.db_path = db_path
        self.ttl = ttl
        self._hits = 0
        self._misses = 0
        # 实例级别写锁，每个 LLMCache 实例独立持锁，避免跨实例死锁
        self._write_lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                cache_key TEXT PRIMARY KEY,
                response TEXT NOT NULL,
                model TEXT,
                tokens_used INTEGER DEFAULT 0,
                created_at REAL NOT NULL,
                hit_count INTEGER DEFAULT 0
            )
        """)
        conn.commit()
        conn.close()

    def get(self, key: str) -> dict | None:
        """查询缓存，返回缓存的响应或 None。

        DELETE（过期淘汰）和 UPDATE（命中计数）均为写操作，加实例级写锁防止并发冲突。

        TODO: 当前 get() 在写锁内执行 SELECT，序列化了所有并发查询。
              优化方案：先在锁外 SELECT，仅在需要 DELETE/UPDATE 时获取写锁。
        """
        with self._write_lock:
            conn = sqlite3.connect(self.db_path)
            try:
                row = conn.execute(
                    "SELECT response, created_at FROM cache WHERE cache_key = ?",
                    (key,),
                ).fetchone()
                if not row:
                    self._misses += 1
                    return None
                if time.time() - row[1] > self.ttl:
                    conn.execute("DELETE FROM cache WHERE cache_key = ?", (key,))
                    conn.commit()
                    self._misses += 1
                    return None
                conn.execute(
                    "UPDATE cache SET hit_count = hit_count + 1 WHERE cache_key = ?",
                    (key,),
                )
                conn.commit()
                self._hits += 1
                return json.loads(row[0])
            finally:
                conn.close()

    def put(self, key: str, response: dict, model: str = "", tokens_used: int = 0):
        """写入缓存（写操作加实例级别锁，防止并发 database is locked）"""
        with self._write_lock:
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO cache
                       (cache_key, response, model, tokens_used, created_at, hit_count)
                       VALUES (?, ?, ?, ?, ?, 0)""",
                    (key, json.dumps(response, ensure_ascii=False), model, tokens_used, time.time()),
                )
                conn.commit()
            finally:
                conn.close()

    def clear(self):
        """清除所有缓存"""
        with self._write_lock:
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute("DELETE FROM cache")
                conn.commit()
            finally:
                conn.close()
        logger.info("LLM 响应缓存已清除")

    def cleanup_expired(self) -> int:
        """清除过期缓存，返回清除数量"""
        with self._write_lock:
            conn = sqlite3.connect(self.db_path)
            try:
                cutoff = time.time() - self.ttl
                result = conn.execute("DELETE FROM cache WHERE created_at < ?", (cutoff,))
                count = result.rowcount
                conn.commit()
            finally:
                conn.close()
        if count:
            logger.info(f"清除 {count} 条过期缓存")
        return count

    def stats(self) -> dict:
        """返回缓存统计"""
        conn = sqlite3.connect(self.db_path)
        try:
            total = conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
            total_hits = conn.execute("SELECT SUM(hit_count) FROM cache").fetchone()[0] or 0
            tokens_saved = conn.execute(
                "SELECT SUM(tokens_used * hit_count) FROM cache"
            ).fetchone()[0] or 0
            return {
                "cached_responses": total,
                "total_hits": total_hits,
                "session_hits": self._hits,
                "session_misses": self._misses,
                "tokens_saved": tokens_saved,
            }
        finally:
            conn.close()

    @staticmethod
    def make_key(messages: list, model: str, temperature: float) -> str:
        """从消息列表生成缓存键"""
        data = json.dumps(
            {"messages": messages, "model": model, "temp": temperature},
            sort_keys=True,
        )
        return hashlib.sha256(data.encode()).hexdigest()

    @staticmethod
    def should_cache(temperature: float) -> bool:
        """判断是否应该缓存"""
        return temperature <= MAX_CACHE_TEMP
