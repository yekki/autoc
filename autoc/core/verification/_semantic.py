"""语义匹配工具 — CLI/API 协议的自然语言 expected 处理

两个核心函数:
- is_natural_language(): 判断 expected 字符串是否为自然语言描述
- llm_semantic_check(): 委托 LLM 做 stdout/response vs expected 的语义匹配
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("autoc.verification.semantic")

_NATURAL_LANG_RE = re.compile(r"[\u4e00-\u9fff]")
_MAX_CONCRETE_LEN = 60

_SEMANTIC_PROMPT = """\
你是一个测试断言评判器。请判断「实际输出」是否满足「期望行为」。

期望行为: {expected}
实际输出（截取）:
```
{output}
```

只回答 true 或 false（一个词，不要解释）。
- true: 输出内容中能看到满足期望行为的证据
- false: 输出中没有相关证据，或者明显不满足"""


def is_natural_language(s: str) -> bool:
    """判断 expected 字符串是自然语言描述（而非精确输出片段）

    精确输出片段：短、无中文、看起来像程序输出（如 "ok", "200", "success"）
    自然语言描述：有中文、有完整句子、很长（如 "列表中出现买牛奶条目"）
    """
    s = s.strip()
    if not s:
        return False
    if len(s) > _MAX_CONCRETE_LEN:
        return True
    if _NATURAL_LANG_RE.search(s):
        return True
    return len(s.split()) >= 5


def llm_semantic_check(
    llm: Any,
    output: str,
    expected: str,
) -> bool:
    """委托 LLM 做 stdout/response vs expected 的语义匹配

    Args:
        llm: LLM 实例
        output: 实际命令输出（截取前 800 字符）
        expected: 自然语言期望描述

    Returns:
        True 如果 LLM 认为输出满足期望，False 否则。
        LLM 异常时返回 True（不阻塞流程）。
    """
    if not llm or not output.strip():
        return True

    prompt = _SEMANTIC_PROMPT.format(
        expected=expected[:200],
        output=output[:800],
    )
    try:
        response = llm.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=10,
        )
        answer = (response.get("content") or "").strip().lower()
        return answer.startswith("true")
    except Exception as e:
        logger.debug(f"语义匹配 LLM 调用失败（降级通过）: {e}")
        return True
