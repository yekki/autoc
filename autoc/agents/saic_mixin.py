"""SAIC (Smart Autonomous Iteration Control) Mixin — 从 BaseAgent 拆分

职责：
- 工具调用阶段分类（explore / produce / execute）
- 调用追踪与重复检测
- 四级进度提醒
- 预算耗尽时的工具降级
"""

import logging

logger = logging.getLogger("autoc.agent")


class _SAICMixin:
    """智能迭代控制 — 避免 Agent 在探索阶段停滞"""

    def _classify_tool_phase(self, tool_name: str) -> str:
        """将工具调用分类到 explore / produce / execute 阶段"""
        if tool_name == "ask_helper":
            return "explore"
        return self._TOOL_PHASES.get(tool_name, "execute")

    def _track_tool_call(self, tool_name: str, tool_args: dict):
        """记录工具调用，更新阶段计数和重复检测列表"""
        phase = self._classify_tool_phase(tool_name)
        self._phase_counts[phase] = self._phase_counts.get(phase, 0) + 1
        if phase in ("produce", "execute"):
            self._last_produce_iter = self._iteration_count

        first_arg = str(next(iter(tool_args.values()), ""))[:80] if tool_args else ""
        self._recent_tools.append((tool_name, first_arg))
        if len(self._recent_tools) > 10:
            self._recent_tools = self._recent_tools[-10:]

    progress_degrade_threshold: float = 0.7

    def _check_progress(self) -> tuple[str | None, bool]:
        """检查 Agent 是否停滞，返回 (提醒消息, 是否降级工具)。

        四级提醒，每级只触发一次（通过 _nudge_level 去重）：
          Level 1: 预算过半 + 仍在纯探索
          Level 2: 预算 65-75% + 通用强烈警告
          Level 2.5: 预算 70%+ → 剥离探索类工具
          Level 3: 检测到重复操作（独立于预算）
        """
        base_budget = getattr(self, '_initial_max_iterations', self.max_iterations)
        if base_budget <= 2:
            return None, False

        budget_ratio = self._iteration_count / base_budget
        total_calls = sum(self._phase_counts.values())
        explore_calls = self._phase_counts.get("explore", 0)
        produce_calls = self._phase_counts.get("produce", 0)
        execute_calls = self._phase_counts.get("execute", 0)

        remaining = self.max_iterations - self._iteration_count
        should_degrade = budget_ratio >= self.progress_degrade_threshold

        if budget_ratio >= self.progress_warn_threshold and self._nudge_level < 2:
            self._nudge_level = 2
            msg = (
                f"🚨 迭代预算即将耗尽（已用 {self._iteration_count}/{self.max_iterations}，"
                f"仅剩 {remaining} 次）！请在接下来 1-2 次迭代内完成所有工作并输出最终结果。"
                f"不要再做探索性操作。"
            )
            if should_degrade:
                msg += "\n（探索类工具 read_file/list_files/search_in_files 已被禁用，请直接产出结果。）"
            return msg, should_degrade

        if (budget_ratio >= self.progress_nudge_threshold
                and self._nudge_level < 1
                and total_calls > 0
                and produce_calls == 0 and execute_calls == 0
                and explore_calls / total_calls >= self.progress_explore_limit):
            self._nudge_level = 1
            return (
                f"⚠️ 进度提醒：你已使用 {self._iteration_count}/{self.max_iterations} 次迭代，"
                f"目前全部用于浏览文件（{explore_calls} 次探索，0 次产出/执行）。"
                f"剩余 {remaining} 次迭代，请立即开始核心任务（编写文件、运行命令、输出结果）。"
            ), False

        if len(self._recent_tools) >= 3:
            last3 = self._recent_tools[-3:]
            if last3[0] == last3[1] == last3[2]:
                tool_name, arg_val = last3[0]
                self._recent_tools.clear()
                return (
                    f"⚠️ 检测到重复操作：连续 3 次调用 {tool_name}({arg_val[:40]})。"
                    f"请调整策略，避免无效循环。"
                ), should_degrade

        return None, should_degrade

    def _build_forced_output_nudge(self) -> str:
        """构建最后一次迭代的强制输出指令"""
        return (
            "🛑 这是最后一次迭代。请立即输出完整的最终结果"
            "（JSON 报告 / 代码分析 / 任务总结），不要再调用任何工具。"
            "即使工作未 100% 完成，也请输出当前已有的结果。"
        )
