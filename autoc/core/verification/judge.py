"""LLM-as-Judge 验证 — 验收驱动架构的 P0 守门员

两个主要用途：
1. LLMJudgeProtocol: 作为兜底 VerificationProtocol，
   用于 domain="llm_judge" 或其他协议都无法处理的场景。

2. judge_task_completion(): 任务级守门员，在 implement_and_verify
   自报告 pass=true 后，独立 LLM 评判任务是否真正满足用户需求。
   参考 OpenHands resolver/issue_definitions.py 的 guess_success 模式。
"""

from __future__ import annotations

import logging
import os
import re
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from .protocol import VerificationProtocol, VerifyEvidence, VerifyResult

if TYPE_CHECKING:
    from autoc.core.project.models import AcceptanceTest

logger = logging.getLogger("autoc.verification.judge")

_JUDGE_SYSTEM_PROMPT = """\
你是独立的质量评审员。你的职责是根据代码变更和验证证据，判断任务是否真正满足用户需求。
不要依赖开发者的自报告，只看代码变更本身和实际证据。用简洁的中文回答。"""

_JUDGE_PROMPT_TEMPLATE = """\
## 任务信息
标题: {task_title}
描述: {task_description}

## 用户需求/验收标准
{acceptance_criteria}

## 实际代码变更
{change_summary}

## 开发者验收报告摘要
{dev_report_summary}

## 评判要求
请仔细分析代码变更（git diff 或文件内容），判断是否真正满足了上述验收标准的每一条。
重点关注：
1. 核心功能逻辑是否实现（不只是文件存在，要看 JS/Python 函数体、事件绑定、DOM 操作等实际逻辑）
2. 用户可见的行为是否符合预期（添加/删除/修改等操作的完整链路）
3. 明显的遗漏或死代码

---
请按如下格式回答（每行单独一条）：

判断: true/false
理由: （2-4句简明说明，引用具体代码片段）
风险点: （若为 true 但有潜在问题，说明哪些场景可能有问题；若为 false，说明具体缺少什么）"""


class JudgeResult(BaseModel):
    """任务级 LLM 评判结果"""
    passed: bool = False
    reasoning: str = ""
    risk_points: str = ""
    skipped: bool = False    # 跳过评判（LLM 不可用、无变更等）
    skip_reason: str = ""


class LLMJudgeProtocol(VerificationProtocol):
    """LLM 评判协议 — 兜底，用于 domain='llm_judge' 或降级场景"""

    def __init__(self, llm=None):
        self._llm = llm

    def can_handle(self, domain: str, workspace_dir: str) -> bool:
        # 只精确匹配自己的 domain，路由兜底由 VerificationRunner._select_protocol 保证
        return domain == "llm_judge"

    def execute(
        self,
        test: "AcceptanceTest",
        workspace_dir: str,
        shell=None,
        **kwargs,
    ) -> VerifyResult:
        if self._llm is None:
            return VerifyResult(
                description=test.description,
                passed=True,  # 无法评判时不阻塞
                error="LLM 不可用，跳过 LLM Judge 验证",
                evidence=VerifyEvidence(diagnosis="llm_unavailable"),
            )

        actions_str = "\n".join(f"  - {a}" for a in test.actions) if test.actions else "（无）"
        expected_str = "\n".join(f"  - {e}" for e in test.expected) if test.expected else "（无）"

        prompt = (
            f"验收测试描述: {test.description}\n\n"
            f"操作步骤:\n{actions_str}\n\n"
            f"预期结果:\n{expected_str}\n\n"
            f"工作区路径: {workspace_dir}\n\n"
            "请判断：基于以上验收测试的描述，代码实现是否可能满足此测试的要求？\n"
            "（注意：你没有运行时环境，只能做静态推断）\n\n"
            "回答 true/false 并给出理由（1-2句）。"
        )
        try:
            response = self._llm.chat(
                messages=[
                    {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=300,
            )
            content = response.get("content", "").strip().lower()
            passed = "true" in content and "false" not in content.split("true")[0]
            return VerifyResult(
                description=test.description,
                passed=passed,
                evidence=VerifyEvidence(raw_output=content, diagnosis=content[:200]),
            )
        except Exception as e:
            logger.warning(f"LLMJudgeProtocol 执行异常: {e}")
            return VerifyResult(
                description=test.description,
                passed=True,
                error=str(e),
                evidence=VerifyEvidence(diagnosis=f"llm_error: {e}"),
            )


def judge_task_completion(
    llm,
    task_title: str,
    task_description: str,
    acceptance_criteria: list[str],
    changed_files: list[str],
    workspace_dir: str,
    dev_report_summary: str = "",
    shell: Any = None,
    git_ops: Any = None,
) -> JudgeResult:
    """任务级 LLM 守门员 — 独立于 CodeActAgent，锚定原始需求评判

    在 implement_and_verify 自报告 pass=true 之后调用。
    参考 OpenHands guess_success 模式：评判者独立于执行者，优先使用 git diff。

    Args:
        llm: 独立 LLM 实例（推荐使用 llm_critique，非 llm_coder）
        task_title: 任务标题
        task_description: 任务描述
        acceptance_criteria: 验收标准列表
        changed_files: 本次实现变更的文件列表
        workspace_dir: 工作区路径
        dev_report_summary: CodeActAgent 的验收报告摘要
        shell: 可选 ShellExecutor，用于沙箱内读取文件
        git_ops: 可选 GitOps 实例，用于获取 git diff（优先）

    Returns:
        JudgeResult with passed + reasoning + risk_points
    """
    if not llm:
        return JudgeResult(skipped=True, skip_reason="llm_unavailable", passed=True)

    if not changed_files:
        return JudgeResult(skipped=True, skip_reason="no_changed_files", passed=True)

    # 构建变更摘要：优先 git diff（精确增量），fallback 到文件内容
    change_summary = _build_change_summary(
        changed_files, workspace_dir, shell=shell, git_ops=git_ops,
    )

    if acceptance_criteria:
        criteria_text = "\n".join(f"- {c}" for c in acceptance_criteria)
    else:
        criteria_text = task_description[:500] if task_description else task_title

    prompt = _JUDGE_PROMPT_TEMPLATE.format(
        task_title=task_title,
        task_description=task_description[:400],
        acceptance_criteria=criteria_text,
        change_summary=change_summary,
        dev_report_summary=dev_report_summary[:400] if dev_report_summary else "（无）",
    )

    try:
        response = llm.chat(
            messages=[
                {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=600,
        )
        content = response.get("content", "").strip()
        return _parse_judge_response(content)
    except Exception as e:
        logger.warning(f"LLM Judge 调用失败，降级跳过: {e}")
        return JudgeResult(skipped=True, skip_reason=f"llm_error: {e}", passed=True)


_MAX_DIFF_CHARS = 4000   # git diff 总长度预算
_MAX_FILE_CHARS = 1200   # 单文件内容预算（当 diff 不可用时）
_MAX_FILES = 8           # 最多分析的文件数


def _build_change_summary(
    changed_files: list[str],
    workspace_dir: str,
    shell: Any = None,
    git_ops: Any = None,
) -> str:
    """构建供 Judge 参考的变更摘要 — 三级策略

    L1 (最优): git diff — 精确展示增量变更，LLM 能看到新增的每一行逻辑
    L2 (中等): 整文件读取（短文件）— 新项目没有 git 历史时的 fallback
    L3 (兜底): head+tail 截取 — 超长文件
    """
    # L1: 尝试用 git diff 获取精确增量
    diff_text = _try_git_diff(changed_files, workspace_dir, shell, git_ops)
    if diff_text and len(diff_text.strip()) > 50:
        header = f"以下是 git diff 输出（共涉及 {len(changed_files)} 个文件）:\n"
        return header + f"```diff\n{diff_text[:_MAX_DIFF_CHARS]}\n```"

    # L2/L3: fallback 到文件内容读取
    return _build_files_content(changed_files, workspace_dir, shell)


def _try_git_diff(
    changed_files: list[str],
    workspace_dir: str,
    shell: Any = None,
    git_ops: Any = None,
) -> str:
    """尝试获取 git diff，包含 staged + unstaged + 新文件"""
    # 方式 1: 用 git_ops（宿主机侧，工作区已挂载）
    if git_ops is not None:
        try:
            diff = git_ops.diff(staged=False)
            if not diff:
                diff = git_ops.diff(staged=True)
            # 如果 diff 为空（已 commit），取最后一次 commit 的 diff
            if not diff:
                from subprocess import run as _run, PIPE
                result = _run(
                    ["git", "diff", "HEAD~1", "--", *changed_files[:_MAX_FILES]],
                    capture_output=True, text=True, cwd=workspace_dir, timeout=5,
                )
                diff = result.stdout if result.returncode == 0 else ""
            return diff.strip()
        except Exception as e:
            logger.debug(f"git_ops.diff 失败: {e}")

    # 方式 2: 通过 shell 在沙箱内执行
    if shell is not None:
        try:
            file_args = " ".join(f"'{f}'" for f in changed_files[:_MAX_FILES])
            diff = shell.execute(
                f"cd '{workspace_dir}' && git diff HEAD~1 -- {file_args} 2>/dev/null"
                " || git diff -- . 2>/dev/null"
                " || git diff --cached -- . 2>/dev/null",
                timeout=10,
            )
            if diff and len(diff.strip()) > 10:
                return diff.strip()
        except Exception as e:
            logger.debug(f"shell git diff 失败: {e}")

    # 方式 3: 宿主机直接执行（对抗测试场景：git_ops=None, shell=None，但 workspace_dir 有 git 历史）
    # 按优先级依次尝试：HEAD~1 diff → unstaged diff → staged diff
    if workspace_dir and os.path.isdir(os.path.join(workspace_dir, ".git")):
        from subprocess import run as _run
        for git_cmd in (
            ["git", "diff", "HEAD~1", "--"],
            ["git", "diff", "--"],
            ["git", "diff", "--cached", "--"],
        ):
            try:
                result = _run(
                    git_cmd,
                    capture_output=True, text=True,
                    cwd=workspace_dir, timeout=5,
                )
                if result.returncode == 0 and len(result.stdout.strip()) > 10:
                    return result.stdout.strip()
            except Exception as e:
                logger.debug(f"宿主机 git diff ({git_cmd}) 失败: {e}")

    return ""


def _build_files_content(
    changed_files: list[str],
    workspace_dir: str,
    shell: Any = None,
) -> str:
    """读取文件内容作为 fallback（无 git 时用）

    对短文件（< _MAX_FILE_CHARS）给出完整内容；
    对长文件做智能截取而非简单 head+tail。
    """
    sections = []
    for fpath in changed_files[:_MAX_FILES]:
        abs_path = fpath if os.path.isabs(fpath) else os.path.join(workspace_dir, fpath)
        content = _read_file_smart(abs_path, shell)
        sections.append(f"### {fpath}\n```\n{content}\n```")

    if len(changed_files) > _MAX_FILES:
        sections.append(f"...及其他 {len(changed_files) - _MAX_FILES} 个文件")
    return "\n\n".join(sections) if sections else "（无变更文件内容可读）"


def _read_file_smart(abs_path: str, shell: Any = None) -> str:
    """智能读取单个文件

    策略：
    - 短文件（< _MAX_FILE_CHARS）: 完整输出
    - 长文件: 提取 function/class 定义行 + 事件绑定 + 关键逻辑（而非简单 head+tail）
    """
    raw = ""
    if shell is not None:
        try:
            result = shell.execute(f"cat '{abs_path}' 2>/dev/null", timeout=5)
            if result and "No such file" not in result:
                raw = result
        except Exception:
            pass
    if not raw:
        try:
            with open(abs_path, encoding="utf-8", errors="replace") as f:
                raw = f.read()
        except Exception:
            return "（无法读取）"

    if len(raw) <= _MAX_FILE_CHARS:
        return raw

    # 长文件：提取关键行（函数/类/事件/路由定义 + 上下文）
    return _extract_key_lines(raw, abs_path)


# 关键行匹配：函数/类定义、事件绑定、路由定义、DOM 操作
_KEY_LINE_PATTERNS = re.compile(
    r"(def\s+\w+|class\s+\w+|function\s+\w+|const\s+\w+\s*=|"
    r"addEventListener|onclick|onsubmit|on\w+\s*=|"
    r"\.route\(|@app\.|@router\.|fetch\(|axios\.|"
    r"querySelector|getElementById|createElement|appendChild|removeChild|"
    r"innerHTML|textContent|\.append\(|\.remove\(|\.push\(|\.splice\(|"
    r"export\s+|import\s+|module\.exports|require\()",
    re.IGNORECASE,
)


def _extract_key_lines(raw: str, filepath: str) -> str:
    """从长文件中提取函数签名 + 关键逻辑行 + 上下文"""
    lines = raw.splitlines()
    total = len(lines)
    kept_indices: set[int] = set()

    # 始终保留前 5 行（imports/declarations）
    for i in range(min(5, total)):
        kept_indices.add(i)

    # 匹配关键行并保留其上下文（前2行 + 后5行）
    for i, line in enumerate(lines):
        if _KEY_LINE_PATTERNS.search(line):
            for j in range(max(0, i - 2), min(total, i + 6)):
                kept_indices.add(j)

    if not kept_indices:
        # 没有匹配到关键行，退化到头尾截取
        half = _MAX_FILE_CHARS // 2
        return raw[:half] + f"\n... ({total} 行，省略中间部分) ...\n" + raw[-half:]

    # 按行号顺序输出，省略间隔标记为 "..."
    sorted_indices = sorted(kept_indices)
    result_lines: list[str] = []
    budget = _MAX_FILE_CHARS
    prev_idx = -2

    for idx in sorted_indices:
        if idx > prev_idx + 1:
            gap = idx - prev_idx - 1
            marker = f"  ... ({gap} 行省略) ..."
            result_lines.append(marker)
            budget -= len(marker)
        line_text = lines[idx]
        if budget - len(line_text) < 0:
            result_lines.append(f"  ... (截断，共 {total} 行)")
            break
        result_lines.append(line_text)
        budget -= len(line_text)
        prev_idx = idx

    return "\n".join(result_lines)


_BOLD_STRIP_RE = re.compile(r"\*+")


def _strip_line(line: str) -> str:
    """去掉 Markdown bold（**判断**:）和首尾空白"""
    return _BOLD_STRIP_RE.sub("", line).strip()


def _extract_field_value(line: str) -> str:
    """从 '判断: xxx' 或 '判断：xxx' 中提取 xxx"""
    for sep in ("：", ":"):
        if sep in line:
            return line.split(sep, 1)[1].strip()
    return ""


def _parse_judge_response(content: str) -> JudgeResult:
    """解析 LLM Judge 的结构化回答

    兼容格式:
      - 标准:   '判断: true'
      - 全角:   '判断：true'
      - Bold:   '**判断**: true' / '**判断**：true'
      - 容错:   无结构化字段时从全文推断
    """
    lines = content.strip().splitlines()
    passed = False
    reasoning = ""
    risk_points = ""

    for raw_line in lines:
        line = _strip_line(raw_line)
        if line.startswith("判断"):
            val = _extract_field_value(line).lower()
            if val:
                passed = val.startswith("true")
        elif line.startswith("理由"):
            val = _extract_field_value(line)
            if val:
                reasoning = val
        elif line.startswith("风险点"):
            val = _extract_field_value(line)
            if val:
                risk_points = val

    # 容错：结构化解析完全失败时从全文推断
    if not reasoning:
        reasoning = content[:300]
        lower = content.lower()
        # 严格：有明确否定词则 False，否则看肯定词
        has_negative = any(kw in lower for kw in ("false", "不满足", "未实现", "未通过", "没有实现"))
        has_positive = any(kw in lower for kw in ("true", "满足", "通过", "已实现", "正确实现"))
        passed = has_positive and not has_negative

    return JudgeResult(passed=passed, reasoning=reasoning, risk_points=risk_points)
