"""循环引擎修复阶段 — Fix / 反思 / 快速验证 / 修复轨迹"""

import logging
import re
from typing import TYPE_CHECKING, Optional

from rich.console import Console

from autoc.core.project.state import PRDState
from autoc.core.project.models import BugReport, TaskStatus
from autoc.core.analysis.failure_analyzer import FailureAnalyzer, FailureAnalysis
from .loop_models import Phase, IterationResult

if TYPE_CHECKING:
    from .facade import Orchestrator

console = Console()
logger = logging.getLogger("autoc.loop")

_failure_analyzer = FailureAnalyzer()


class _FixMixin:
    """Fix 阶段执行 + 反思 + 快速验证（混入 IterativeLoop）"""

    # Bug 严重级别优先序（越小越优先）
    _SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    _MAX_BUGS_PER_FIX_ROUND = 5

    def _prioritize_bugs(self, bugs: list) -> list:
        """按严重程度排序，每轮只取最关键的一批，避免上下文爆炸"""
        bugs.sort(key=lambda b: self._SEVERITY_ORDER.get(b.severity, 2))
        return bugs[:self._MAX_BUGS_PER_FIX_ROUND]

    def _execute_fix(
        self, iteration: int, prd: PRDState,
        context: str, ir: IterationResult,
    ) -> IterationResult:
        """FIX 阶段 (P-FT-03/04/05, P-QG-04, P-SM-05/06):
        按严重程度分批处理，每轮最多 N 个 Bug。
        """
        report = self._last_test_report
        open_bugs = self.orc.memory.get_open_bugs()

        if not open_bugs:
            last_passed = self._last_test_report.get("pass", False) if isinstance(self._last_test_report, dict) else False
            if last_passed:
                console.print("  ℹ️  没有需要修复的 Bug，测试已通过")
                self._transition("test", "无 Bug 且测试已通过")
                ir.success = True
            else:
                # 防死循环: 跟踪连续 "无 Bug 但未通过" 次数
                self._no_bug_fail_count += 1
                no_bug_fail_count = self._no_bug_fail_count

                _FORCE_PASS_THRESHOLD = 4  # 需连续 4 次才强制放行，降低误放行风险
                if no_bug_fail_count >= _FORCE_PASS_THRESHOLD:
                    console.print(
                        f"  🛑 连续 {no_bug_fail_count} 次无 Bug 但测试未通过，"
                        f"强制标记所有已实现任务为通过以终止循环"
                    )
                    prd = self.state.load_prd()
                    for task in prd.tasks:
                        if task.id in self._implemented and not task.passes:
                            prd.mark_task_passed(
                                task.id, True,
                                "测试框架异常，验证命令通过但报告格式异常，强制放行（force_passed=true）",
                            )
                            self.orc.memory.update_task(
                                task.id, status=TaskStatus.COMPLETED, passes=True,
                            )
                    self.state.save_prd(prd)
                    self._transition("test", "强制放行：连续无 Bug 但测试未通过")
                    ir.success = True
                else:
                    console.print(
                        "  ⚠️  没有注册的 Bug 但测试未通过，可能是测试框架异常，"
                        f"重测 (第 {no_bug_fail_count} 次，{_FORCE_PASS_THRESHOLD} 次后强制放行)"
                    )
                    self._transition("test", "无 Bug 但测试未通过，疑似框架异常")
                    ir.success = True
                    ir.error = "无 Bug 记录但测试未通过，疑似测试框架异常"
            return ir

        self._no_bug_fail_count = 0

        # 按严重程度分批，每轮只修复最关键的 Bug
        total_open = len(open_bugs)
        open_bugs = self._prioritize_bugs(open_bugs)
        if total_open > len(open_bugs):
            console.print(f"  📊 共 {total_open} 个 Bug，本轮优先修复最严重的 {len(open_bugs)} 个")

        failure_analysis = _failure_analyzer.analyze(
            test_report=report,
            bugs=open_bugs,
            round_num=self._fix_round,
            previous_reports=self._test_reports[:-1],
            fix_history=self._fix_history,
        )
        if failure_analysis.patterns:
            pattern_str = ", ".join(p.value for p in failure_analysis.patterns)
            console.print(
                f"  🔍 失败模式: [{failure_analysis.severity}] {pattern_str}"
                f" | 类型: {failure_analysis.failure_type.value}"
                f" → 策略: {failure_analysis.recommended_strategy}"
            )
            self._emit("failure_analysis",
                        round=self._fix_round,
                        patterns=[p.value for p in failure_analysis.patterns],
                        failure_type=failure_analysis.failure_type.value,
                        recommended_strategy=failure_analysis.recommended_strategy,
                        severity=failure_analysis.severity,
                        should_revert=failure_analysis.should_revert)

        # 改进 B (PALADIN): 按失败类型路由 — 依赖缺失时优先环境修复
        strategy = failure_analysis.recommended_strategy
        env_repaired_ids: set[str] = set()
        if strategy == "env_repair":
            console.print("  🔧 失败类型: 依赖/环境问题，优先执行环境修复")
            env_repaired_ids = self._try_env_repair(open_bugs)
            if env_repaired_ids:
                # 环境修复成功的 bug 标记为 fixed，不再交给 Developer 做代码修复
                for bug in open_bugs:
                    if hasattr(bug, "id") and bug.id in env_repaired_ids:
                        self.orc.memory.update_bug(bug.id, status="fixed")
                        logger.info(f"Bug {bug.id} 已通过环境修复解决，跳过代码修复")
                open_bugs = [b for b in open_bugs if not (hasattr(b, "id") and b.id in env_repaired_ids)]
                if not open_bugs:
                    console.print("  ✅ 所有 Bug 已通过环境修复解决")
                    self._transition("test", "环境修复已解决所有 Bug")
                    ir.success = True
                    return ir
                console.print(f"  📊 环境修复解决 {len(env_repaired_ids)} 个 Bug，剩余 {len(open_bugs)} 个交给 Developer")
        elif strategy == "planning_clarify":
            console.print("  📋 失败类型: 规约歧义，记录供下次修复参考")
            self._emit("planning_decision", action="clarify",
                        reason="规约歧义导致修复失败")

        # 反思（round >= 2 时启用）
        reflection = ""
        if self._fix_round >= 2:
            reflection = self._run_reflection(report, self._fix_round, failure_analysis)

        # Git checkpoint
        checkpoint_hash = ""
        if self.orc.git_ops:
            self.orc.git_ops.commit(f"checkpoint: pre-fix round {self._fix_round}")
            checkpoint_hash = self.orc.git_ops.get_current_hash()

        dev = self.orc.code_act_agent.clone()
        dev._changed_files.clear()
        _tokens_before = dev.llm.total_tokens

        console.print(f"  🔧 FIX — 修复 {len(open_bugs)} 个 Bug (round {self._fix_round})")
        self._emit("bug_fix_start", count=len(open_bugs),
                    bugs=[b.title for b in open_bugs[:5]])

        failure_context = ""
        if failure_analysis.recommendations:
            failure_context = "\n".join(f"- {r}" for r in failure_analysis.recommendations)

        fixed_count = dev.fix_bugs(
            open_bugs,
            reflection=reflection,
            failure_context=failure_context,
        )

        self._fix_history.append({
            "round": self._fix_round,
            "total_bugs": len(open_bugs),
            "fixed_count": fixed_count,
        })

        ir.agent_output = f"Fixed {fixed_count}/{len(open_bugs)} bugs"
        ir.success = fixed_count > 0
        ir.files_changed = list(dev._changed_files)
        ir.tokens_used = dev.llm.total_tokens - _tokens_before
        remaining_bugs = len(open_bugs) - fixed_count
        console.print(f"  🔧 修复了 {fixed_count}/{len(open_bugs)} 个 Bug")
        self._emit("bug_fix_done", fixed=fixed_count, total=len(open_bugs),
                    bugs_remaining=remaining_bugs)

        self.orc.code_act_agent._changed_files.update(dev._changed_files)
        self._iteration_changed_files = set(dev._changed_files)

        fix_verified = self._quick_verify()

        # 验证闭环：quick_verify 失败时将 pending_verification 的 Bug 回退为 open
        if not fix_verified:
            for bug in open_bugs:
                if getattr(bug, "status", "") == "pending_verification":
                    self.orc.memory.update_bug(bug.id, status="open")
                    logger.info(f"Bug {bug.id} 修复未通过验证，回退为 open")
        else:
            # 验证通过，正式标记为 fixed
            for bug in open_bugs:
                if getattr(bug, "status", "") == "pending_verification":
                    self.orc.memory.update_bug(bug.id, status="fixed")

        # 回归回滚
        if (failure_analysis.should_revert and not fix_verified
                and checkpoint_hash and self.orc.git_ops):
            console.print(f"  ↩️  检测到回归，回滚到 round {self._fix_round} 修复前")
            self.orc.git_ops.rollback(checkpoint_hash)

        if self.orc.git_ops:
            self.orc.git_ops.commit(f"fix: resolve {fixed_count} bugs (round {self._fix_round})")

        self._record_fix_trajectories(
            open_bugs, fixed_count, self._fix_round,
            reflection=reflection,
            failure_analysis=failure_analysis,
            test_passed=fix_verified,
        )

        # P1: 空修复检测 — 没有实际文件变更的修复不应消耗修复轮次
        if not ir.files_changed and fixed_count == 0:
            logger.warning("FIX 阶段未产生任何文件变更，回退 _fix_round 计数")
            if self._fix_round > 0:
                self._fix_round -= 1

        post_fix_issues = self._smoke_check(prd)
        if post_fix_issues and self._fix_round < self.max_fix_rounds:
            logger.warning(
                f"FIX 后冒烟检查仍有 {len(post_fix_issues)} 个问题，"
                f"保持 fix 阶段继续修复"
            )
            self._fix_round += 1
            self._transition("fix", f"Fix 后仍有 {len(post_fix_issues)} 个问题")
        else:
            self._transition("test", "Fix 完成，进入 Test 验证")
        return ir

    def _run_reflection(self, report: dict, round_num: int,
                        failure_analysis: FailureAnalysis) -> str:
        """结构化反思 — LLM 分析连续失败的根因"""
        prompt_parts = [
            f"## 反思分析 (Round {round_num})",
            f"连续 {round_num} 轮测试未通过，请分析根本原因并建议新策略。",
            f"\n### 当前测试结果",
            f"- 整体通过: {report.get('pass', False)}",
            f"- Bug 数量: {len(report.get('bugs', []))}",
            f"- 质量评分: {report.get('quality_score', 0)}/10",
        ]

        bugs = report.get("bugs", [])
        if bugs:
            prompt_parts.append("\n### Bug 列表")
            for b in bugs[:5]:
                title = b.get("title", "") if isinstance(b, dict) else getattr(b, "title", "")
                desc = b.get("description", "") if isinstance(b, dict) else getattr(b, "description", "")
                prompt_parts.append(f"- {title}: {desc[:100]}")

        if failure_analysis.diagnosis:
            prompt_parts.append(f"\n### 失败模式分析\n{failure_analysis.diagnosis}")

        prompt_parts.append(
            "\n### 请回答\n"
            "1. 连续失败的根本原因是什么？\n"
            "2. 之前的修复方法为什么无效？\n"
            "3. 建议采用什么新的修复策略？\n"
            "4. 是否需要重构而非局部修复？\n"
            "\n请用简洁的中文回答（200字以内）。"
        )

        try:
            response = self.orc.llm_coder.chat(
                messages=[
                    {"role": "system", "content": "你是一位资深软件工程师，擅长分析代码问题的根本原因。"},
                    {"role": "user", "content": "\n".join(prompt_parts)},
                ],
                temperature=0.3, max_tokens=500,
            )
            reflection = response["content"]
            console.print(f"  💭 反思分析: {reflection[:200]}...")
            self._emit("reflection", round=round_num, content=reflection[:500])
            return reflection
        except Exception as e:
            logger.warning(f"反思分析失败: {e}")
            return ""

    def _quick_verify(self) -> bool:
        """P-QG-04 修复后快速验证 — 根据技术栈选择测试命令

        如果测试工具不可用（如 pytest 未安装），视为"无法验证"而非"验证失败"，
        返回 True 让后续 Tester Agent 做完整验证。
        """
        try:
            from autoc.stacks._registry import get_test_command
            cmd = get_test_command(self.orc.workspace_dir)
        except Exception:
            cmd = "python -m pytest tests/ -x --tb=line -q 2>&1"

        try:
            result = self.orc.shell.execute(cmd, timeout=60)
            result_lower = result.lower()

            # 测试工具不可用 → 跳过验证，交给 Tester Agent
            if "no module named pytest" in result_lower or "no module named" in result_lower:
                console.print("  ⏭️  测试工具不可用，跳过快速验证（交给 Tester）")
                return True
            # tests/ 目录不存在 → 无测试可跑，视为通过
            if "no such file or directory" in result_lower and "tests/" in result_lower:
                console.print("  ⏭️  tests/ 目录不存在，跳过快速验证")
                return True
            if "no tests ran" in result_lower or "collected 0 items" in result_lower:
                console.print("  ⏭️  无测试用例，跳过快速验证")
                return True

            # 避免 "ok" 宽泛匹配 "token"/"hook" 等无关词，改用完整词匹配
            has_pass = "passed" in result_lower or bool(re.search(r'\bok\b', result_lower))
            has_fail = "failed" in result_lower or "error" in result_lower
            if has_pass and not has_fail:
                console.print("  ✅ 快速验证通过")
                return True
            short = result.strip().split("\n")[-1][:120] if result.strip() else ""
            console.print(f"  ⚠️  快速验证未通过: {short}")
            return False
        except Exception as e:
            logger.warning(f"快速验证异常: {e}")
            return False

    def _auto_lint_fix(self, low_bugs: list, iteration: int):
        """测试通过后对低优先级 bug 做轻量修复"""
        console.print(f"[cyan]  🔧 自动修复 {len(low_bugs)} 个低优先级问题...[/cyan]")
        try:
            bug_objects = []
            for b in low_bugs:
                if hasattr(b, "title"):
                    bug_objects.append(b)
                elif isinstance(b, dict):
                    bug_obj = BugReport(
                        task_id=b.get("task_id", ""),
                        title=b.get("title", ""),
                        description=b.get("description", ""),
                        severity=b.get("severity", "low"),
                        file_path=b.get("file_path", ""),
                        line_number=b.get("line_number", 0),
                        root_cause=b.get("root_cause", ""),
                        fix_strategy=b.get("fix_strategy", "局部修复"),
                        affected_functions=b.get("affected_functions", []),
                        suggested_fix=b.get("suggested_fix", ""),
                    )
                    self.orc.memory.add_bug_report(bug_obj)
                    bug_objects.append(bug_obj)

            if bug_objects:
                dev = self.orc.code_act_agent.clone()
                fixed = dev.fix_bugs(bug_objects)
                console.print(f"[cyan]  🔧 已修复 {fixed}/{len(bug_objects)} 个问题[/cyan]")
            if self.orc.code_quality:
                self.orc.code_quality.run_all()
            if self.orc.git_ops:
                self.orc.git_ops.commit(
                    f"fix: auto lint-fix low-priority issues (iteration {iteration})"
                )
        except Exception as e:
            logger.warning(f"自动 lint-fix 失败: {e}")

    def _record_fix_trajectories(
        self, bugs, fixed_count, round_num,
        reflection="", failure_analysis=None, test_passed=False,
    ):
        """记录修复轨迹到经验库"""
        if not self.orc.experience:
            return
        patterns = [p.value for p in failure_analysis.patterns] if failure_analysis else []
        for bug in bugs:
            result_str = "fixed" if bug.status == "fixed" else "failed"
            try:
                self.orc.experience.record_fix_trajectory(
                    session_id=self.orc.session_id,
                    round_num=round_num,
                    bug_id=bug.id, bug_title=bug.title,
                    bug_severity=bug.severity, bug_description=bug.description,
                    fix_attempt=getattr(bug, "fix_attempts", 1),
                    strategy="", fix_result=result_str,
                    code_changes=list(self.orc.code_act_agent._changed_files)[:10],
                    test_passed=test_passed, reflection=reflection,
                    failure_patterns=patterns,
                )
            except Exception as e:
                logger.debug(f"记录修复轨迹失败: {e}")

    def _try_env_repair(self, bugs: list) -> set[str]:
        """依赖/环境类失败的自动修复，返回已修复的 bug id 集合。

        两阶段策略（不互斥，可同时执行）:
        1. 规则匹配 — 扫描 bug 中的缺失模块名，直接 pip install
        2. LLM 兜底 — 让 LLM 诊断剩余环境错误并给出修复命令
        """
        import re as _re

        repaired_bug_ids: set[str] = set()
        all_bug_text = ""
        modules_to_install: set[str] = set()
        dep_bug_ids: set[str] = set()

        for b in bugs:
            desc = b.description if hasattr(b, "description") else ""
            title = b.title if hasattr(b, "title") else ""
            bug_id = b.id if hasattr(b, "id") else ""
            text = f"{title} {desc}"
            all_bug_text += text + "\n"
            mods_found = _re.findall(r"no module named ['\"]?(\w+)", text, _re.IGNORECASE)
            mods_found += _re.findall(r"command not found:\s*(\w+)", text, _re.IGNORECASE)
            if mods_found:
                modules_to_install.update(mods_found)
                if bug_id:
                    dep_bug_ids.add(bug_id)

        # 阶段 1: pip install 缺失模块
        if modules_to_install:
            from autoc.core.infra.cn_mirror import pip_install_cmd
            console.print(f"  📦 尝试安装缺失依赖: {', '.join(modules_to_install)}")
            for mod in list(modules_to_install)[:5]:
                try:
                    sandbox = getattr(self.orc, "sandbox", None)
                    if sandbox and hasattr(sandbox, "execute"):
                        cmd = pip_install_cmd(mod)
                        result = sandbox.execute(cmd, timeout=30)
                        exit_code = result.get("exit_code", 1)
                        status = "✅" if exit_code == 0 else "❌"
                        console.print(f"    {status} {cmd}")
                        if exit_code == 0:
                            repaired_bug_ids.update(dep_bug_ids)
                    else:
                        logger.info(f"无沙箱，跳过 pip install {mod}")
                except Exception as e:
                    logger.warning(f"环境修复失败 ({mod}): {e}")

        # 阶段 2: LLM 兜底（总是尝试，不被阶段 1 短路）
        llm_repaired = self._try_env_repair_via_llm(all_bug_text.strip(), bugs)
        repaired_bug_ids.update(llm_repaired)
        return repaired_bug_ids

    _ENV_REPAIR_SYSTEM = (
        "你是一位 DevOps 专家。用户的应用部署后遇到了环境/基础设施错误。\n"
        "请分析错误信息，给出**一条**能在项目根目录执行的 shell 命令来修复问题。\n\n"
        "常见场景和解法:\n"
        "- 'no such table' → 数据库未初始化，如 `flask init-db` 或 `python manage.py migrate`\n"
        "- 'OperationalError: unable to open database' → 目录权限或 DB 文件路径不存在\n"
        "- 'ENOENT: no such file or directory' → 缺少必要目录，如 `mkdir -p data/`\n"
        "- 'role does not exist' → PostgreSQL 用户未创建\n\n"
        "规则:\n"
        "1. 只输出一条 shell 命令，不要解释\n"
        "2. 命令必须是安全的（不能删除文件、不能 DROP）\n"
        "3. 如果无法判断修复方案，输出 SKIP\n"
        "4. 不要输出 markdown 代码块，直接输出命令"
    )

    # 白名单：LLM 建议的命令必须匹配这些模式之一才允许执行
    _ALLOWED_CMD_PATTERNS = [
        r"^flask\s",                          # flask init-db, flask db upgrade
        r"^python\s+manage\.py\s",            # Django manage.py migrate/collectstatic
        r"^python\s+[\w./]+\.py",             # python create_tables.py, python init.py
        r"^python\s+-c\s",                    # python -c "from app import db; ..."
        r"^python3?\s+-m\s+\w",              # python -m flask init-db
        r"^mkdir\s+-p\s",                     # mkdir -p data/ uploads/
        r"^chmod\s+[0-7]{3}\s",              # chmod 755 data/ (但不允许 chmod 777 /)
        r"^npm\s+run\s",                      # npm run build, npm run migrate
        r"^npx\s+\w",                         # npx prisma migrate dev
        r"^pip\s+install\s",                  # pip install xxx
        r"^alembic\s",                        # alembic upgrade head
        r"^touch\s",                          # touch data.db
        r"^export\s+\w+=.*?&&\s+(flask|python|npm|npx)\s",  # export FLASK_APP=app && flask init-db
    ]

    def _try_env_repair_via_llm(self, bug_text: str, bugs: list) -> set[str]:
        """LLM 兜底：让 LLM 诊断环境错误并给出修复命令。返回已修复的 bug id 集合。"""
        import re as _re

        repaired: set[str] = set()
        llm = getattr(self.orc, "llm_coder", None)
        if not llm:
            logger.info("无 LLM 实例，跳过 LLM 环境修复")
            return repaired

        # 收集项目技术栈上下文，帮助 LLM 精准诊断
        tech_context = ""
        try:
            plan = self.orc.memory.project_plan
            if plan and plan.tech_stack:
                tech_context = f"\n\n项目技术栈: {', '.join(plan.tech_stack)}"
        except Exception:
            pass

        try:
            response = llm.chat(
                messages=[
                    {"role": "system", "content": self._ENV_REPAIR_SYSTEM},
                    {"role": "user", "content": (
                        f"应用部署后出现以下错误，请给出修复命令:"
                        f"{tech_context}\n\n{bug_text[:1500]}"
                    )},
                ],
                temperature=0.0,
                max_tokens=200,
            )
            cmd = response.get("content", "").strip()
        except Exception as e:
            logger.warning(f"LLM 环境诊断失败: {e}")
            return repaired

        if not cmd or cmd.upper() == "SKIP" or len(cmd) > 300:
            logger.info(f"LLM 环境修复跳过 (响应: {cmd[:80]})")
            return repaired

        # 去掉可能的 markdown 代码块包装
        if cmd.startswith("```"):
            lines = cmd.split("\n")
            cmd = "\n".join(l for l in lines if not l.startswith("```")).strip()

        # 白名单校验：命令必须匹配允许的模式
        allowed = any(_re.match(pat, cmd) for pat in self._ALLOWED_CMD_PATTERNS)
        if not allowed:
            logger.warning(f"LLM 建议命令不在白名单中，拒绝执行: {cmd}")
            console.print(f"  🚫 LLM 建议命令不在白名单中: {cmd[:100]}")
            return repaired

        # 拒绝多命令链接（分号/管道到 bash/sh）
        if ";" in cmd or "| bash" in cmd or "| sh" in cmd:
            logger.warning(f"LLM 建议命令包含链式执行，拒绝: {cmd}")
            console.print(f"  🚫 LLM 建议命令包含链式执行: {cmd[:100]}")
            return repaired

        console.print(f"  🤖 LLM 环境诊断建议: {cmd[:120]}")
        try:
            sandbox = getattr(self.orc, "sandbox", None)
            if sandbox and hasattr(sandbox, "execute"):
                result = sandbox.execute(cmd, timeout=30)
                exit_code = result.get("exit_code", 1)
                output = result.get("output", "")[:200]
                if exit_code == 0:
                    console.print(f"  ✅ 环境修复成功: {cmd[:80]}")
                    repaired.update(b.id for b in bugs if hasattr(b, "id"))
                else:
                    console.print(f"  ❌ 环境修复失败 (exit={exit_code}): {output[:100]}")
                logger.info(f"LLM env repair: cmd={cmd!r}, exit={exit_code}")
            else:
                logger.info(f"无沙箱，跳过 LLM 建议命令: {cmd}")
        except Exception as e:
            logger.warning(f"LLM 建议命令执行异常: {e}")
        return repaired
