"""Agent 上下文管理 — JSON 校验 / 自我审查 / 历史压缩

两种压缩策略：
1. 滑动窗口（主动式）：每轮迭代检查，超过窗口大小时自动压缩旧轮次到增量摘要
2. 紧急压缩（被动式）：context_limit 溢出时的一次性全量压缩（兜底）
"""

import json
import logging
import re

logger = logging.getLogger("autoc.agent")

# 滑动窗口参数（按典型单轮 3-8 条消息校准）
_WINDOW_RECENT_MSGS = 12
_COMPRESS_TRIGGER_MSGS = 20

# 摘要块的统一标记前缀（滑动窗口和紧急压缩共用，用于 _split_summary_block 识别）
_SUMMARY_MARKER = "## 执行摘要"


class _ContextCompressMixin:
    """上下文压缩与输出校验（混入 BaseAgent）"""

    def _validate_json_output(self, output: str, required_fields: list[str] | None = None) -> dict | None:
        """校验 JSON 结构化输出 (去幻觉)"""
        json_str = output.strip()
        if json_str.startswith("```"):
            lines = json_str.split("\n")
            start = 0
            end = len(lines)
            for i, line in enumerate(lines):
                if line.strip().startswith("{"):
                    start = i
                    break
            for i in range(len(lines) - 1, -1, -1):
                if lines[i].strip().startswith("}"):
                    end = i + 1
                    break
            json_str = "\n".join(lines[start:end])

        data = None
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}', output, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group())
                except json.JSONDecodeError:
                    pass

        if data is None:
            logger.warning(f"[{self.name}] 输出不是有效的 JSON")
            return None

        if required_fields:
            missing = [f for f in required_fields if f not in data]
            if missing:
                logger.warning(f"[{self.name}] JSON 缺少必需字段: {missing}")
                return None

        return data

    def _estimate_tokens(self, messages: list[dict]) -> int:
        """改进的 token 估算：中文约 1.5 字符/token，英文约 4 字符/token。"""
        total_tokens = 0
        for m in messages:
            text = str(m.get("content", ""))
            if "tool_calls" in m:
                text += json.dumps(m["tool_calls"], ensure_ascii=False)
            cjk = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
            ascii_chars = len(text) - cjk
            total_tokens += int(cjk / 1.5 + ascii_chars / 4)
        return total_tokens

    # ========== 滑动窗口压缩（主动式，每轮调用） ==========

    def _sliding_window_compress(self):
        """滑动窗口：保留 system + running_summary + 最近 N 轮完整交互。

        与被动 _compress_history 的区别：
        - 每轮迭代调用，增量追加到 running_summary（O(1) 增长而非 O(N)）
        - 不等 context_limit 溢出才触发，窗口外的消息立即压缩
        - summary 累积式更新，不丢失早期关键信息
        """
        history = self.conversation_history
        if len(history) <= _COMPRESS_TRIGGER_MSGS:
            return

        system_msg = history[0]
        rest = history[1:]

        existing_summary, summary_ack, rest = self._split_summary_block(rest)

        if len(rest) <= _WINDOW_RECENT_MSGS:
            return

        split_idx = max(0, len(rest) - _WINDOW_RECENT_MSGS)
        while split_idx > 0:
            msg = rest[split_idx]
            role = msg.get("role")
            if role == "tool":
                split_idx -= 1
                continue
            if role == "assistant" and msg.get("tool_calls"):
                split_idx -= 1
                continue
            break
        if split_idx == 0:
            return

        to_compress = rest[:split_idx]
        recent = rest[split_idx:]

        new_summary = self._build_incremental_summary(existing_summary, to_compress)

        self.conversation_history = [
            system_msg,
            {"role": "user", "content": new_summary},
            {"role": "assistant", "content": "了解，继续。"},
        ] + recent

        compressed_count = len(to_compress)
        retained_count = len(recent)

        if self.trace_logger:
            self.trace_logger.log_event("sliding_window_compress", {
                "compressed_count": compressed_count,
                "retained_recent": retained_count,
                "summary_len": len(new_summary),
            })

        logger.info(
            f"[{self.name}] 滑动窗口压缩: {compressed_count} 条 → 增量摘要，"
            f"保留最近 {retained_count} 条"
        )

    @staticmethod
    def _split_summary_block(rest: list[dict]) -> tuple[str, dict | None, list[dict]]:
        """从 rest 开头提取已有的 running_summary + ack（滑动窗口或紧急压缩产出）。"""
        if (
            len(rest) >= 2
            and rest[0].get("role") == "user"
            and _SUMMARY_MARKER in str(rest[0].get("content", ""))
            and rest[1].get("role") == "assistant"
        ):
            return str(rest[0]["content"]), rest[1], rest[2:]
        return "", None, rest

    def _build_incremental_summary(self, existing: str, new_msgs: list[dict]) -> str:
        """增量构建 running_summary：从新消息提取结构化信息，合并到已有摘要。"""
        written: list[str] = []
        commands: list[str] = []
        errors: list[str] = []
        decisions: list[str] = []
        tc_lookup: dict[str, dict] = {}

        for msg in new_msgs:
            role = msg.get("role", "")
            content = str(msg.get("content", ""))

            if role == "assistant":
                if "tool_calls" in msg:
                    for tc in msg.get("tool_calls", []):
                        fn = tc.get("function", {})
                        name = fn.get("name", "")
                        try:
                            args = json.loads(fn.get("arguments", "{}"))
                        except Exception:
                            args = {}
                        tc_lookup[tc.get("id", "")] = {"name": name, "args": args}
                elif content and len(content) > 30:
                    decisions.append(content[:80])

            elif role == "tool":
                tc_id = msg.get("tool_call_id", "")
                tc_info = tc_lookup.get(tc_id, {})
                name = tc_info.get("name", "")
                args = tc_info.get("args", {})
                is_err = any(kw in content for kw in [
                    "[错误]", "[超时]", "Traceback", "Error:", "FAILED",
                ])
                if name in ("write_file", "create_directory"):
                    written.append(args.get("path", "?"))
                elif name == "execute_command":
                    cmd = args.get("command", "?")[:60]
                    commands.append(f"{cmd} [{'✗' if is_err else '✓'}]")
                if is_err:
                    errors.append(f"[{name}] {content[:80]}")

        delta_parts: list[str] = []
        if written:
            delta_parts.append(f"文件: {', '.join(written)}")
        if commands:
            delta_parts.append("命令: " + "; ".join(commands[-4:]))
        if errors:
            delta_parts.append("错误: " + "; ".join(errors[-2:]))
        if decisions:
            delta_parts.append("决策: " + decisions[-1])
        delta = " | ".join(delta_parts) if delta_parts else "(无显著操作)"

        if existing:
            prev_lines = existing.strip().split("\n")
            round_lines = [l for l in prev_lines if l.startswith("- R")]
            round_num = len(round_lines) + 1
            return (
                existing.rstrip()
                + f"\n- R{round_num}: {delta}"
            )

        return (
            f"{_SUMMARY_MARKER}（迭代 1-{self._iteration_count}）\n"
            f"Agent: {self.name}\n"
            f"- R1: {delta}"
        )

    # ========== 紧急压缩（被动式，context_limit 溢出兜底） ==========

    def _compress_history(self):
        """紧急压缩：context_limit 溢出时的全量一次性压缩。

        正常情况下滑动窗口已经控制了历史长度，这里只在极端情况触发。
        """
        recent_count = _WINDOW_RECENT_MSGS
        if len(self.conversation_history) <= recent_count + 2:
            return

        system_msg = self.conversation_history[0]
        rest = self.conversation_history[1:]

        split_idx = max(0, len(rest) - recent_count)
        while split_idx > 0:
            msg = rest[split_idx]
            role = msg.get("role")
            if role == "tool":
                split_idx -= 1
                continue
            if role == "assistant" and msg.get("tool_calls"):
                split_idx -= 1
                continue
            break

        middle = rest[:split_idx]
        recent = rest[split_idx:]

        if not middle:
            return

        written_files: list[str] = []
        commands: list[str] = []
        errors: list[str] = []
        tc_lookup: dict[str, dict] = {}

        for msg in middle:
            role = msg.get("role", "")
            content = str(msg.get("content", ""))
            if role == "assistant" and "tool_calls" in msg:
                for tc in msg.get("tool_calls", []):
                    fn = tc.get("function", {})
                    name = fn.get("name", "")
                    try:
                        args = json.loads(fn.get("arguments", "{}"))
                    except Exception:
                        args = {}
                    tc_lookup[tc.get("id", "")] = {"name": name, "args": args}
            elif role == "tool":
                tc_id = msg.get("tool_call_id", "")
                tc_info = tc_lookup.get(tc_id, {})
                name = tc_info.get("name", "")
                args = tc_info.get("args", {})
                is_err = any(kw in content for kw in [
                    "[错误]", "[超时]", "Traceback", "Error:", "FAILED",
                ])
                if name in ("write_file", "create_directory"):
                    written_files.append(args.get("path", "?"))
                elif name == "execute_command":
                    cmd = args.get("command", "?")[:60]
                    commands.append(f"{cmd} [{'✗' if is_err else '✓'}]")
                if is_err:
                    errors.append(f"[{name}] {content[:100]}")

        parts = [f"{_SUMMARY_MARKER}（紧急压缩 {len(middle)} 条）"]
        parts.append(f"Agent: {self.name}, 迭代: {self._iteration_count}")
        if written_files:
            parts.append(f"文件: {', '.join(set(written_files))}")
        if commands:
            parts.append("命令: " + "; ".join(commands[-5:]))
        if errors:
            parts.append("错误: " + "; ".join(errors[-3:]))

        summary = "\n".join(parts)

        self.conversation_history = [
            system_msg,
            {"role": "user", "content": f"{summary}\n\n请继续执行当前任务。"},
            {"role": "assistant", "content": "了解，继续。"},
        ] + recent

        if self.trace_logger:
            self.trace_logger.log_event("emergency_compress", {
                "compressed_count": len(middle),
                "retained_recent": len(recent),
            })

        logger.info(
            f"[{self.name}] 紧急压缩: {len(middle)} 条 → 摘要，保留最近 {len(recent)} 条"
        )
