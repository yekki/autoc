"""ConversationStore — 对话增量持久化

参考 OpenHands Conversation debounced 持久化设计：
- Debounced 保存策略：每 N 条消息变更 或 N 秒间隔保存一次快照
- Append-Only JSONL 存储：每个 session 一个文件
- 快照 = 某一时刻的完整 conversation_history + 元数据
- 支持断点续传：从最近快照恢复 Agent 对话状态

存储格式（每行一个 JSON 快照）：
{
    "snapshot_id": "snap-001",
    "ts": 1700000000.123,
    "agent": "main",
    "iteration": 3,
    "message_count": 15,
    "messages": [...],           # 完整 conversation_history
    "metadata": {...}            # 附加上下文（task_id, phase 等）
}

Debounce 策略（两个条件取 OR）：
1. 自上次保存后新增 >= debounce_messages 条消息
2. 自上次保存后经过 >= debounce_seconds 秒
"""

import json
import logging
import os
import time
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("autoc.conversation")


@dataclass
class ConversationSnapshot:
    """对话快照"""
    snapshot_id: str
    ts: float
    agent: str
    iteration: int
    message_count: int
    messages: list[dict]
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "snapshot_id": self.snapshot_id,
            "ts": self.ts,
            "agent": self.agent,
            "iteration": self.iteration,
            "message_count": self.message_count,
            "messages": self.messages,
            "metadata": self.metadata,
        }


class ConversationStore:
    """对话增量持久化

    用法：
        store = ConversationStore("/workspace/.autoc-conversations", "session-123")

        # Agent 每次迭代后调用（debounce 内部判断是否实际保存）
        store.maybe_save("main", conversation_history, iteration=3)

        # 断点续传：加载最近快照
        snapshot = store.load_latest("main")
        if snapshot:
            agent.conversation_history = snapshot.messages
    """

    def __init__(
        self,
        store_dir: str,
        session_id: str = "",
        debounce_messages: int = 5,
        debounce_seconds: float = 30.0,
    ):
        self._store_dir = Path(store_dir)
        self._store_dir.mkdir(parents=True, exist_ok=True)
        self._session_id = session_id or f"conv-{int(time.time())}"
        self._debounce_messages = debounce_messages
        self._debounce_seconds = debounce_seconds
        self._lock = threading.Lock()

        # 每个 agent 独立的 debounce 状态
        self._last_save_ts: dict[str, float] = {}
        self._last_save_count: dict[str, int] = {}
        self._seq = 0

    def maybe_save(
        self,
        agent_name: str,
        conversation_history: list[dict],
        iteration: int = 0,
        metadata: dict | None = None,
    ) -> bool:
        """检查 debounce 条件，满足则保存快照。返回是否实际保存。

        debounce 判断和保存在同一把锁内完成，避免并发下重复保存。
        """
        with self._lock:
            now = time.time()
            msg_count = len(conversation_history)

            last_ts = self._last_save_ts.get(agent_name, 0.0)
            last_count = self._last_save_count.get(agent_name, 0)

            time_elapsed = now - last_ts >= self._debounce_seconds
            msgs_changed = msg_count - last_count >= self._debounce_messages

            if not (time_elapsed or msgs_changed):
                return False

            # 在锁内提前更新 debounce 状态，防止另一线程同时通过检查后重复保存
            self._last_save_ts[agent_name] = now
            self._last_save_count[agent_name] = msg_count

        self.save_snapshot(agent_name, conversation_history, iteration, metadata)
        return True

    def save_snapshot(
        self,
        agent_name: str,
        conversation_history: list[dict],
        iteration: int = 0,
        metadata: dict | None = None,
    ) -> ConversationSnapshot:
        """强制保存一个快照。
        
        注意：调用方 maybe_save 已在锁内提前更新过 debounce 计数器，
        此处不再覆盖，以保留 maybe_save 中采样到的精确时间戳。
        直接调用 save_snapshot（绕过 maybe_save）时同样需要更新计数器，
        所以在锁内有条件地更新：仅当 maybe_save 未提前写入时才写入。
        """
        with self._lock:
            self._seq += 1
            snapshot = ConversationSnapshot(
                snapshot_id=f"snap-{self._seq:04d}",
                ts=time.time(),
                agent=agent_name,
                iteration=iteration,
                message_count=len(conversation_history),
                messages=self._sanitize_messages(conversation_history),
                metadata=metadata or {},
            )

            log_file = self._store_dir / f"{self._session_id}.jsonl"
            try:
                with open(log_file, "a", encoding="utf-8") as f:
                    line = json.dumps(
                        snapshot.to_dict(), ensure_ascii=False, default=str,
                    )
                    f.write(line + "\n")
            except OSError as e:
                logger.error(f"ConversationStore 写入失败: {e}")

            # 仅当调用方（maybe_save）未提前写入计数器时才更新，避免覆盖更精确的值。
            # maybe_save 在锁外保存时写入的是 snapshot.message_count（与此处相同），
            # 直接调用 save_snapshot 时需要在此处同步 debounce 状态。
            current_count = self._last_save_count.get(agent_name, -1)
            if current_count != snapshot.message_count:
                self._last_save_ts[agent_name] = snapshot.ts
                self._last_save_count[agent_name] = snapshot.message_count

            logger.debug(
                f"对话快照保存: {agent_name} iter={iteration} "
                f"msgs={snapshot.message_count} id={snapshot.snapshot_id}"
            )
            return snapshot

    def load_latest(self, agent_name: str | None = None) -> ConversationSnapshot | None:
        """加载最近的快照（可按 agent 过滤）"""
        snapshots = self.list_snapshots(agent_name)
        return snapshots[-1] if snapshots else None

    def load_by_iteration(
        self, agent_name: str, iteration: int,
    ) -> ConversationSnapshot | None:
        """按迭代号加载快照"""
        for snap in reversed(self.list_snapshots(agent_name)):
            if snap.iteration == iteration:
                return snap
        return None

    def list_snapshots(
        self, agent_name: str | None = None,
    ) -> list[ConversationSnapshot]:
        """列出所有快照（按时间排序）"""
        log_file = self._store_dir / f"{self._session_id}.jsonl"
        if not log_file.exists():
            return []

        snapshots: list[ConversationSnapshot] = []
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        snap = ConversationSnapshot(**data)
                        if agent_name is None or snap.agent == agent_name:
                            snapshots.append(snap)
                    except (json.JSONDecodeError, TypeError):
                        continue
        except OSError:
            pass

        return snapshots

    def get_resume_context(self, agent_name: str) -> dict | None:
        """获取断点续传上下文

        返回最近快照的精简信息，可注入到 Agent 的 session context。
        不直接恢复 conversation_history（避免 token 膨胀），
        而是提供摘要供 Agent 参考。
        """
        snapshot = self.load_latest(agent_name)
        if not snapshot:
            return None

        # 提取关键信息：最后几条 assistant/tool 消息
        recent_msgs = []
        for msg in reversed(snapshot.messages[-6:]):
            role = msg.get("role", "")
            content = str(msg.get("content", ""))[:200]
            if role in ("assistant", "tool"):
                recent_msgs.append(f"[{role}] {content}")

        return {
            "snapshot_id": snapshot.snapshot_id,
            "iteration": snapshot.iteration,
            "message_count": snapshot.message_count,
            "ts": snapshot.ts,
            "recent_context": "\n".join(reversed(recent_msgs)),
            "metadata": snapshot.metadata,
        }

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def stats(self) -> dict[str, Any]:
        snapshots = self.list_snapshots()
        by_agent: dict[str, int] = {}
        for s in snapshots:
            by_agent[s.agent] = by_agent.get(s.agent, 0) + 1
        return {
            "session_id": self._session_id,
            "total_snapshots": len(snapshots),
            "by_agent": by_agent,
            "store_dir": str(self._store_dir),
        }

    @staticmethod
    def _sanitize_messages(messages: list[dict]) -> list[dict]:
        """清理消息，移除不可序列化的内容，截断过长 tool result"""
        sanitized = []
        for msg in messages:
            clean = {
                "role": msg.get("role", ""),
                "content": str(msg.get("content", "")) if msg.get("content") else "",
            }
            if "tool_call_id" in msg:
                clean["tool_call_id"] = msg["tool_call_id"]
            if "tool_calls" in msg:
                clean["tool_calls"] = msg["tool_calls"]
            if "reasoning_content" in msg:
                rc = str(msg["reasoning_content"])
                clean["reasoning_content"] = rc[:500] if len(rc) > 500 else rc
            # tool result 截断（节省存储）
            if clean["role"] == "tool" and len(clean["content"]) > 2000:
                clean["content"] = clean["content"][:1800] + "\n... (truncated)"
            sanitized.append(clean)
        return sanitized
