"""LLM 客户端 - 统一的大模型调用接口，兼容 OpenAI API 格式"""

import hashlib
import json
import logging
import re
import threading
import time
import random
from dataclasses import dataclass, field
from typing import Any, Optional

from openai import OpenAI
from pydantic import BaseModel, Field

from autoc.exceptions import LLMError, LLMAuthError, LLMRateLimitError, LLMTimeoutError
from .cache import LLMCache

logger = logging.getLogger("autoc.llm")


def _is_cjk(c: str) -> bool:
    """判断字符是否属于 CJK 统一表意文字（含扩展区）、日韩假名、全角标点"""
    cp = ord(c)
    return (
        0x4E00 <= cp <= 0x9FFF        # CJK Unified Ideographs
        or 0x3400 <= cp <= 0x4DBF     # CJK Extension A
        or 0x20000 <= cp <= 0x2A6DF   # CJK Extension B
        or 0x2A700 <= cp <= 0x2B73F   # CJK Extension C
        or 0x2B740 <= cp <= 0x2B81F   # CJK Extension D
        or 0xF900 <= cp <= 0xFAFF     # CJK Compatibility Ideographs
        or 0x3040 <= cp <= 0x309F     # Hiragana
        or 0x30A0 <= cp <= 0x30FF     # Katakana
        or 0xAC00 <= cp <= 0xD7AF     # Hangul Syllables
        or 0xFF00 <= cp <= 0xFFEF     # Halfwidth and Fullwidth Forms
    )


def _get_content_text(content) -> str:
    """将消息 content 转为纯文本（支持 str 和多模态 list）"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            part.get("text", "") for part in content
            if isinstance(part, dict) and "text" in part
        )
    return str(content) if content else ""


def _estimate_tokens(text: str) -> int:
    """粗略估算 token 数：ASCII /4，CJK/全角 ×1.5，其他非 ASCII（拉丁扩展/西里尔/emoji）/3"""
    if not text:
        return 0
    ascii_count = 0
    cjk_count = 0
    other_count = 0
    for c in text:
        cp = ord(c)
        if cp < 128:
            ascii_count += 1
        elif _is_cjk(c):
            cjk_count += 1
        else:
            other_count += 1
    return max(1, ascii_count // 4 + int(cjk_count * 1.5) + other_count // 3)


@dataclass
class CallRecord:
    """单次 LLM 调用的完整记录，用于逐调用分析和成本归因"""
    timestamp: str = ""
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0
    is_error: bool = False
    is_cache_hit: bool = False
    error_msg: str = ""


# ==================== 服务提供商配置 ====================
# 每个提供商包含 base_url、热门模型列表、角色推荐标签
# tags 含义: helper=适合需求分析/架构设计, dev=适合代码生成, test=适合测试/审查

PROVIDERS: dict[str, dict[str, Any]] = {
    "glm": {
        "name": "智谱 GLM",
        "base_url": "https://open.bigmodel.cn/api/coding/paas/v4",
        "editable_url": False,
        "env_key": "GLM_API_KEY",
        "default_headers": {},
        "extra_params": {},
        "models": [
            {"id": "glm-5", "name": "GLM-5 (旗舰)", "tags": ["helper", "test"]},
            {"id": "glm-4.7", "name": "GLM-4.7", "tags": ["helper", "dev", "test"]},
            {"id": "glm-4.6", "name": "GLM-4.6", "tags": ["dev"]},
            {"id": "glm-4.5-air", "name": "GLM-4.5 Air", "tags": ["helper", "dev", "test"]},
            {"id": "glm-4.7-flash", "name": "GLM-4.7 Flash (免费)", "tags": ["helper", "dev", "test"]},
            {"id": "codegeex-4", "name": "CodeGeeX 4", "tags": ["dev"]},
        ],
    },
    "qwen": {
        "name": "阿里千问",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "editable_url": False,
        "env_key": "QWEN_API_KEY",
        "default_headers": {},
        "extra_params": {},
        "models": [
            {"id": "qwen3-max", "name": "Qwen3-Max (旗舰)", "tags": ["helper", "test"]},
            {"id": "qwen3.5-plus", "name": "Qwen3.5-Plus (均衡)", "tags": ["helper", "dev", "test"]},
            {"id": "qwen3.5-flash", "name": "Qwen3.5-Flash (快速)", "tags": ["dev", "test"]},
            {"id": "qwen3-coder-plus", "name": "Qwen3-Coder-Plus (代码)", "tags": ["dev"]},
            {"id": "qwen3-coder-flash", "name": "Qwen3-Coder-Flash", "tags": ["dev"]},
            {"id": "qwen-turbo", "name": "Qwen-Turbo (经济)", "tags": ["dev", "test"]},
            {"id": "qwen-long", "name": "Qwen-Long (长文本)", "tags": ["helper"]},
        ],
    },
}

# ==================== 向后兼容的预设配置 ====================
# 从 PROVIDERS 自动派生，供旧版 LLMConfig.resolve() 使用
PRESETS: dict[str, dict[str, Any]] = {}
for _pid, _prov in PROVIDERS.items():
    if _pid == "openai_compatible":
        continue
    PRESETS[_pid] = {
        "base_url": _prov["base_url"],
        "model": _prov["models"][0]["id"] if _prov["models"] else "default",
        "description": _prov["name"],
        "extra_params": _prov["extra_params"],
        "default_headers": _prov["default_headers"],
    }


class LLMConfig(BaseModel):
    """LLM 配置"""
    preset: str = ""
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    temperature: float = 0.7
    max_tokens: int = 32768
    timeout: int = 120
    extra_params: dict = Field(default_factory=dict)
    max_retries: int = 3
    retry_base_delay: float = 2.0

    def resolve(self) -> "LLMConfig":
        """
        解析预设配置：如果设置了 preset，用预设值填充空白的 base_url、model 和 extra_params。
        返回一个新的已解析的 LLMConfig 实例。
        """
        resolved_base_url = self.base_url
        resolved_model = self.model
        resolved_extra = self.extra_params.copy()

        if self.preset and self.preset in PRESETS:
            preset_data = PRESETS[self.preset]
            if not resolved_base_url:
                resolved_base_url = preset_data["base_url"]
            if not resolved_model:
                resolved_model = preset_data["model"]
            if not resolved_extra:
                resolved_extra = preset_data.get("extra_params", {})
            logger.info(
                f"使用预设 '{self.preset}': {preset_data['description']} "
                f"(base_url={resolved_base_url}, model={resolved_model})"
            )
        elif self.preset:
            available = ", ".join(PRESETS.keys())
            logger.warning(f"未知预设 '{self.preset}'，可用预设: {available}")

        if not resolved_base_url:
            resolved_base_url = "https://open.bigmodel.cn/api/coding/paas/v4"
        if not resolved_model:
            resolved_model = "glm-4.7"

        return LLMConfig(
            preset=self.preset,
            base_url=resolved_base_url,
            api_key=self.api_key,
            model=resolved_model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            timeout=self.timeout,
            extra_params=resolved_extra,
            max_retries=self.max_retries,
            retry_base_delay=self.retry_base_delay,
        )


class LLMClient:
    """统一的 LLM 调用客户端，兼容所有 OpenAI 格式 API"""

    def __init__(self, config: LLMConfig):
        # 先解析预设
        self.config = config.resolve()

        # 构建客户端参数
        client_kwargs: dict[str, Any] = {
            "api_key": self.config.api_key,
            "base_url": self.config.base_url,
            "timeout": self.config.timeout,
        }

        # 注入预设的自定义请求头（如 Kimi Coding API 的 User-Agent）
        preset_data = PRESETS.get(self.config.preset, {})
        default_headers = preset_data.get("default_headers", {})
        if default_headers:
            client_kwargs["default_headers"] = default_headers

        self.client = OpenAI(**client_kwargs)
        self.total_tokens = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.cached_tokens = 0
        self.error_calls = 0

        self.call_log: list[CallRecord] = []

        # per-tag token 统计（用于共享实例下拆分不同 Agent 的消耗）
        self._current_tag: str = ""
        self._tag_tokens: dict[str, dict[str, int]] = {}

        # Completion 日志（每次 LLM 调用的 request/response 写入独立文件）
        self._completion_log_dir: str | None = None

        # 响应缓存（temperature <= 0.3 的确定性请求）
        self._cache: dict[str, dict] = {}
        self._cache_lock = threading.Lock()
        self._cache_hits = 0
        self._cache_misses = 0

        # SQLite 持久化缓存（补充内存缓存）
        self._persistent_cache: LLMCache | None = None
        try:
            self._persistent_cache = LLMCache()
            self._persistent_cache.cleanup_expired()
        except Exception as e:
            logger.warning(f"持久化缓存初始化失败: {e}")

        logger.info(f"LLM 客户端初始化: model={self.config.model}, base_url={self.config.base_url}")

    def _make_cache_key(
        self,
        messages: list[dict],
        tools: Optional[list[dict]],
        temperature: float,
        max_tokens: Optional[int] = None,
        response_format: Optional[dict] = None,
        extra_params: Optional[dict] = None,
    ) -> Optional[str]:
        """生成缓存键，仅对低温度请求启用缓存。纳入所有影响输出的因素。"""
        if temperature > 0.3:
            return None
        model = self.config.model or ""
        key_data: list = list(messages)
        if tools:
            key_data.append({"_tools": tools})
        if max_tokens:
            key_data.append({"_max_tokens": max_tokens})
        if response_format:
            key_data.append({"_response_format": response_format})
        if extra_params:
            key_data.append({"_extra_params": extra_params})
        return LLMCache.make_key(key_data, model, temperature)

    @property
    def cache_stats(self) -> dict:
        return {"hits": self._cache_hits, "misses": self._cache_misses, "size": len(self._cache)}

    def get_tag_tokens(self, tag: str) -> dict[str, int]:
        """获取指定 tag 的 token 消耗（用于共享实例下的 Agent 级别拆分）"""
        return dict(self._tag_tokens.get(tag, {"prompt": 0, "completion": 0, "cached": 0, "total": 0, "calls": 0}))

    def set_tag(self, tag: str) -> None:
        """设置当前调用来源标签（用于 per-agent Token 统计）"""
        self._current_tag = tag

    def _append_call_record(self, record: CallRecord) -> None:
        """追加调用记录并裁剪，防止无界增长"""
        self.call_log.append(record)
        if len(self.call_log) > 1000:
            self.call_log = self.call_log[-1000:]

    def enable_completion_logging(self, log_dir: str) -> None:
        """启用 LLM Completion 日志（每次调用写入独立 JSONL 文件）"""
        import os
        os.makedirs(log_dir, exist_ok=True)
        self._completion_log_dir = log_dir
        logger.info(f"Completion 日志已启用: {log_dir}")

    def _log_completion(
        self, messages: list[dict], result: dict, record: CallRecord,
    ) -> None:
        """将完整 request/response 写入 Completion 日志文件"""
        if not self._completion_log_dir:
            return
        import os
        try:
            log_file = os.path.join(self._completion_log_dir, "completions.jsonl")
            entry = {
                "ts": record.timestamp,
                "model": record.model,
                "prompt_tokens": record.prompt_tokens,
                "completion_tokens": record.completion_tokens,
                "latency_ms": record.latency_ms,
                "messages_count": len(messages),
                "last_user_msg": self._extract_last_user_msg(messages),
                "response_content": (result.get("content") or "")[:500],
                "tool_calls": [
                    {"name": tc.get("name"), "args_preview": str(tc.get("arguments", {}))[:200]}
                    for tc in result.get("tool_calls", [])
                ],
                "finish_reason": result.get("finish_reason", ""),
            }
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        except Exception as e:
            logger.debug(f"Completion 日志写入失败: {e}")

    @staticmethod
    def _extract_last_user_msg(messages: list[dict]) -> str:
        """提取最近一条 user 消息的前 200 字符（用于日志概览）"""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                return str(msg.get("content", ""))[:200]
        return ""

    @staticmethod
    def _safe_parse_arguments(raw: str) -> dict:
        """
        安全解析 tool call 的 arguments JSON，容错常见 LLM 输出问题。

        常见问题: 末尾多逗号、缺少引号、多余换行等。
        """
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # 尝试修复: 去掉末尾多余逗号
        fixed = re.sub(r',\s*([}\]])', r'\1', raw)
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass

        # 尝试修复: 提取第一个 {...} 块
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        # 兜底: 返回原始字符串作为单参数
        logger.warning(f"无法解析 tool arguments，返回原始内容: {raw[:100]}...")
        return {"raw_arguments": raw}

    def chat(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        response_format: Optional[dict] = None,
    ) -> dict:
        """
        发送对话请求（带重试机制）

        Args:
            messages: 消息列表 [{"role": "system"|"user"|"assistant", "content": "..."}]
            tools: 工具定义列表 (function calling)
            temperature: 温度参数
            max_tokens: 最大生成 token 数
            response_format: 响应格式要求

        Returns:
            dict: {"content": str, "reasoning_content": str, "tool_calls": list, "finish_reason": str}
        """
        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.config.temperature,
            "max_tokens": max_tokens if max_tokens is not None else self.config.max_tokens,
        }

        # 注入预设额外参数（如 GLM-5 的 thinking）
        # 通过 extra_body 传递非标准参数，避免 OpenAI SDK 报错
        if self.config.extra_params:
            kwargs["extra_body"] = self.config.extra_params

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        if response_format:
            kwargs["response_format"] = response_format

        logger.debug(f"LLM 请求: model={self.config.model}, messages={len(messages)}")

        # 检查缓存
        effective_temp = temperature if temperature is not None else self.config.temperature
        eff_max_tokens = max_tokens if max_tokens is not None else self.config.max_tokens
        cache_key = self._make_cache_key(
            messages, tools, effective_temp,
            max_tokens=eff_max_tokens,
            response_format=response_format,
            extra_params=self.config.extra_params or None,
        )
        _mem_cache_hit = None
        if cache_key:
            with self._cache_lock:
                if cache_key in self._cache:
                    self._cache_hits += 1
                    _mem_cache_hit = self._cache[cache_key]
        if _mem_cache_hit is not None:
            logger.debug(f"LLM 缓存命中 (hits={self._cache_hits})")
            # 缓存命中时估算 token 并计入统计，保持 total_tokens 的单调递增语义
            _est_prompt = sum(_estimate_tokens(_get_content_text(m.get("content", ""))) for m in messages)
            _est_completion = _estimate_tokens(
                _mem_cache_hit.get("content", "") if isinstance(_mem_cache_hit, dict) else str(_mem_cache_hit)
            )
            _est_total = _est_prompt + _est_completion
            self.total_tokens += _est_total
            self.prompt_tokens += _est_prompt
            self.completion_tokens += _est_completion
            if self._current_tag:
                td = self._tag_tokens.setdefault(
                    self._current_tag,
                    {"prompt": 0, "completion": 0, "cached": 0, "total": 0, "calls": 0},
                )
                td["prompt"] += _est_prompt
                td["completion"] += _est_completion
                td["total"] += _est_total
                td["calls"] += 1
            self._append_call_record(CallRecord(
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                model=self.config.model, is_cache_hit=True,
                prompt_tokens=_est_prompt, completion_tokens=_est_completion,
                total_tokens=_est_total,
            ))
            return _mem_cache_hit

        # 持久化缓存检查
        if cache_key and self._persistent_cache:
            persistent_key = cache_key  # 复用 _make_cache_key 的结果（已含 tools）
            cached = self._persistent_cache.get(persistent_key)
            if cached:
                self._cache_hits += 1
                logger.debug(f"LLM 持久化缓存命中")
                _est_prompt = sum(_estimate_tokens(_get_content_text(m.get("content", ""))) for m in messages)
                _est_completion = _estimate_tokens(
                    cached.get("content", "") if isinstance(cached, dict) else str(cached)
                )
                _est_total = _est_prompt + _est_completion
                self.total_tokens += _est_total
                self.prompt_tokens += _est_prompt
                self.completion_tokens += _est_completion
                if self._current_tag:
                    td = self._tag_tokens.setdefault(
                        self._current_tag,
                        {"prompt": 0, "completion": 0, "cached": 0, "total": 0, "calls": 0},
                    )
                    td["prompt"] += _est_prompt
                    td["completion"] += _est_completion
                    td["total"] += _est_total
                    td["calls"] += 1
                self._append_call_record(CallRecord(
                    timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    model=self.config.model, is_cache_hit=True,
                    prompt_tokens=_est_prompt, completion_tokens=_est_completion,
                    total_tokens=_est_total,
                ))
                with self._cache_lock:
                    self._cache[cache_key] = cached  # 回填内存缓存，避免重复 SQLite 查询
                return cached

        if cache_key:
            self._cache_misses += 1

        # 重试循环
        last_error: Optional[Exception] = None
        for attempt in range(self.config.max_retries + 1):
            t0 = time.monotonic()
            try:
                response = self.client.chat.completions.create(**kwargs)

                latency_ms = int((time.monotonic() - t0) * 1000)
                if not response.choices:
                    raise LLMError("API 返回空响应（choices 为空），可能触发了内容过滤或模型过载")
                message = response.choices[0].message

                # 统计 token
                call_prompt = 0
                call_completion = 0
                call_cached = 0
                call_total = 0

                if response.usage and response.usage.total_tokens:
                    call_total = response.usage.total_tokens
                    call_prompt = response.usage.prompt_tokens or 0
                    call_completion = response.usage.completion_tokens or 0
                    self.total_tokens += call_total
                    self.prompt_tokens += call_prompt
                    self.completion_tokens += call_completion

                    # GLM Prompt Caching：缓存命中 Token 按 cache_read 价格计费（约 20% of input）
                    ptd = getattr(response.usage, "prompt_tokens_details", None)
                    if ptd:
                        call_cached = getattr(ptd, "cached_tokens", 0) or 0
                    self.cached_tokens += call_cached

                    # per-tag 统计（支持共享实例下的 Agent 级别拆分）
                    if self._current_tag:
                        td = self._tag_tokens.setdefault(
                            self._current_tag,
                            {"prompt": 0, "completion": 0, "cached": 0, "total": 0, "calls": 0},
                        )
                        td["prompt"] += call_prompt
                        td["completion"] += call_completion
                        td["cached"] += call_cached
                        td["total"] += call_total
                        td["calls"] += 1

                    if call_cached > 0:
                        logger.debug(
                            f"Token: prompt={call_prompt} (cached={call_cached}), "
                            f"completion={call_completion}, total={call_total}, "
                            f"latency={latency_ms}ms"
                        )
                    else:
                        logger.debug(
                            f"Token: prompt={call_prompt}, "
                            f"completion={call_completion}, total={call_total}, "
                            f"latency={latency_ms}ms"
                        )
                else:
                    est_input = sum(_estimate_tokens(_get_content_text(m.get("content", ""))) for m in messages)
                    est_output = _estimate_tokens(message.content or "")
                    call_total = est_input + est_output
                    call_prompt = est_input
                    call_completion = est_output
                    self.total_tokens += call_total
                    self.prompt_tokens += call_prompt
                    self.completion_tokens += call_completion
                    logger.debug(f"Token（估算）: ~{call_total}, latency={latency_ms}ms")

                    # per-tag 统计（估算分支）
                    if self._current_tag:
                        td = self._tag_tokens.setdefault(
                            self._current_tag,
                            {"prompt": 0, "completion": 0, "cached": 0, "total": 0, "calls": 0},
                        )
                        td["prompt"] += call_prompt
                        td["completion"] += call_completion
                        td["total"] += call_total
                        td["calls"] += 1

                self._append_call_record(CallRecord(
                    timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    model=self.config.model,
                    prompt_tokens=call_prompt,
                    completion_tokens=call_completion,
                    cached_tokens=call_cached,
                    total_tokens=call_total,
                    latency_ms=latency_ms,
                ))

                result = {
                    "content": message.content or "",
                    "tool_calls": [],
                    "finish_reason": response.choices[0].finish_reason,
                    "reasoning_content": getattr(message, "reasoning_content", None) or "",
                }

                # 处理 tool calls（带容错）
                if message.tool_calls:
                    for tc in message.tool_calls:
                        result["tool_calls"].append({
                            "id": tc.id,
                            "name": tc.function.name,
                            "arguments": self._safe_parse_arguments(tc.function.arguments),
                        })

                # 缓存确定性结果（无 tool_calls 的纯文本回复）
                if cache_key and not result["tool_calls"]:
                    with self._cache_lock:
                        self._cache[cache_key] = result
                        if len(self._cache) > 200:
                            oldest = next(iter(self._cache))
                            del self._cache[oldest]

                    if self._persistent_cache:
                        persistent_key = cache_key  # 复用 _make_cache_key 的结果（已含 tools）
                        tokens_used = response.usage.total_tokens if response.usage else 0
                        self._persistent_cache.put(persistent_key, result, self.config.model, tokens_used)

                self._log_completion(messages, result, self.call_log[-1])
                return result

            except Exception as e:
                latency_ms = int((time.monotonic() - t0) * 1000)
                self.error_calls += 1
                self._append_call_record(CallRecord(
                    timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    model=self.config.model, latency_ms=latency_ms,
                    is_error=True, error_msg=str(e)[:200],
                ))
                last_error = e
                error_str = str(e).lower()

                # 三层 API 限制检测（参考 Ralph 的 three-layer detection）
                # Layer 1: timeout guard — 超时不是 API 限制
                is_timeout = any(kw in error_str for kw in ["timeout", "timed out"])

                # Layer 2: 结构化错误检测
                is_auth = any(kw in error_str for kw in ["401", "invalid api key", "unauthorized", "authentication"])
                is_rate_limit = any(kw in error_str for kw in ["429", "rate_limit", "rate limit", "overloaded"])
                is_quota_exhausted = any(kw in error_str for kw in [
                    "quota", "insufficient_quota", "billing",
                    "exceeded", "limit reached", "usage limit",
                ])
                is_server = any(kw in error_str for kw in ["500", "502", "503", "504"])
                is_connection = "connection" in error_str

                is_retryable = is_rate_limit or is_timeout or is_server or is_connection

                if is_auth:
                    raise LLMAuthError(f"API Key 无效或未授权: {e}")

                # API 配额耗尽（如 5 小时限制），长时间等待后重试
                if is_quota_exhausted and not is_timeout:
                    logger.warning(f"API 配额可能耗尽: {e}，建议等待后重试")
                    raise LLMRateLimitError(f"API 配额耗尽（可能触及使用限制）: {e}")

                if not is_retryable or attempt >= self.config.max_retries:
                    if is_rate_limit:
                        raise LLMRateLimitError(f"请求频率超限: {e}")
                    if is_timeout:
                        raise LLMTimeoutError(f"调用超时: {e}")
                    raise LLMError(f"LLM 调用失败: {e}")

                # 速率限制时使用更长的退避
                if is_rate_limit:
                    delay = max(30.0, self.config.retry_base_delay * (4 ** attempt)) + random.uniform(0, 5)
                else:
                    delay = self.config.retry_base_delay * (2 ** attempt) + random.uniform(0, 1)
                logger.warning(
                    f"LLM 调用失败 ({e})，{delay:.1f}s 后重试 "
                    f"(第 {attempt + 1}/{self.config.max_retries} 次)..."
                )
                time.sleep(delay)

        # 所有重试都失败
        logger.error(f"LLM 调用失败，已重试 {self.config.max_retries} 次")
        raise LLMError(f"LLM 调用失败 (重试 {self.config.max_retries} 次): {last_error}")

    def chat_stream(
        self,
        messages: list[dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ):
        """流式对话（含瞬态错误重试，与 chat() 策略对齐）"""
        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.config.temperature,
            "max_tokens": max_tokens if max_tokens is not None else self.config.max_tokens,
            "stream": True,
        }

        if self.config.extra_params:
            kwargs["extra_body"] = self.config.extra_params

        max_retries = self.config.max_retries
        for attempt in range(max_retries + 1):
            try:
                t0 = time.monotonic()
                collected_content = ""
                has_yielded = False
                response = self.client.chat.completions.create(**kwargs)
                for chunk in response:
                    if chunk.choices and chunk.choices[0].delta.content:
                        text = chunk.choices[0].delta.content
                        collected_content += text
                        has_yielded = True
                        yield text
                # 流式结束后补记 Token（使用估算值）
                latency_ms = int((time.monotonic() - t0) * 1000)
                est_input = sum(_estimate_tokens(_get_content_text(m.get("content", ""))) for m in messages)
                est_output = _estimate_tokens(collected_content)
                call_total = est_input + est_output
                self.total_tokens += call_total
                self.prompt_tokens += est_input
                self.completion_tokens += est_output
                if self._current_tag:
                    td = self._tag_tokens.setdefault(
                        self._current_tag,
                        {"prompt": 0, "completion": 0, "cached": 0, "total": 0, "calls": 0},
                    )
                    td["prompt"] += est_input
                    td["completion"] += est_output
                    td["total"] += call_total
                    td["calls"] += 1
                record = CallRecord(
                    timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    model=self.config.model,
                    prompt_tokens=est_input,
                    completion_tokens=est_output,
                    total_tokens=call_total,
                    latency_ms=latency_ms,
                )
                self._append_call_record(record)
                return
            except Exception as e:
                error_str = str(e).lower()
                is_auth = any(kw in error_str for kw in ["401", "invalid api key", "unauthorized", "authentication"])
                is_timeout = any(kw in error_str for kw in ["timeout", "timed out"])
                is_rate_limit = any(kw in error_str for kw in ["429", "rate_limit", "rate limit", "overloaded"])
                is_server = any(kw in error_str for kw in ["500", "502", "503", "504"])
                is_retryable = (is_rate_limit or is_timeout or is_server) and not is_auth

                if is_auth:
                    raise LLMAuthError(f"API Key 无效（流式）: {e}") from e

                # 已经 yield 过内容，重试会导致重复输出，直接终止
                if has_yielded:
                    logger.error(
                        f"流式输出中断（已输出 {len(collected_content)} 字符，不重试）: {e}"
                    )
                    raise LLMError(f"流式输出中断: {e}") from e

                if is_retryable and attempt < max_retries:
                    delay = self.config.retry_base_delay * (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(f"LLM 流式调用失败，{delay:.1f}s 后重试 (第 {attempt + 1}/{max_retries} 次): {e}")
                    time.sleep(delay)
                    continue

                logger.error(f"LLM 流式调用失败: {e}")
                if is_rate_limit:
                    raise LLMRateLimitError(f"请求频率超限（流式）: {e}") from e
                if is_timeout:
                    raise LLMTimeoutError(f"调用超时（流式）: {e}") from e
                raise LLMError(f"流式请求失败: {e}") from e
