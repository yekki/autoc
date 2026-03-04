"""Stuck Detector — Agent 级别的停滞检测

参考 OpenHands Stuck Detection 设计：
- 滑动窗口模式匹配，识别 Agent 行为循环
- 多维度检测：重复调用 / 循环模式 / 错误重复 / 空产出 / 独白
- 与 CircuitBreaker（Loop 级）互补，覆盖 Agent 内部微循环

检测模式：
1. RepeatCall: 连续 N 次相同工具+参数调用（默认 3 次）
2. CyclicPattern: A→B→A→B 交替循环（默认 2 轮完整循环）
3. ErrorRepeat: 相同错误消息连续出现 N 次（默认 3 次）
4. EmptyOutput: 连续 N 次工具调用无实质产出（默认 5 次）
5. ContextOverflow: Context Window 超限死循环（默认 2 次）
6. AlternatingAction: 同一工具在两组参数间振荡（默认 3 次）
7. Monologue: 连续 N 轮无工具调用（Agent 只说话不行动，默认 3 轮）

分级恢复：
- severity=1 (首次): 注入文字提示（轻量）
- severity=2 (二次): 自动调用 helper + 截断循环历史（中度）
- severity=3+ (持续): 上报 Orchestrator 触发任务级决策（重度）
"""

import hashlib
import logging
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("autoc.stuck_detector")


class StuckPattern(str, Enum):
    REPEAT_CALL = "repeat_call"
    CYCLIC_PATTERN = "cyclic_pattern"
    ERROR_REPEAT = "error_repeat"
    EMPTY_OUTPUT = "empty_output"
    CONTEXT_OVERFLOW = "context_overflow"
    ALTERNATING_ACTION = "alternating_action"
    MONOLOGUE = "monologue"        # 参考 OpenHands 场景 3：Agent 连续只说话不行动


@dataclass
class StuckSignal:
    """停滞检测信号"""
    pattern: StuckPattern
    confidence: float  # 0.0 ~ 1.0
    description: str
    suggestion: str
    window_size: int = 0
    severity: int = 1   # 1=轻度(首次) 2=中度(二次) 3+=重度(持续)，由 StuckDetector 在返回前设置


@dataclass
class ToolCallRecord:
    """单次工具调用记录"""
    tool_name: str
    args_hash: str
    has_error: bool = False
    error_message: str = ""
    output_length: int = 0
    is_write: bool = False
    is_no_tool: bool = False  # True 表示本轮 LLM 未调用任何工具（独白检测用）


class StuckDetector:
    """Agent 级别的停滞检测器

    用法：
        detector = StuckDetector()
        detector.record("write_file", {"path": "a.py", "content": "..."}, result, False)
        stuck, signal = detector.check()
        if stuck:
            print(signal.description)
    """

    _CONTEXT_OVERFLOW_KEYWORDS = frozenset([
        "context_length_exceeded", "maximum context length",
        "token limit", "context window", "max_tokens",
        "reduce the length", "too many tokens",
    ])

    def __init__(
        self,
        repeat_threshold: int = 3,
        cycle_threshold: int = 2,
        error_repeat_threshold: int = 3,
        empty_output_threshold: int = 5,
        context_overflow_threshold: int = 2,
        alternating_threshold: int = 3,
        monologue_threshold: int = 3,
        window_size: int = 20,
    ):
        self._repeat_threshold = repeat_threshold
        self._cycle_threshold = cycle_threshold
        self._error_repeat_threshold = error_repeat_threshold
        self._empty_output_threshold = empty_output_threshold
        self._context_overflow_threshold = context_overflow_threshold
        self._alternating_threshold = alternating_threshold
        self._monologue_threshold = monologue_threshold
        self._window_size = window_size
        self._records: list[ToolCallRecord] = []
        self._total_checks: int = 0
        self._total_stuck: int = 0
        # 连续 stuck 计数（reset 时清零），用于分级恢复
        self._consecutive_stuck_count: int = 0

    def record(
        self,
        tool_name: str,
        arguments: dict,
        result: str = "",
        has_error: bool = False,
        error_message: str = "",
    ) -> None:
        """记录一次工具调用"""
        args_hash = self._hash_args(tool_name, arguments)
        is_write = tool_name in (
            "write_file", "create_directory", "execute_command",
            "format_code", "git_commit",
            "submit_critique", "submit_test_report",
        )
        record = ToolCallRecord(
            tool_name=tool_name,
            args_hash=args_hash,
            has_error=has_error,
            error_message=error_message[:200] if error_message else "",
            output_length=len(result) if result else 0,
            is_write=is_write,
            is_no_tool=(tool_name == "__no_tool__"),
        )
        self._records.append(record)
        if len(self._records) > self._window_size * 2:
            self._records = self._records[-self._window_size:]

    def record_no_tool(self) -> None:
        """记录一轮 LLM 未调用任何工具（独白轮次），用于 MONOLOGUE 检测"""
        record = ToolCallRecord(
            tool_name="__no_tool__",
            args_hash="",
            is_no_tool=True,
        )
        self._records.append(record)
        if len(self._records) > self._window_size * 2:
            self._records = self._records[-self._window_size:]

    def check(self) -> tuple[bool, StuckSignal | None]:
        """执行停滞检测，返回 (是否停滞, 信号详情)。

        信号的 severity 由 _consecutive_stuck_count 决定：
          1 = 首次检测到（轻度）
          2 = 连续第 2 次（中度，触发 helper 自动咨询）
          3+ = 连续第 3 次及以上（重度，上报 Orchestrator）
        相邻两次 check() 之间如有工具调用成功，则 _consecutive_stuck_count 由
        reset_consecutive() 方法外部重置。
        """
        self._total_checks += 1
        window = self._records[-self._window_size:]
        if len(window) < self._repeat_threshold:
            return False, None

        # 按优先级检测（context overflow 最高，monologue 紧次，其余按可信度排序）
        for detector in [
            self._detect_context_overflow,
            self._detect_monologue,
            self._detect_repeat_call,
            self._detect_alternating_action,
            self._detect_cyclic_pattern,
            self._detect_error_repeat,
            self._detect_empty_output,
        ]:
            signal = detector(window)
            if signal:
                self._total_stuck += 1
                self._consecutive_stuck_count += 1
                signal.severity = self._consecutive_stuck_count
                logger.warning(
                    f"停滞检测[severity={signal.severity}]: {signal.pattern.value} — "
                    f"{signal.description} (confidence={signal.confidence:.0%})"
                )
                return True, signal

        # 本轮未检测到 stuck，重置连续计数（非完全清零，防止假阴性干扰）
        if self._consecutive_stuck_count > 0:
            self._consecutive_stuck_count = max(0, self._consecutive_stuck_count - 1)
        return False, None

    def check_monologue_only(self) -> StuckSignal | None:
        """仅检测 MONOLOGUE 模式（无工具调用场景专用）。

        当 LLM 不返回 tool_calls 时，调用此方法而非 check()，
        避免将历史工具调用的残留 pattern 误判为"任务未完成"。
        severity 同样由 _consecutive_stuck_count 管理。
        """
        self._total_checks += 1
        window = self._records[-self._window_size:]
        signal = self._detect_monologue(window)
        if signal:
            self._total_stuck += 1
            self._consecutive_stuck_count += 1
            signal.severity = self._consecutive_stuck_count
            logger.warning(
                f"停滞检测[monologue，severity={signal.severity}]: "
                f"{signal.description} (confidence={signal.confidence:.0%})"
            )
            return signal
        if self._consecutive_stuck_count > 0:
            self._consecutive_stuck_count = max(0, self._consecutive_stuck_count - 1)
        return None

    def reset_consecutive(self) -> None:
        """外部主动重置连续 stuck 计数（本轮无 stuck 且全部工具成功时调用）"""
        self._consecutive_stuck_count = 0

    def reset(self) -> None:
        """重置检测器（新任务开始时调用）"""
        self._records.clear()
        self._consecutive_stuck_count = 0

    @property
    def stats(self) -> dict:
        return {
            "total_records": len(self._records),
            "total_checks": self._total_checks,
            "total_stuck": self._total_stuck,
            "stuck_rate": (
                self._total_stuck / self._total_checks
                if self._total_checks > 0 else 0.0
            ),
        }

    def _detect_repeat_call(self, window: list[ToolCallRecord]) -> StuckSignal | None:
        """检测连续相同工具+参数调用"""
        if len(window) < self._repeat_threshold:
            return None

        tail = window[-self._repeat_threshold:]
        first_hash = tail[0].args_hash
        if all(r.args_hash == first_hash for r in tail):
            tool_name = tail[0].tool_name
            repeat_count = 0
            for r in reversed(window):
                if r.args_hash == first_hash:
                    repeat_count += 1
                else:
                    break
            confidence = min(1.0, repeat_count / (self._repeat_threshold + 2))
            return StuckSignal(
                pattern=StuckPattern.REPEAT_CALL,
                confidence=confidence,
                description=(
                    f"连续 {repeat_count} 次调用 {tool_name}（相同参数）"
                ),
                suggestion=f"停止重复调用 {tool_name}，尝试不同的方法或参数",
                window_size=repeat_count,
            )
        return None

    def _detect_cyclic_pattern(self, window: list[ToolCallRecord]) -> StuckSignal | None:
        """检测循环模式：A→B→A→B 或 A→B→C→A→B→C

        仅当 pattern 包含 >=2 种不同工具时才算循环；
        同一工具连续调用不同参数（如 write_file 创建多个文件）不是循环。
        """
        if len(window) < 4:
            return None

        names = [r.tool_name for r in window[-12:]]
        for cycle_len in range(2, min(5, len(names) // 2 + 1)):
            pattern = names[-cycle_len:]
            if len(set(pattern)) < 2:
                continue
            cycles_found = 0
            pos = len(names) - cycle_len
            while pos >= cycle_len:
                candidate = names[pos - cycle_len: pos]
                if candidate == pattern:
                    cycles_found += 1
                    pos -= cycle_len
                else:
                    break

            if cycles_found >= self._cycle_threshold:
                total_in_cycle = (cycles_found + 1) * cycle_len
                pattern_str = " → ".join(pattern)
                confidence = min(1.0, cycles_found / (self._cycle_threshold + 1))
                return StuckSignal(
                    pattern=StuckPattern.CYCLIC_PATTERN,
                    confidence=confidence,
                    description=(
                        f"检测到循环模式: [{pattern_str}] 重复 {cycles_found + 1} 次"
                    ),
                    suggestion="打破循环：跳过当前方法，尝试完全不同的策略",
                    window_size=total_in_cycle,
                )
        return None

    def _detect_error_repeat(self, window: list[ToolCallRecord]) -> StuckSignal | None:
        """检测相同错误消息重复出现"""
        error_records = [r for r in window if r.has_error and r.error_message]
        if len(error_records) < self._error_repeat_threshold:
            return None

        tail_errors = error_records[-self._error_repeat_threshold:]
        first_msg = tail_errors[0].error_message
        if all(r.error_message == first_msg for r in tail_errors):
            consecutive = 0
            for r in reversed(error_records):
                if r.error_message == first_msg:
                    consecutive += 1
                else:
                    break
            confidence = min(1.0, consecutive / (self._error_repeat_threshold + 2))
            return StuckSignal(
                pattern=StuckPattern.ERROR_REPEAT,
                confidence=confidence,
                description=(
                    f"相同错误连续出现 {consecutive} 次: "
                    f"{first_msg[:80]}..."
                ),
                suggestion="错误反复出现，需要分析根本原因而非重试",
                window_size=consecutive,
            )
        return None

    def _detect_empty_output(self, window: list[ToolCallRecord]) -> StuckSignal | None:
        """检测连续无实质产出（写操作次数为 0）"""
        if len(window) < self._empty_output_threshold:
            return None

        tail = window[-self._empty_output_threshold:]
        if not any(r.is_write for r in tail):
            no_write_count = 0
            for r in reversed(window):
                if not r.is_write:
                    no_write_count += 1
                else:
                    break
            if no_write_count >= self._empty_output_threshold:
                confidence = min(
                    1.0,
                    no_write_count / (self._empty_output_threshold + 3),
                )
                return StuckSignal(
                    pattern=StuckPattern.EMPTY_OUTPUT,
                    confidence=confidence,
                    description=(
                        f"连续 {no_write_count} 次工具调用无写操作"
                    ),
                    suggestion="过多探索无产出，请开始编写代码或执行命令",
                    window_size=no_write_count,
                )
        return None

    def _detect_monologue(self, window: list[ToolCallRecord]) -> StuckSignal | None:
        """检测独白模式：Agent 连续多轮只输出文字，不调用任何工具。

        参考 OpenHands 场景 3（Monologue）：连续 N 个 no-tool 轮次且之间无工具调用。
        只统计 is_no_tool 记录，正常工具调用会打断独白计数。
        """
        no_tool_count = 0
        for r in reversed(window):
            if r.is_no_tool:
                no_tool_count += 1
            else:
                break

        if no_tool_count >= self._monologue_threshold:
            confidence = min(1.0, no_tool_count / (self._monologue_threshold + 2))
            return StuckSignal(
                pattern=StuckPattern.MONOLOGUE,
                confidence=confidence,
                description=f"Agent 连续 {no_tool_count} 轮未调用任何工具（只说话不行动）",
                suggestion="停止分析，立即选择一个工具执行具体操作",
                window_size=no_tool_count,
            )
        return None

    def _detect_context_overflow(self, window: list[ToolCallRecord]) -> StuckSignal | None:
        """检测 Context Window 超限死循环（Condenser 失效时：反复超限→压缩→仍超限）"""
        overflow_count = 0
        for r in reversed(window):
            if r.has_error and any(kw in r.error_message.lower() for kw in self._CONTEXT_OVERFLOW_KEYWORDS):
                overflow_count += 1
            elif r.has_error:
                break
            else:
                break

        if overflow_count >= self._context_overflow_threshold:
            return StuckSignal(
                pattern=StuckPattern.CONTEXT_OVERFLOW,
                confidence=min(1.0, overflow_count / (self._context_overflow_threshold + 1)),
                description=f"Context Window 超限连续出现 {overflow_count} 次（Condenser 可能失效）",
                suggestion="强制重置对话历史或切换到更激进的压缩策略",
                window_size=overflow_count,
            )
        return None

    def _detect_alternating_action(self, window: list[ToolCallRecord]) -> StuckSignal | None:
        """检测交替动作模式：相同工具+不同参数的 A-B-A-B 循环（如 add→remove→add→remove）

        与 CyclicPattern（工具名循环）的区别：AlternatingAction 检测同一工具的参数振荡。
        """
        if len(window) < self._alternating_threshold * 2:
            return None

        tail = window[-(self._alternating_threshold * 2):]
        tool_names = [r.tool_name for r in tail]
        if len(set(tool_names)) != 1:
            return None

        hashes = [r.args_hash for r in tail]
        unique_hashes = set(hashes)
        if len(unique_hashes) != 2:
            return None

        hash_list = list(unique_hashes)
        expected_a = hash_list[0] if hashes[0] == hash_list[0] else hash_list[1]
        expected_b = hash_list[1] if expected_a == hash_list[0] else hash_list[0]

        alternating = True
        for i, h in enumerate(hashes):
            expected = expected_a if i % 2 == 0 else expected_b
            if h != expected:
                alternating = False
                break

        if alternating:
            return StuckSignal(
                pattern=StuckPattern.ALTERNATING_ACTION,
                confidence=min(1.0, len(tail) / (self._alternating_threshold * 2 + 2)),
                description=f"交替动作检测: {tool_names[0]} 在两组参数间振荡 {len(tail) // 2} 次",
                suggestion="停止交替修改，分析两个方案的根本差异后选定一个",
                window_size=len(tail),
            )
        return None

    @staticmethod
    def _hash_args(tool_name: str, arguments: dict) -> str:
        """生成工具调用的唯一指纹（嵌套 dict 安全）"""
        import json as _json
        raw = f"{tool_name}:{_json.dumps(arguments, sort_keys=True, default=str)}"
        return hashlib.md5(raw.encode(), usedforsecurity=False).hexdigest()[:12]
