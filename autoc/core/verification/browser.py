"""Browser 验证协议 — Web 前端交互的验收测试执行

依赖沙箱内安装的 Playwright（python3 playwright 包）。
当 Playwright 不可用时，自动降级到 LLMJudgeProtocol。

使用方式：
    protocol = BrowserProtocol()
    result = protocol.execute(test, workspace_dir, shell=shell, preview_url="http://localhost:5000")
"""

from __future__ import annotations

import hashlib
import json as _json
import logging
import re
from typing import TYPE_CHECKING, Any

from .protocol import VerificationProtocol, VerifyEvidence, VerifyResult

if TYPE_CHECKING:
    from autoc.core.project.models import AcceptanceTest

logger = logging.getLogger("autoc.verification.browser")

# 匹配引号内的文本：'xxx' / "xxx" / 「xxx」
_QUOTED_TEXT_RE = re.compile(r"['\"\u300c\u300e](.*?)['\"\u300d\u300f]")


class BrowserProtocol(VerificationProtocol):
    """Web 前端验证 — Playwright 浏览器交互

    需要沙箱内安装 Playwright: pip install playwright && playwright install chromium
    当 Playwright 不可用时自动降级到 LLMJudgeProtocol。

    可用性检查结果缓存在实例级别（按 shell 对象 id），
    避免跨项目/跨沙箱污染，也避免每次都检查。
    """

    def __init__(self):
        # 按 shell 对象 id 缓存：{shell_id: bool}
        self._availability_cache: dict[int, bool] = {}

    def _check_playwright(self, shell: Any) -> bool:
        """检查沙箱内 Playwright 是否可用（实例级缓存，按 shell 隔离）"""
        if shell is None:
            return False
        shell_id = id(shell)
        if shell_id in self._availability_cache:
            return self._availability_cache[shell_id]
        try:
            result = shell.execute(
                "python3 -c 'from playwright.sync_api import sync_playwright; print(\"ok\")' 2>&1",
                timeout=10,
            )
            available = "ok" in (result or "")
        except Exception:
            available = False
        self._availability_cache[shell_id] = available
        logger.debug(f"Playwright 可用性检查: shell={shell_id} → {available}")
        return available

    def can_handle(self, domain: str, workspace_dir: str) -> bool:
        return domain == "browser"

    def execute(
        self,
        test: "AcceptanceTest",
        workspace_dir: str,
        shell: Any = None,
        preview_url: str = "",
        **kwargs,
    ) -> VerifyResult:
        # 检查 Playwright 可用性
        if not self._check_playwright(shell):
            logger.info("Playwright 不可用，降级到 LLMJudgeProtocol")
            from .judge import LLMJudgeProtocol
            llm = kwargs.get("llm")
            fallback = LLMJudgeProtocol(llm=llm)
            return fallback.execute(test, workspace_dir, shell=shell, **kwargs)

        if not preview_url:
            return VerifyResult(
                description=test.description,
                passed=True,
                error="preview_url 未提供，跳过浏览器验证",
                evidence=VerifyEvidence(diagnosis="no_preview_url"),
            )

        test_id = hashlib.md5(test.description.encode()).hexdigest()[:8]
        script = self._build_script(test, preview_url, test_id)

        script_path = f"/tmp/pw_test_{test_id}.py"
        try:
            # 用 printf 写入避免 heredoc 对脚本内容的 shell 解释问题
            script_escaped = script.replace("'", "'\\''")
            shell.execute(f"printf '%s' '{script_escaped}' > {script_path}", timeout=10)
            result_raw = shell.execute(f"python3 {script_path} 2>&1", timeout=30)
        except Exception as e:
            return VerifyResult(
                description=test.description,
                passed=False,
                error=str(e),
                evidence=VerifyEvidence(diagnosis=f"playwright_exec_error: {e}"),
            )

        return self._parse_result(test, result_raw)

    def _build_script(self, test: "AcceptanceTest", preview_url: str, test_id: str) -> str:
        """生成 Playwright 测试脚本

        URL 和 expected_checks 用 json.dumps 安全序列化，
        避免特殊字符导致的脚本语法错误。
        """
        url_repr = _json.dumps(preview_url)           # '"http://..."' 安全
        expected_repr = _json.dumps(test.expected or [])  # '["..."]' 安全
        actions_code = _build_actions_code(test.actions or [])

        return f'''\
from playwright.sync_api import sync_playwright
import json

errors = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)

    try:
        page.goto({url_repr}, timeout=10000)
        page.wait_for_load_state("networkidle", timeout=5000)

        page.screenshot(path="/tmp/before_{test_id}.png")

{actions_code}

        page.screenshot(path="/tmp/after_{test_id}.png")

        content = page.content()
        checks = {expected_repr}
        missing = [c for c in checks if c not in content]

        result = {{
            "passed": len(missing) == 0,
            "missing": missing,
            "console_errors": errors[:5],
            "screenshot_before": "/tmp/before_{test_id}.png",
            "screenshot_after": "/tmp/after_{test_id}.png",
        }}
    except Exception as e:
        result = {{"passed": False, "error": str(e), "console_errors": errors[:5]}}

    browser.close()

print(json.dumps(result))
'''

    def _parse_result(self, test: "AcceptanceTest", result_raw: str) -> VerifyResult:
        """解析 Playwright 脚本的 JSON 输出"""
        try:
            last_brace = result_raw.rfind("}")
            first_brace = result_raw.rfind("{", 0, last_brace + 1)
            if first_brace >= 0:
                parsed = _json.loads(result_raw[first_brace:last_brace + 1])
            else:
                raise ValueError("no JSON in output")
        except Exception:
            parsed = {"passed": False, "error": result_raw[:300]}

        missing = parsed.get("missing", [])
        console_errors = parsed.get("console_errors", [])
        dom_diff = f"缺少期望内容: {', '.join(missing)}" if missing else ""

        diagnosis_parts = []
        if missing:
            diagnosis_parts.append(f"DOM 中缺少: {', '.join(missing[:3])}")
        if console_errors:
            diagnosis_parts.append(f"控制台错误: {'; '.join(console_errors[:2])}")

        return VerifyResult(
            description=test.description,
            passed=parsed.get("passed", False),
            error=parsed.get("error", ""),
            evidence=VerifyEvidence(
                raw_output=result_raw[:500],
                dom_diff=dom_diff,
                console_errors=console_errors[:5],
                screenshot_before=parsed.get("screenshot_before", ""),
                screenshot_after=parsed.get("screenshot_after", ""),
                diagnosis="; ".join(diagnosis_parts),
            ),
        )


def _build_actions_code(actions: list[str]) -> str:
    """把自然语言 actions 翻译为 Playwright Python 代码片段（8空格缩进）"""
    lines = []
    for action in actions:
        action_lower = action.lower()
        if any(kw in action for kw in ("输入", "填写")) or \
                any(kw in action_lower for kw in ("input", "fill", "type")):
            m = _QUOTED_TEXT_RE.search(action)
            text = _json.dumps(m.group(1) if m else "test")  # 安全转义
            if "输入框" in action or "input" in action_lower:
                lines.append(f"        page.fill('input', {text})")
            else:
                lines.append(f"        page.keyboard.type({text})")
        elif "点击" in action or "click" in action_lower:
            if any(kw in action for kw in ("添加", "提交")) or \
                    any(kw in action_lower for kw in ("add", "submit")):
                lines.append("        page.click('button')")
            elif any(kw in action for kw in ("删除", "移除")) or \
                    any(kw in action_lower for kw in ("delete", "remove")):
                lines.append(
                    "        page.click('[data-action=delete], .delete, .remove,"
                    " button:has-text(\"删除\")')"
                )
            else:
                lines.append("        page.click('button')")
        elif "等待" in action or "wait" in action_lower:
            lines.append("        page.wait_for_timeout(1000)")
        else:
            lines.append(f"        # 无法自动翻译: {action}")
            lines.append("        page.wait_for_timeout(500)")
    return "\n".join(lines) if lines else "        page.wait_for_timeout(500)"
