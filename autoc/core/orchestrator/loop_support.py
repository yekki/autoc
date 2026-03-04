"""循环引擎支持功能 — 上下文构建 / 后处理 / 信息提取"""

import logging
import os
import re
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from rich.console import Console

from autoc.core.project.state import PRDState
from autoc.core.project.models import Task
from .loop_models import Phase, IterationResult

if TYPE_CHECKING:
    from .facade import Orchestrator

console = Console()
logger = logging.getLogger("autoc.loop")


class _SupportMixin:
    """上下文构建 + 后处理 + 信息提取（混入 IterativeLoop）"""

    # ================================================================
    # Post-iteration
    # ================================================================

    def _post_iteration(
        self, iteration: int, phase: Phase,
        story: Optional[Task], result: IterationResult, prd: PRDState,
    ):
        """更新 prd.json, progress.txt, guardrails, AGENTS.md, Git, SQLite sync"""
        learnings = self._extract_learnings(result.agent_output)
        new_guardrails = self._extract_guardrails(result.agent_output)
        new_patterns = self._extract_patterns(result.agent_output)

        if story and result.success:
            self.state.append_progress(
                story=story, iteration=iteration,
                summary=f"{phase.value}: {result.agent_output[:200] if result.agent_output else 'completed'}",
                files_changed=result.files_changed,
                learnings=learnings,
            )

        if new_guardrails:
            self.state.append_guardrail("已发现的模式", new_guardrails)

        if new_patterns:
            self.state.update_codebase_patterns(new_patterns)

        all_discoveries = new_patterns + new_guardrails + learnings
        if all_discoveries and result.files_changed:
            self._update_workspace_agents_md(result.files_changed, all_discoveries)

        if phase == Phase.DEV and self.orc.git_ops and result.files_changed:
            story_info = f"{story.id} - {story.title[:40]}" if story else "iteration"
            self.orc.git_ops.commit(
                f"feat: [{phase.value}] {story_info} (iteration {iteration})"
            )

        self._sync_to_sqlite(prd)

        try:
            if hasattr(self.orc, "_save_checkpoint"):
                story_id = story.id if story else "unknown"
                self.orc._save_checkpoint(f"iteration_{iteration}_{story_id}")
        except Exception as e:
            logger.warning(f"保存 checkpoint 失败: {e}")

        if story and self.orc.progress_tracker:
            self.orc.progress_tracker.write_task_result(
                task_id=story.id,
                phase=phase.value,
                success=result.success,
                files=result.files_changed,
                summary=result.agent_output[:300] if result.agent_output else "",
            )

    def _sync_to_sqlite(self, prd: PRDState):
        """同步 prd.json 状态到 SQLite"""
        if not self.orc.progress_tracker:
            return
        for task in prd.tasks:
            self.orc.progress_tracker.update_task_passes(
                task.id, task.passes, "",
            )

    # ================================================================
    # Context Building
    # ================================================================

    def _build_context(
        self, phase: Phase, story: Optional[Task],
        prd: PRDState, guardrails: str, patterns: str,
    ) -> str:
        complexity = getattr(self.orc, "_complexity", "complex")
        parts = []
        # 简单项目跳过 patterns/guardrails，减少 prompt 体积
        if patterns and complexity not in ("simple",):
            parts.append(f"## Codebase Patterns\n\n{patterns}")
        if guardrails and complexity not in ("simple",):
            parts.append(f"## Guardrails\n\n{guardrails}")
        parts.append(f"## 项目状态\n\n- 进度: {prd.progress_summary()}")
        if prd.tech_stack:
            parts.append(f"- 技术栈: {', '.join(prd.tech_stack)}")
        pending = [t for t in prd.tasks if not t.passes]
        if pending:
            parts.append(f"- 待完成任务: {len(pending)}")
            for t in pending[:5]:
                parts.append(f"  - [{t.id}] {t.title}")
        return "\n\n".join(parts)

    # ================================================================
    # Codebase Summary — 零 LLM 消耗的代码摘要
    # ================================================================

    _SIGNATURE_PATTERNS = [
        (r"^\s*(export\s+)?(async\s+)?function\s+(\w+)", "fn"),
        (r"^\s*(export\s+)?class\s+(\w+)", "class"),
        (r"^\s*(export\s+)?(const|let|var)\s+(\w+)\s*=", "var"),
        (r"^\s*def\s+(\w+)\s*\(", "fn"),
        (r"^\s*class\s+(\w+)", "class"),
    ]

    def _extract_signatures(self, filepath: str) -> list[str]:
        """用正则提取单个文件的公开接口签名"""
        sigs: list[str] = []
        try:
            with open(filepath, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    for pattern, kind in self._SIGNATURE_PATTERNS:
                        m = re.match(pattern, line)
                        if m:
                            name = m.group(m.lastindex) if m.lastindex else m.group(0)
                            sigs.append(f"{kind}: {name}")
                            break
        except OSError:
            pass
        return sigs[:20]

    def _generate_codebase_summary(self) -> str:
        """扫描 workspace 下的代码文件，提取公开接口签名摘要"""
        from autoc.stacks._registry import get_hidden_dirs
        ws = self.orc.workspace_dir
        hidden = get_hidden_dirs(ws)
        code_exts = {".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".go", ".rs"}
        lines: list[str] = ["## 已有代码文件摘要（系统自动提取，无需 read_file）"]
        file_count = 0
        for root, dirs, files in os.walk(ws):
            dirs[:] = [d for d in dirs if d not in hidden and not d.startswith(".")]
            for fname in sorted(files):
                ext = os.path.splitext(fname)[1]
                if ext not in code_exts:
                    continue
                fpath = os.path.join(root, fname)
                rel = os.path.relpath(fpath, ws)
                sigs = self._extract_signatures(fpath)
                if sigs:
                    lines.append(f"**{rel}**: {', '.join(sigs)}")
                    file_count += 1
                if file_count >= 30:
                    break
            if file_count >= 30:
                break
        if file_count == 0:
            return ""
        return "\n".join(lines)

    def _build_prev_tasks_summary(self, story: Task, prd: PRDState) -> str:
        """构建前序已完成任务的精简摘要，避免跨任务上下文断裂"""
        completed = [t for t in prd.tasks if t.id in self._implemented and t.id != story.id]
        if not completed:
            return ""
        lines = ["## 前序已完成任务（关键决策参考）"]
        for t in completed[:5]:
            _files = list(t.files) if t.files else []
            files_info = f"，文件: {', '.join(_files[:3])}" if _files else ""
            lines.append(f"- [{t.id}] {t.title}{files_info}")
        if len(completed) > 5:
            lines.append(f"- ...及其他 {len(completed) - 5} 个任务")
        lines.append("\n> 请通过 read_file 查看已有代码，确保本任务与已有实现兼容。")
        return "\n".join(lines)

    def _build_dev_prompt(self, story: Task, prd: PRDState, context: str) -> str:
        # P-INV-03: Prompt 组装规范 (见 AGENT_SCHEDULING_PARADIGM.md §4)
        criteria = "\n".join(f"  - {c}" for c in story.acceptance_criteria)

        # 文件契约（PM 硬约束）
        file_contract = ""
        if story.files:
            file_list = "\n".join(f"  - `{f}`" for f in story.files)
            file_contract = (
                f"\n\n## 📋 必须创建的文件（PM 契约，不可更改）\n"
                f"{file_list}\n\n"
                f"**你必须使用 write_file 创建以上每个文件。**"
                f"文件路径和命名必须与上述列表完全一致。"
            )

        # P-INV-02: 按需加载规约 — 仅当任务涉及数据层/API 时才注入
        spec_section = ""
        task_desc = (story.description or "").lower() + " ".join(story.files or []).lower()
        _needs_data = any(kw in task_desc for kw in ("model", "db", "database", "schema", "table", "orm", "数据"))
        _needs_api = any(kw in task_desc for kw in ("route", "api", "endpoint", "app.py", "server", "flask", "fastapi", "路由"))
        if _needs_data and hasattr(prd, "data_models") and prd.data_models:
            spec_section += f"\n\n## 📐 数据模型规约（PM 定义，必须照抄实现）\n```\n{prd.data_models}\n```"
        if _needs_api and hasattr(prd, "api_design") and prd.api_design:
            spec_section += f"\n\n## 🔌 API 契约（PM 定义，必须实现）\n```\n{prd.api_design}\n```"
        is_first = (prd.tasks and story.id == prd.tasks[0].id)
        if is_first and not spec_section:
            if hasattr(prd, "data_models") and prd.data_models:
                spec_section += f"\n\n## 📐 数据模型规约（PM 定义，必须照抄实现）\n```\n{prd.data_models}\n```"
            if hasattr(prd, "api_design") and prd.api_design:
                spec_section += f"\n\n## 🔌 API 契约（PM 定义，必须实现）\n```\n{prd.api_design}\n```"

        interface_spec = getattr(prd, "interface_spec", "") or ""
        if interface_spec:
            interface_spec = f"\n\n## 接口规格（PM 定义，所有任务必须遵循）\n{interface_spec}"

        # 验证步骤（可执行的 shell 命令）
        verification_section = ""
        if story.verification_steps:
            v_steps = "\n".join(f"  {i}. `{c}`" for i, c in enumerate(story.verification_steps, 1))
            verification_section = (
                f"\n\n## ✅ 验证步骤（写完代码后必须逐条执行）\n{v_steps}\n"
                "**用 execute_command 逐条运行以上命令验证，全部通过才算完成。**"
            )

        prev_summary = self._build_prev_tasks_summary(story, prd)
        if prev_summary:
            prev_summary = f"\n\n{prev_summary}"

        stack_info = ""
        try:
            from autoc.stacks._registry import parse_project_context, get_coding_guidelines
            proj_ctx = parse_project_context(self.orc.workspace_dir)
            summary = proj_ctx.to_prompt_summary()
            guidelines = get_coding_guidelines(self.orc.workspace_dir)
            stack_info = f"\n\n{summary}"
            if guidelines:
                stack_info += f"\n\n{guidelines}"
        except Exception:
            pass

        codebase_summary = self._generate_codebase_summary()
        if codebase_summary:
            stack_info += f"\n\n{codebase_summary}"

        failure_hint = ""
        trajectory = story.failure_trajectory if story.failure_trajectory else []
        if trajectory:
            failure_hint = f"\n\n## ⚠️ 该任务已失败 {len(trajectory)} 次 — 必须使用不同方案\n"
            last = trajectory[-1]

            # 区分普通执行失败 vs LLM-Judge-Gate 失败（带验证证据）
            if last.get("source") == "llm_judge_gate":
                failure_hint += "**失败原因: 独立质量评审未通过（代码可运行但功能验证失败）**\n\n"

                # acceptance_tests 证据（最有价值）
                at_evidence = last.get("at_evidence", [])
                if at_evidence:
                    failure_hint += "### 验收测试失败证据\n"
                    for ev in at_evidence[:2]:
                        failure_hint += f"- 测试: {ev.get('test', '未知')[:80]}\n"
                        if ev.get("diagnosis"):
                            failure_hint += f"  诊断: {ev['diagnosis'][:120]}\n"
                        if ev.get("dom_diff"):
                            failure_hint += f"  DOM 差异: {ev['dom_diff'][:100]}\n"
                        if ev.get("console_errors"):
                            errs = ev["console_errors"][:2]
                            failure_hint += f"  控制台错误: {'; '.join(errs)}\n"
                        if ev.get("raw_output"):
                            failure_hint += f"  原始输出片段: {ev['raw_output'][:150]}\n"

                # LLM Judge 评判
                judge_reasoning = last.get("judge_reasoning", "")
                risk_points = last.get("judge_risk_points", "")
                if judge_reasoning:
                    failure_hint += f"\n### LLM 评审意见\n{judge_reasoning[:300]}\n"
                if risk_points:
                    failure_hint += f"\n### 风险点\n{risk_points[:200]}\n"

                failure_hint += (
                    "\n**修复重点**: 上述验收测试揭示了功能层面的缺陷，请针对性修复：\n"
                    "- 检查相关事件处理器是否正确绑定（onclick, addEventListener）\n"
                    "- 检查 DOM 操作是否正确（元素选择器、插入/删除逻辑）\n"
                    "- 检查异步操作和状态更新是否生效\n"
                    "- 在浏览器控制台可见的错误必须全部消除\n"
                )
            else:
                # 普通失败轨迹
                failure_hint += f"上次错误: {last.get('error', '未知')}\n"
                if last.get("files_attempted"):
                    failure_hint += f"上次尝试的文件: {', '.join(last['files_attempted'][:5])}\n"
                if last.get("missing_files"):
                    failure_hint += f"缺失的文件: {', '.join(last['missing_files'][:5])}\n"

            failure_hint += (
                "\n**禁止重复上次的实现方案。** 请选择以下策略之一:\n"
                "- 简化实现（去掉非核心功能，先跑通再迭代）\n"
                "- 更换实现方式（换数据结构、换算法、换库）\n"
                "- 拆分为更小的步骤（先写核心逻辑，再加辅助功能）\n"
            )

        return (
            f"你是契约驱动的开发工程师。请按照 PM 规约实现以下 story:\n\n"
            f"## Story: [{story.id}] {story.title}\n"
            f"{story.description}\n\n"
            f"## 验收标准\n{criteria}"
            f"{file_contract}"
            f"{spec_section}"
            f"{verification_section}\n\n"
            f"{context}"
            f"{interface_spec}"
            f"{prev_summary}"
            f"{failure_hint}"
            f"{stack_info}\n\n"
            "## 执行步骤\n"
            "1. 按文件清单逐个创建文件（write_file），代码写完整\n"
            "2. **必须创建上述文件清单中的所有文件**\n"
            "3. 安装必要依赖（pip install + requirements.txt）\n"
            "4. **逐条执行验证步骤**，全部通过才算完成\n"
            "5. 如果验证失败，修复后重新验证\n"
        )

    # ================================================================
    # Extraction Helpers
    # ================================================================

    def _extract_guardrails(self, output: str) -> list[str]:
        if not output:
            return []
        markers = ["GUARDRAIL:", "注意:", "GOTCHA:", "WARNING:"]
        items = []
        for line in output.split("\n"):
            stripped = line.strip()
            for marker in markers:
                if stripped.upper().startswith(marker.upper()):
                    items.append(stripped[len(marker):].strip())
        return items

    def _extract_patterns(self, output: str) -> list[str]:
        if not output:
            return []
        markers = ["PATTERN:", "模式:"]
        items = []
        for line in output.split("\n"):
            stripped = line.strip()
            for marker in markers:
                if stripped.upper().startswith(marker.upper()):
                    items.append(stripped[len(marker):].strip())
        return items

    def _extract_learnings(self, output: str) -> list[str]:
        """从 Agent 输出中提取 learnings"""
        if not output:
            return []
        markers = ["LEARNING:", "学到:", "发现:", "GOTCHA:", "TIP:"]
        items = []
        for line in output.split("\n"):
            stripped = line.strip()
            for marker in markers:
                if stripped.upper().startswith(marker.upper()):
                    items.append(stripped[len(marker):].strip())
        return items

    def _update_workspace_agents_md(
        self, changed_files: list[str], discoveries: list[str],
    ):
        """自动更新工作区 AGENTS.md（参考 snarktank/ralph）"""
        ws = self.orc.workspace_dir
        agents_md_path = os.path.join(ws, "AGENTS.md")

        if not discoveries:
            return

        existing = ""
        if os.path.exists(agents_md_path):
            try:
                with open(agents_md_path, "r", encoding="utf-8") as f:
                    existing = f.read()
            except Exception:
                pass

        new_items = [d for d in discoveries if d and d not in existing]
        if not new_items:
            return

        section_header = "## Auto-discovered Patterns"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        entries = "\n".join(f"- {item}" for item in new_items[:10])
        block = f"\n\n{section_header}\n\n> Updated: {timestamp}\n\n{entries}\n"

        if section_header in existing:
            insert_pos = existing.index(section_header) + len(section_header)
            next_section = existing.find("\n## ", insert_pos)
            if next_section == -1:
                next_section = len(existing)
            new_content = (
                existing[:next_section].rstrip()
                + f"\n\n> Updated: {timestamp}\n\n{entries}\n"
                + existing[next_section:]
            )
        else:
            new_content = existing.rstrip() + block

        try:
            with open(agents_md_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            logger.info(f"AGENTS.md 已更新: +{len(new_items)} 条发现")
        except Exception as e:
            logger.warning(f"更新 AGENTS.md 失败: {e}")
