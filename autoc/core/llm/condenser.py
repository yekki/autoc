"""Condenser — 对话历史动态压缩策略

参考 OpenHands Condenser 设计：
- 可插拔策略: NoOp / SlidingWindow / LLM / Hybrid
- Agent 级配置: 不同 agent 可使用不同压缩策略
- 压缩质量保证: LLM 压缩保留关键决策和错误信息

策略选择指南：
- NoOp: 短对话（< 12 条消息），无需压缩
- SlidingWindow: 默认策略，低成本，适合大多数场景
- LLM: 高质量压缩，适合需要保留深层上下文的长任务
- Hybrid: 先 SlidingWindow 控制规模，再 LLM 精炼摘要
"""

import json
import re
import logging
from abc import ABC, abstractmethod

logger = logging.getLogger("autoc.condenser")

_SUMMARY_MARKER = "## 执行摘要"
_WINDOW_RECENT_MSGS = 10   # 保留最近 5 次工具交互（原 12，略降）
_COMPRESS_TRIGGER_MSGS = 12  # 第 6 次工具交互后触发（原 20，显著降低；比 8 更安全）


class Condenser(ABC):
    """上下文压缩器基类"""

    @abstractmethod
    def condense(
        self,
        messages: list[dict],
        agent_name: str = "",
        iteration: int = 0,
    ) -> list[dict]:
        """压缩消息列表，返回压缩后的消息列表

        Args:
            messages: 完整的对话历史（含 system message）
            agent_name: 当前 agent 名称
            iteration: 当前迭代轮次

        Returns:
            压缩后的消息列表（保留 system message）
        """
        ...

    @property
    def strategy_name(self) -> str:
        return self.__class__.__name__


class NoOpCondenser(Condenser):
    """不压缩，原样返回"""

    def condense(self, messages, agent_name="", iteration=0):
        return messages


class SlidingWindowCondenser(Condenser):
    """滑动窗口压缩 — 保留最近 N 条消息，旧消息提取结构化摘要

    与 context_compress.py 中的 _sliding_window_compress 逻辑一致，
    但提取为独立可复用的策略类。
    """

    def __init__(
        self,
        window_size: int = _WINDOW_RECENT_MSGS,
        trigger_threshold: int = _COMPRESS_TRIGGER_MSGS,
    ):
        self._window_size = window_size
        self._trigger = trigger_threshold

    def condense(self, messages, agent_name="", iteration=0):
        if not messages or messages[0].get("role") != "system":
            return messages  # 无法安全压缩，原样返回

        if len(messages) <= self._trigger:
            return messages

        system_msg = messages[0]
        rest = messages[1:]

        existing_summary, _, rest = _split_summary_block(rest)

        if len(rest) <= self._window_size:
            return messages

        split_idx = max(0, len(rest) - self._window_size)
        while split_idx > 0 and rest[split_idx].get("role") == "tool":
            split_idx -= 1
        if split_idx == 0:
            return messages

        to_compress = rest[:split_idx]
        recent = rest[split_idx:]
        new_summary = _build_structural_summary(
            existing_summary, to_compress, agent_name, iteration,
        )

        logger.info(
            f"[{agent_name}] SlidingWindow: {len(to_compress)} 条 → 摘要，"
            f"保留 {len(recent)} 条"
        )

        return [
            system_msg,
            {"role": "user", "content": new_summary},
            {"role": "assistant", "content": "了解，继续。"},
        ] + recent


class LLMCondenser(Condenser):
    """LLM 驱动的智能压缩 — 用 LLM 总结旧消息，保留关键上下文

    优点: 压缩质量高，能理解语义，保留重要决策和错误模式
    缺点: 每次压缩消耗额外 token（~200-500 tokens）
    """

    def __init__(
        self,
        llm_client,
        window_size: int = _WINDOW_RECENT_MSGS,
        trigger_threshold: int = _COMPRESS_TRIGGER_MSGS,
        max_summary_tokens: int = 500,
    ):
        self._llm = llm_client
        self._window_size = window_size
        self._trigger = trigger_threshold
        self._max_summary_tokens = max_summary_tokens

    def condense(self, messages, agent_name="", iteration=0):
        if not messages or messages[0].get("role") != "system":
            return messages  # 无法安全压缩，原样返回

        if len(messages) <= self._trigger:
            return messages

        system_msg = messages[0]
        rest = messages[1:]

        existing_summary, _, rest = _split_summary_block(rest)

        if len(rest) <= self._window_size:
            return messages

        split_idx = max(0, len(rest) - self._window_size)
        while split_idx > 0 and rest[split_idx].get("role") == "tool":
            split_idx -= 1
        if split_idx == 0:
            return messages

        to_compress = rest[:split_idx]
        recent = rest[split_idx:]

        try:
            new_summary = self._llm_summarize(
                existing_summary, to_compress, agent_name, iteration,
            )
        except Exception as e:
            logger.warning(f"LLM 压缩失败，降级为结构化摘要: {e}")
            new_summary = _build_structural_summary(
                existing_summary, to_compress, agent_name, iteration,
            )

        logger.info(
            f"[{agent_name}] LLMCondenser: {len(to_compress)} 条 → LLM 摘要，"
            f"保留 {len(recent)} 条"
        )

        return [
            system_msg,
            {"role": "user", "content": new_summary},
            {"role": "assistant", "content": "了解，继续。"},
        ] + recent

    def _llm_summarize(
        self, existing: str, msgs: list[dict], agent_name: str, iteration: int,
    ) -> str:
        """用 LLM 总结旧消息"""
        content_parts = []
        for msg in msgs:
            role = msg.get("role", "")
            content = str(msg.get("content", ""))[:200]
            if role == "assistant" and "tool_calls" in msg:
                calls = msg.get("tool_calls", [])
                call_names = [tc.get("function", {}).get("name", "?") for tc in calls]
                content_parts.append(f"[assistant 调用工具: {', '.join(call_names)}]")
            elif role == "tool":
                content_parts.append(f"[工具结果: {content[:100]}]")
            elif content:
                content_parts.append(f"[{role}]: {content}")

        raw_context = "\n".join(content_parts[-30:])

        prompt = (
            f"你是 {agent_name} 的上下文压缩器。请将以下对话历史浓缩为关键摘要。\n\n"
            "必须保留的信息：\n"
            "1. 已创建/修改的文件及路径\n"
            "2. 执行过的关键命令及结果（成功/失败）\n"
            "3. 遇到的错误和已采取的修复措施\n"
            "4. 重要的架构/实现决策\n"
            "5. 当前任务的进展状态\n\n"
            "可以省略的信息：\n"
            "- 文件内容的具体代码\n"
            "- 成功命令的详细输出\n"
            "- 重复的操作\n\n"
        )
        if existing:
            prompt += f"已有摘要：\n{existing}\n\n"
        prompt += f"新的对话历史：\n{raw_context}\n\n请输出更新后的完整摘要（中文）："

        response = self._llm.chat(
            messages=[
                {"role": "system", "content": "你是上下文压缩专家，输出简洁的结构化摘要。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=self._max_summary_tokens,
        )
        summary = response.get("content", "").strip()
        if not summary:
            raise ValueError("LLM 返回空摘要")

        return f"{_SUMMARY_MARKER}（LLM 压缩，迭代 1-{iteration}）\n{summary}"


class HybridCondenser(Condenser):
    """混合策略 — 先用 SlidingWindow 控制规模，再用 LLM 精炼摘要

    适合长任务（> 30 轮迭代），在成本和质量之间取平衡。
    每 N 次 SlidingWindow 压缩后触发一次 LLM 精炼。
    """

    def __init__(
        self,
        llm_client,
        llm_refine_interval: int = 5,
        **kwargs,
    ):
        self._sliding = SlidingWindowCondenser(**kwargs)
        self._llm = LLMCondenser(llm_client, **kwargs)
        self._refine_interval = llm_refine_interval
        self._compress_count = 0

    def condense(self, messages, agent_name="", iteration=0):
        result = self._sliding.condense(messages, agent_name, iteration)
        if len(result) < len(messages):
            self._compress_count += 1
            if self._compress_count % self._refine_interval == 0:
                result = self._llm.condense(result, agent_name, iteration)
        return result


def create_condenser(
    strategy: str = "sliding_window",
    llm_client=None,
    **kwargs,
) -> Condenser:
    """工厂函数 — 根据策略名创建 Condenser 实例

    Args:
        strategy: "noop" | "sliding_window" | "llm" | "hybrid"
        llm_client: LLM 策略需要的 LLMClient 实例
        **kwargs: 传递给具体策略的参数
    """
    strategies = {
        "noop": lambda: NoOpCondenser(),
        "sliding_window": lambda: SlidingWindowCondenser(**kwargs),
        "llm": lambda: LLMCondenser(llm_client, **kwargs),
        "hybrid": lambda: HybridCondenser(llm_client, **kwargs),
    }
    factory = strategies.get(strategy)
    if factory is None:
        logger.warning(f"未知 Condenser 策略 '{strategy}'，降级为 sliding_window")
        return SlidingWindowCondenser(**kwargs)
    return factory()


# ========== 共享工具函数 ==========

def _split_summary_block(
    rest: list[dict],
) -> tuple[str, dict | None, list[dict]]:
    """从消息序列开头提取已有的 running_summary + ack"""
    if (
        len(rest) >= 2
        and rest[0].get("role") == "user"
        and _SUMMARY_MARKER in str(rest[0].get("content", ""))
        and rest[1].get("role") == "assistant"
    ):
        return str(rest[0]["content"]), rest[1], rest[2:]
    return "", None, rest


def _build_structural_summary(
    existing: str,
    msgs: list[dict],
    agent_name: str,
    iteration: int,
) -> str:
    """从消息中提取结构化摘要（文件/命令/错误/决策）"""
    written: list[str] = []
    commands: list[str] = []
    errors: list[str] = []
    decisions: list[str] = []
    tc_lookup: dict[str, dict] = {}

    for msg in msgs:
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
                path = args.get("path", "?")
                content_len = len(args.get("content", ""))
                written.append(f"{path}({content_len}B)" if content_len else path)
            elif name == "edit_file":
                path = args.get("path", "?")
                new_len = len(args.get("new_str", ""))
                written.append(f"{path}[edit,{new_len}B]")
            elif name == "execute_command":
                cmd = args.get("command", "?")[:60]
                commands.append(f"{cmd} [{'✗' if is_err else '✓'}]")
            if is_err:
                # 保留更多错误上下文：用正则提取 Traceback 最后一行异常
                # [\w.]+ 支持带包名前缀的全限定类名（如 sqlalchemy.exc.OperationalError）
                err_text = content[:200]
                tb_lines = [
                    l for l in content.splitlines()
                    if re.match(r'^\s*[\w.]+(?:Error|Exception|Warning|Fault)\b', l)
                ]
                if tb_lines:
                    err_text = tb_lines[-1].strip()[:200]
                errors.append(f"[{name}] {err_text}")

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
        round_lines = [line for line in prev_lines if line.startswith("- R")]
        round_num = len(round_lines) + 1
        return existing.rstrip() + f"\n- R{round_num}: {delta}"

    return (
        f"{_SUMMARY_MARKER}（迭代 1-{iteration}）\n"
        f"Agent: {agent_name}\n"
        f"- R1: {delta}"
    )
