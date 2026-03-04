"""Token 成本统计 — GLM 专用定价 + 缓存感知费用估算

定价数据来源: https://zhipu-32152247.mintlify.app/guides/overview/pricing
所有价格单位: USD / 百万 Token
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from autoc.core.project.manager import ProjectManager

logger = logging.getLogger("autoc.token_stats")

# GLM 官方定价（USD / 百万 Token），来自 Z.AI Developer Documentation
# 三维定价: input（常规输入）/ cache_read（缓存命中输入）/ output（输出）
GLM_PRICING: dict[str, dict[str, float]] = {
    "glm-5":          {"input": 1.00,  "cache_read": 0.20,  "output": 3.20},
    "glm-5-code":     {"input": 1.20,  "cache_read": 0.30,  "output": 5.00},
    "glm-4.7":        {"input": 0.60,  "cache_read": 0.11,  "output": 2.20},
    "glm-4.6":        {"input": 0.60,  "cache_read": 0.11,  "output": 2.20},
    "glm-4.5":        {"input": 0.60,  "cache_read": 0.11,  "output": 2.20},
    "glm-4.5-air":    {"input": 0.20,  "cache_read": 0.03,  "output": 1.10},
    "glm-4.7-flash":  {"input": 0.00,  "cache_read": 0.00,  "output": 0.00},
    "glm-4.5-flash":  {"input": 0.00,  "cache_read": 0.00,  "output": 0.00},
    "codegeex-4":     {"input": 0.00,  "cache_read": 0.00,  "output": 0.00},
}

FALLBACK_PRICING = {"input": 0.60, "cache_read": 0.11, "output": 2.20}


def get_model_pricing(model: str) -> dict[str, float]:
    """查找模型定价，精确匹配优先，其次最长前缀匹配（避免短 key 优先于长 key 命中）"""
    if model in GLM_PRICING:
        return GLM_PRICING[model]
    key = model.lower()
    if key in GLM_PRICING:
        return GLM_PRICING[key]
    best_match, best_len = None, 0
    for m, p in GLM_PRICING.items():
        if key.startswith(m) and len(m) > best_len:
            best_match, best_len = p, len(m)
    return best_match or FALLBACK_PRICING


def is_free_model(model: str) -> bool:
    p = get_model_pricing(model)
    return p["input"] == 0 and p["output"] == 0


class TokenStats:
    """Token 成本统计器"""

    def __init__(self, project_manager: ProjectManager):
        self._project_manager = project_manager

    _AGENT_KEY_ALIASES: dict[str, str] = {
        "planner": "coder",
        "refiner": "helper",
        "dev": "coder",
        "developer": "coder",
        "implementer": "coder",
        "test": "critique",
        "tester": "critique",
    }

    def get_project_stats(self, project_name: str | None = None) -> dict:
        """获取项目累计 Token 统计"""
        metadata = self._project_manager.load()
        if not metadata:
            return {"total_tokens": 0, "sessions": 0, "agent_breakdown": {}}

        sessions = self._project_manager.list_sessions()
        total_tokens = 0
        total_prompt = 0
        total_completion = 0
        total_cached = 0
        agent_tokens: dict[str, int] = {
            "helper": 0, "coder": 0, "critique": 0,
        }

        for s in sessions:
            total_tokens += s.get("total_tokens", 0)
            at = s.get("agent_tokens", {})
            for raw_key, value in at.items():
                if raw_key.startswith("_"):
                    continue
                if not isinstance(value, (int, float)):
                    continue
                # 处理旧数据中的合并 key（如 "planner+coder"）
                if "+" in raw_key:
                    sub_keys = raw_key.split("+")
                    canonical = self._AGENT_KEY_ALIASES.get(sub_keys[-1], sub_keys[-1])
                else:
                    canonical = self._AGENT_KEY_ALIASES.get(raw_key, raw_key)
                if canonical in agent_tokens:
                    agent_tokens[canonical] += value
            total_prompt += at.get("_prompt_tokens", 0)
            total_completion += at.get("_completion_tokens", 0)
            total_cached += at.get("_cached_tokens", 0)

        return {
            "total_tokens": total_tokens,
            "prompt_tokens": total_prompt,
            "completion_tokens": total_completion,
            "cached_tokens": total_cached,
            "sessions": len(sessions),
            "agent_breakdown": agent_tokens,
        }

    def estimate_cost(
        self, tokens: int, model: str = "glm-4.7",
        prompt_tokens: int = 0, completion_tokens: int = 0,
        cached_tokens: int = 0,
    ) -> float:
        """估算费用 (USD)

        精确模式（有 prompt/completion/cached 明细）:
          uncached_input × input_price + cached × cache_read_price + completion × output_price
        粗略模式（仅有 total）:
          按实际 I/O 比（90:10）加权估算
        """
        pricing = get_model_pricing(model)

        if prompt_tokens > 0 or completion_tokens > 0:
            uncached_input = max(0, prompt_tokens - cached_tokens)
            return (
                uncached_input / 1_000_000 * pricing["input"]
                + cached_tokens / 1_000_000 * pricing["cache_read"]
                + completion_tokens / 1_000_000 * pricing["output"]
            )

        # 粗略模式: 根据 Cursor 用量分析，典型 I/O 比约 90:10
        est_input = int(tokens * 0.9)
        est_output = tokens - est_input
        return (
            est_input / 1_000_000 * pricing["input"]
            + est_output / 1_000_000 * pricing["output"]
        )

    def estimate_cache_savings(
        self, cached_tokens: int, model: str = "glm-4.7",
    ) -> float:
        """计算缓存节省的费用 (USD)"""
        pricing = get_model_pricing(model)
        saved_per_token = pricing["input"] - pricing["cache_read"]
        return cached_tokens / 1_000_000 * saved_per_token

    def format_summary(self) -> str:
        """格式化为文本摘要"""
        stats = self.get_project_stats()
        if stats["total_tokens"] == 0:
            return "  暂无 Token 使用记录"

        total = stats["total_tokens"]
        prompt = stats["prompt_tokens"]
        completion = stats["completion_tokens"]
        cached = stats["cached_tokens"]
        breakdown = stats["agent_breakdown"]

        lines = [
            f"  Token 消耗: {total:,}",
            f"  会话次数: {stats['sessions']}",
        ]

        if prompt > 0:
            cache_pct = f" (缓存命中 {cached * 100 // prompt}%)" if cached > 0 and prompt > 0 else ""
            lines.append(f"  输入/输出: {prompt:,} / {completion:,}{cache_pct}")

        agent_lines = [
            f"  Agent 分布:",
            f"    辅助 AI: {breakdown.get('helper', 0):,}",
            f"    Coder AI: {breakdown.get('coder', 0):,}",
            f"    Critique AI: {breakdown.get('critique', 0):,}",
        ]
        lines.extend(agent_lines)
        return "\n".join(lines)
