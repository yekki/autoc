"""EventLog — Append-Only JSONL 统一事件日志

参考 OpenHands Event System 设计：
- 所有事件写入单一 JSONL 文件，按时间排序
- 支持按类型、Agent、时间范围查询
- 可作为 Condenser 的上下文输入源
- 线程安全写入（单写入锁）

事件结构：
{
    "ts": 1700000000.123,       # Unix 时间戳
    "seq": 42,                   # 全局递增序号
    "type": "tool_call",         # 事件类型
    "agent": "main",             # 来源 Agent
    "session_id": "abc123",      # 会话 ID
    "data": {...}                # 事件负载
}
"""

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

logger = logging.getLogger("autoc.event_log")


@dataclass
class Event:
    """单个事件"""
    ts: float
    seq: int
    type: str
    agent: str = ""
    session_id: str = ""
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)


IMMEDIATE_FLUSH_TYPES = frozenset({
    "tool_call_result", "task_completed", "task_failed",
    "status_change", "error", "session_end",
})


class EventLog:
    """Append-Only 事件日志

    用法：
        log = EventLog("/path/to/workspace/.autoc-events")
        log.append("tool_call", agent="main", data={"tool": "write_file"})
        events = log.query(event_type="tool_call", since=time.time() - 3600)
    """

    def __init__(self, log_dir: str, session_id: str = ""):
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._session_id = session_id or f"s-{int(time.time())}"
        self._log_file = self._log_dir / f"{self._session_id}.jsonl"
        self._seq = self._recover_seq()
        self._lock = threading.Lock()
        self._buffer: list[Event] = []
        self._flush_threshold = 10

    def _recover_seq(self) -> int:
        """从已有日志文件末行恢复 _seq，防止进程重启后序号重置导致同 session 序号重复。

        优先 seek 从文件末尾读 8KB 解析最后一行（O(1)），若截断导致 JSON 解析失败
        则 fallback 到全文逐行扫描确保正确性。
        """
        if not self._log_file.exists():
            return 0
        try:
            file_size = self._log_file.stat().st_size
            if file_size == 0:
                return 0
            # 快速路径：从末尾读取 8KB，覆盖绝大多数单行 JSON
            chunk_size = min(8192, file_size)
            with open(self._log_file, "rb") as f:
                f.seek(-chunk_size, 2)  # 2 = os.SEEK_END
                tail = f.read(chunk_size).decode("utf-8", errors="ignore")
            last_line = next(
                (ln.strip() for ln in reversed(tail.splitlines()) if ln.strip()),
                "",
            )
            if last_line:
                try:
                    data = json.loads(last_line)
                    return int(data.get("seq", 0))
                except (json.JSONDecodeError, ValueError):
                    pass  # 截断导致解析失败，走 fallback
            # 慢速 fallback：全文逐行扫描（仅当 seek 路径失败时触发）
            last_line = ""
            with open(self._log_file, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped:
                        last_line = stripped
            if last_line:
                data = json.loads(last_line)
                return int(data.get("seq", 0))
        except Exception:
            pass
        return 0

    def append(
        self,
        event_type: str,
        agent: str = "",
        data: dict | None = None,
    ) -> Event:
        """追加一条事件"""
        with self._lock:
            self._seq += 1
            event = Event(
                ts=time.time(),
                seq=self._seq,
                type=event_type,
                agent=agent,
                session_id=self._session_id,
                data=data or {},
            )
            self._buffer.append(event)
            # 关键事件立即持久化，普通事件批量 flush
            if event.type in IMMEDIATE_FLUSH_TYPES or len(self._buffer) >= self._flush_threshold:
                self._flush()
            return event

    def flush(self) -> None:
        """手动刷新缓冲区到磁盘"""
        with self._lock:
            self._flush()

    def query(
        self,
        event_type: str | None = None,
        agent: str | None = None,
        since: float | None = None,
        limit: int = 100,
    ) -> list[Event]:
        """查询事件（从缓冲区 + 磁盘）"""
        self.flush()
        events: list[Event] = []

        if self._log_file.exists():
            with open(self._log_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        event = Event(**d)
                        if self._match(event, event_type, agent, since):
                            events.append(event)
                    except (json.JSONDecodeError, TypeError):
                        continue

        if len(events) > limit:
            events = events[-limit:]

        return events

    def export_for_condenser(self, max_events: int = 50) -> str:
        """导出事件摘要，供 Condenser 使用"""
        events = self.query(limit=max_events)
        if not events:
            return ""

        lines = [f"[EventLog] 最近 {len(events)} 条事件:"]
        for e in events[-max_events:]:
            ts_str = time.strftime("%H:%M:%S", time.localtime(e.ts))
            agent_str = f"[{e.agent}]" if e.agent else ""
            data_str = ""
            if e.data:
                data_str = " " + json.dumps(
                    e.data, ensure_ascii=False, default=str,
                )[:120]
            lines.append(f"  #{e.seq} {ts_str} {agent_str} {e.type}{data_str}")

        return "\n".join(lines)

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def event_count(self) -> int:
        return self._seq

    @property
    def stats(self) -> dict[str, Any]:
        """返回事件统计"""
        events = self.query(limit=10000)
        type_counts: dict[str, int] = {}
        agent_counts: dict[str, int] = {}
        for e in events:
            type_counts[e.type] = type_counts.get(e.type, 0) + 1
            if e.agent:
                agent_counts[e.agent] = agent_counts.get(e.agent, 0) + 1
        return {
            "total_events": len(events),
            "session_id": self._session_id,
            "by_type": type_counts,
            "by_agent": agent_counts,
        }

    def _flush(self) -> None:
        """内部刷新（调用者已持有锁）"""
        if not self._buffer:
            return
        try:
            with open(self._log_file, "a", encoding="utf-8") as f:
                for event in self._buffer:
                    f.write(event.to_json() + "\n")
            self._buffer.clear()
        except OSError as e:
            logger.error(f"EventLog 写入失败: {e}")

    @staticmethod
    def _match(
        event: Event,
        event_type: str | None,
        agent: str | None,
        since: float | None,
    ) -> bool:
        if event_type and event.type != event_type:
            return False
        if agent and event.agent != agent:
            return False
        if since and event.ts < since:
            return False
        return True
