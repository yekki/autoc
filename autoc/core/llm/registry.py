"""LLM Registry — 集中管理所有 LLM 实例，提供 per-agent 计量和全局统计

参考 OpenHands 的 LLM Registry 设计：
- 每个 LLM 实例注册时绑定一个 usage_id（agent 角色）
- 提供全局 token 统计、per-agent 计量、运行时模型信息
- 支持运行时查询和导出
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from autoc.core.llm.client import LLMClient

logger = logging.getLogger("autoc.llm.registry")


@dataclass
class AgentMetrics:
    """单个 agent 的 LLM 使用指标"""
    usage_id: str
    model: str = ""
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    call_count: int = 0
    error_count: int = 0
    avg_latency_ms: float = 0.0
    total_latency_ms: int = 0
    registered_at: float = field(default_factory=time.time)


class LLMRegistry:
    """LLM 实例集中注册中心

    典型用法：
        registry = LLMRegistry()
        registry.register("coder", llm_coder)
        registry.register("critique", llm_critique)
        registry.register("helper", llm_helper)

        # 获取全局统计
        stats = registry.get_stats()
        # 获取单个 agent 的指标
        coder_metrics = registry.get_metrics("coder")
    """

    def __init__(self):
        self._clients: dict[str, LLMClient] = {}
        self._created_at = time.time()

    def register(self, usage_id: str, client: LLMClient) -> None:
        """注册 LLM 实例，绑定 agent 角色"""
        if usage_id in self._clients:
            logger.warning(f"覆盖已注册的 LLM 实例: {usage_id}")
        self._clients[usage_id] = client
        logger.debug(f"注册 LLM 实例: {usage_id} → {client.config.model}")

    def get(self, usage_id: str) -> LLMClient | None:
        """按 usage_id 获取 LLM 实例"""
        return self._clients.get(usage_id)

    def get_metrics(self, usage_id: str) -> AgentMetrics | None:
        """获取指定 agent 的实时计量数据"""
        client = self._clients.get(usage_id)
        if not client:
            return None

        call_count = len(client.call_log)
        error_count = client.error_calls
        total_latency = sum(r.latency_ms for r in client.call_log)
        avg_latency = total_latency / call_count if call_count > 0 else 0.0

        return AgentMetrics(
            usage_id=usage_id,
            model=client.config.model,
            total_tokens=client.total_tokens,
            prompt_tokens=client.prompt_tokens,
            completion_tokens=client.completion_tokens,
            cached_tokens=client.cached_tokens,
            call_count=call_count,
            error_count=error_count,
            avg_latency_ms=avg_latency,
            total_latency_ms=total_latency,
        )

    def get_all_metrics(self) -> dict[str, AgentMetrics]:
        """获取所有已注册 agent 的计量数据"""
        return {
            uid: self.get_metrics(uid)
            for uid in self._clients
        }

    def get_stats(self) -> dict[str, Any]:
        """全局统计摘要"""
        seen_ids: set[int] = set()
        total_tokens = 0
        total_calls = 0
        total_errors = 0
        per_agent: dict[str, dict] = {}

        for uid, client in self._clients.items():
            cid = id(client)
            metrics = self.get_metrics(uid)
            per_agent[uid] = {
                "model": metrics.model,
                "tokens": metrics.total_tokens,
                "calls": metrics.call_count,
                "errors": metrics.error_count,
                "avg_latency_ms": round(metrics.avg_latency_ms, 1),
            }
            if cid not in seen_ids:
                total_tokens += client.total_tokens
                total_calls += len(client.call_log)
                total_errors += client.error_calls
                seen_ids.add(cid)

        return {
            "total_tokens": total_tokens,
            "total_calls": total_calls,
            "total_errors": total_errors,
            "agents": per_agent,
            "uptime_seconds": round(time.time() - self._created_at, 1),
        }

    def format_summary(self) -> str:
        """格式化统计摘要（用于日志和 CLI 输出）"""
        stats = self.get_stats()
        lines = [
            f"LLM Registry — {len(self._clients)} agents, "
            f"{stats['total_tokens']:,} tokens, {stats['total_calls']} calls",
        ]
        for uid, info in stats["agents"].items():
            lines.append(
                f"  {uid:12s}: {info['model']:30s} "
                f"tokens={info['tokens']:>8,}  "
                f"calls={info['calls']:>4}  "
                f"errors={info['errors']:>2}  "
                f"avg_ms={info['avg_latency_ms']:>7.1f}"
            )
        return "\n".join(lines)

    @property
    def total_tokens(self) -> int:
        """去重后的全局 token 总量"""
        seen: set[int] = set()
        total = 0
        for client in self._clients.values():
            cid = id(client)
            if cid not in seen:
                total += client.total_tokens
                seen.add(cid)
        return total

    def __len__(self) -> int:
        return len(self._clients)

    def __contains__(self, usage_id: str) -> bool:
        return usage_id in self._clients
