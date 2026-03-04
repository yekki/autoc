"""L1/L2/L3 分层上下文构建器

借鉴 MyCodeAgent 的 ContextBuilder 设计：
- L1 系统静态层：System Prompt + 工具说明（固定不变）
- L2 项目规则层：guardrails / code_law（有则注入，不进入 history）
- L3 会话历史层：user / assistant / tool 消息 + 压缩摘要

职责：
- 将 system prompt、guardrails、skills 等组装为标准 messages 列表
- 管理运行时注入（熔断工具通知、进度提醒等），不污染 user 轮次
- 可选的 @file 提醒注入
"""

import logging
import os
import re
from typing import Optional

logger = logging.getLogger("autoc.context_builder")

# @file 引用匹配（只支持英文路径，最多 5 个）
_FILE_MENTION_PATTERN = re.compile(r'(?<!\w)@([a-zA-Z0-9/._-]+(?:\.[a-zA-Z0-9]+))')
_MAX_FILE_MENTIONS = 5


class ContextBuilder:
    """分层上下文构建器

    Usage:
        builder = ContextBuilder(system_prompt="...", workspace_dir="/path/to/ws")
        builder.set_guardrails("必须使用相对路径...")
        builder.set_skills_prompt("可用技能: ...")
        builder.set_disabled_tools(["read_file"])
        messages = builder.build(conversation_history)
    """

    def __init__(self, system_prompt: str, workspace_dir: str = ""):
        self._base_system_prompt = system_prompt
        self._workspace_dir = workspace_dir
        self._guardrails: str = ""
        self._skills_prompt: str = ""
        self._code_context: str = ""
        self._disabled_tools: list[str] = []
        self._runtime_blocks: list[str] = []
        self._cached_l1: Optional[str] = None

    # ==================== L1: 系统静态层 ====================

    def set_system_prompt(self, prompt: str):
        """更新基础 system prompt（清空 L1 缓存）"""
        self._base_system_prompt = prompt
        self._cached_l1 = None

    def _build_l1(self) -> str:
        """构建 L1 层：base system prompt + 工具状态"""
        if self._cached_l1 is not None and not self._disabled_tools:
            return self._cached_l1

        parts = [self._base_system_prompt]

        # 被熔断禁用的工具提醒
        if self._disabled_tools:
            parts.append(
                "\n## 临时禁用的工具\n"
                "以下工具因连续失败已被临时禁用，请使用其他方式完成任务：\n"
                + "\n".join(f"- {t}" for t in self._disabled_tools)
            )

        result = "\n".join(parts)
        if not self._disabled_tools:
            self._cached_l1 = result
        return result

    # ==================== L2: 项目规则层 ====================

    def set_guardrails(self, guardrails: str):
        """设置 guardrails 规则（每次迭代可更新）"""
        self._guardrails = guardrails

    def set_skills_prompt(self, skills_prompt: str):
        """设置可用 Skills 提示词"""
        self._skills_prompt = skills_prompt

    def set_code_context(self, code_context: str):
        """设置 RAG 代码上下文（来自 CodeIndex 搜索结果）"""
        self._code_context = code_context

    def _build_l2(self) -> Optional[str]:
        """构建 L2 层：项目规则 + 技能（返回 None 表示无需注入）"""
        parts = []
        if self._guardrails:
            parts.append(f"## Guardrails（必须遵守）\n{self._guardrails}")
        if self._skills_prompt:
            parts.append(f"## Available Skills\n{self._skills_prompt}")
        if self._code_context:
            parts.append(f"## 相关代码上下文\n{self._code_context}")
        return "\n\n".join(parts) if parts else None

    # ==================== 运行时注入 ====================

    def set_disabled_tools(self, tools: list[str]):
        """更新被熔断禁用的工具列表"""
        self._disabled_tools = tools
        self._cached_l1 = None

    def set_runtime_blocks(self, blocks: list[str]):
        """设置运行时状态注入块（Team 状态、进度提醒等）"""
        self._runtime_blocks = blocks

    # ==================== 构建最终 messages ====================

    def build(self, conversation_history: list[dict]) -> list[dict]:
        """构建完整的 messages 列表

        结构:
          [0] system: L1 + L2 + Runtime（合并为单条，用 --- 分隔）
          [1..] conversation_history（user / assistant / tool）
        """
        # 将 L1、L2、Runtime 合并为一条 system 消息，避免多条 system 消息兼容性问题
        parts = [self._build_l1()]
        l2 = self._build_l2()
        if l2:
            parts.append(l2)
        if self._runtime_blocks:
            parts.append("[Runtime]\n" + "\n".join(self._runtime_blocks))
        messages = [{"role": "system", "content": "\n\n---\n\n".join(parts)}]

        # L3: 历史消息
        for msg in conversation_history:
            if msg.get("role") == "system":
                continue
            messages.append(msg)

        return messages

    # ==================== @file 提醒 ====================

    @staticmethod
    def detect_file_mentions(text: str) -> list[str]:
        """从文本中提取 @file 引用"""
        mentions = _FILE_MENTION_PATTERN.findall(text)
        seen: set[str] = set()
        unique: list[str] = []
        for m in mentions:
            if m not in seen:
                seen.add(m)
                unique.append(m)
        return unique[:_MAX_FILE_MENTIONS]

    @staticmethod
    def build_file_reminder(mentions: list[str]) -> str:
        """生成 @file 强制读取提醒"""
        if not mentions:
            return ""
        file_list = ", ".join(f"@{m}" for m in mentions)
        if len(mentions) == 1:
            instruction = f"Read {mentions[0]} with the read_file tool"
        else:
            instruction = f"Read these files: {', '.join(mentions)}"
        return (
            f"\n\n<system-reminder>"
            f"User mentioned {file_list}. {instruction} before proceeding."
            f"</system-reminder>"
        )
