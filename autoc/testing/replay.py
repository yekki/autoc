"""Replay 录制/回放 — 录制真实 LLM 调用，确定性回放排查不稳定问题

用法:
    # 1. 录制模式：用真实 LLM 运行一次，录制所有请求/响应
    recorder = LLMRecorder()
    orc.llm_dev = recorder.wrap(orc.llm_dev, "dev")
    orc.llm_test = recorder.wrap(orc.llm_test, "test")
    orc.run("需求描述")
    recorder.save("recordings/session-001.jsonl")

    # 2. 回放模式：用录制数据替代真实 LLM，确定性重现
    replayer = LLMReplayer.load("recordings/session-001.jsonl")
    orc.llm_dev = replayer.wrap(orc.llm_dev, "dev")
    orc.run("需求描述")  # 完全确定性，不调用真实 LLM

这样可以:
- 录制一次失败的真实运行
- 多次回放，在 orchestrator/tool/state 层面加断点调试
- 对比两次录制找出 LLM 返回的差异点
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("autoc.testing.replay")


@dataclass
class LLMCallRecord:
    """单次 LLM 调用的完整录制"""
    seq: int = 0
    agent: str = ""
    timestamp: float = 0.0
    messages_hash: str = ""
    messages_count: int = 0
    tools_count: int = 0
    response: dict = field(default_factory=dict)
    error: str = ""
    latency_ms: int = 0


class LLMRecorder:
    """LLM 调用录制器 — 包装真实 LLMClient，记录所有 chat() 调用"""

    def __init__(self):
        self._records: list[LLMCallRecord] = []
        self._seq = 0

    def wrap(self, llm_client, agent_name: str):
        """包装 LLMClient，返回录制代理"""
        return _RecordingProxy(llm_client, self, agent_name)

    def record(self, call: LLMCallRecord):
        self._records.append(call)

    def save(self, path: str):
        """保存录制到 JSONL 文件"""
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for rec in self._records:
                line = {
                    "seq": rec.seq,
                    "agent": rec.agent,
                    "timestamp": rec.timestamp,
                    "messages_hash": rec.messages_hash,
                    "messages_count": rec.messages_count,
                    "tools_count": rec.tools_count,
                    "response": rec.response,
                    "error": rec.error,
                    "latency_ms": rec.latency_ms,
                }
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
        logger.info(f"录制已保存: {path} ({len(self._records)} 条)")

    def next_seq(self) -> int:
        self._seq += 1
        return self._seq

    @property
    def call_count(self) -> int:
        return len(self._records)


class LLMReplayer:
    """LLM 调用回放器 — 用录制数据替代真实 LLM 调用"""

    def __init__(self, records: list[dict]):
        self._records = records
        self._index = 0
        self._mismatches: list[dict] = []

    @classmethod
    def load(cls, path: str) -> "LLMReplayer":
        records = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        logger.info(f"回放数据已加载: {path} ({len(records)} 条)")
        return cls(records)

    def wrap(self, llm_client, agent_name: str):
        """包装 LLMClient，返回回放代理"""
        return _ReplayProxy(llm_client, self, agent_name)

    def next_response(self, agent: str, messages_count: int) -> dict | None:
        """获取下一条录制的响应"""
        if self._index >= len(self._records):
            logger.warning(f"回放数据已耗尽 (index={self._index})")
            return None

        rec = self._records[self._index]
        self._index += 1

        if rec.get("agent") != agent:
            self._mismatches.append({
                "index": self._index - 1,
                "expected_agent": rec.get("agent"),
                "actual_agent": agent,
            })
            logger.warning(
                f"回放 Agent 不匹配: 录制={rec.get('agent')}, 实际={agent} "
                f"(index={self._index - 1})"
            )

        if rec.get("error"):
            raise RuntimeError(f"回放录制的错误: {rec['error']}")

        return rec.get("response", {})

    @property
    def mismatches(self) -> list[dict]:
        return self._mismatches

    @property
    def remaining(self) -> int:
        return len(self._records) - self._index


def _hash_messages(messages: list[dict]) -> str:
    """计算消息列表的简化哈希（用于回放对齐检测）"""
    import hashlib
    parts = []
    for msg in messages[-3:]:
        role = msg.get("role", "")
        content = msg.get("content", "")[:200]
        parts.append(f"{role}:{content}")
    return hashlib.md5("|".join(parts).encode()).hexdigest()[:12]


class _RecordingProxy:
    """录制代理 — 透传真实 LLM 调用，同时录制请求/响应"""

    def __init__(self, real_llm, recorder: LLMRecorder, agent: str):
        self._real = real_llm
        self._recorder = recorder
        self._agent = agent

    def chat(self, messages, tools=None, **kwargs):
        seq = self._recorder.next_seq()
        start = time.time()
        error_msg = ""
        response = {}

        try:
            response = self._real.chat(messages, tools=tools, **kwargs)
            return response
        except Exception as e:
            error_msg = str(e)
            raise
        finally:
            latency = int((time.time() - start) * 1000)
            self._recorder.record(LLMCallRecord(
                seq=seq,
                agent=self._agent,
                timestamp=time.time(),
                messages_hash=_hash_messages(messages),
                messages_count=len(messages),
                tools_count=len(tools) if tools else 0,
                response=response,
                error=error_msg,
                latency_ms=latency,
            ))

    def __getattr__(self, name):
        return getattr(self._real, name)


class _ReplayProxy:
    """回放代理 — 用录制数据替代真实 LLM 调用"""

    def __init__(self, real_llm, replayer: LLMReplayer, agent: str):
        self._real = real_llm
        self._replayer = replayer
        self._agent = agent

    def chat(self, messages, tools=None, **kwargs):
        response = self._replayer.next_response(self._agent, len(messages))
        if response is None:
            logger.error("回放数据耗尽，回退到真实 LLM")
            return self._real.chat(messages, tools=tools, **kwargs)
        return response

    def __getattr__(self, name):
        return getattr(self._real, name)
