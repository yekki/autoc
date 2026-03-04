"""完整链路集成测试 — 覆盖 ①→⑦ 全流程

测试链路:
  ① refine_requirement   — 需求优化（跳过/增强/异常降级）
  ② check_workspace      — 工作区检查
  ③ PlanningAgent         — ReAct 规划 → PLAN.md
  ④ post_planning_phase   — 写 PLAN.md + 存内存 + git commit
  ⑤ CodeActAgent          — 基于 PLAN.md 实现
  ⑥ CritiqueAgent         — 评审（LLM / 规则型兜底）
  ⑦ finalize              — 统计 + 技术栈检测 + session 记录

所有 LLM 调用通过 mock 替代，不依赖真实 API Key 或 Docker。
"""

from unittest.mock import MagicMock, patch, PropertyMock
import os

import pytest

from autoc.core.project.models import ProjectStatus, RefinedRequirement
from autoc.core.project.memory import SharedMemory, TaskStatus


# ---------------------------------------------------------------------------
# helpers: 最小化 Orchestrator mock（覆盖所有链路阶段需要的属性）
# ---------------------------------------------------------------------------

def _make_orc(workspace_dir, *, refiner=None, critique=None,
              plan_md="# 目标\n测试\n\n# 实现步骤\n1. 创建 main.py",
              main_report=None, max_rounds=3):
    orc = MagicMock()
    orc.workspace_dir = workspace_dir
    orc.refiner = refiner
    orc.on_event = MagicMock()
    orc._emit = MagicMock()
    orc.presenter = MagicMock()
    orc.experience = None
    orc.memory = SharedMemory()
    orc.file_ops = MagicMock()
    orc.file_ops.list_files.return_value = []
    orc.file_ops.workspace_dir = workspace_dir
    orc.file_ops.write_file = MagicMock()
    orc.file_ops.read_file = MagicMock(return_value="print('hello')")

    orc.llm_default = MagicMock()
    orc.llm_default.total_tokens = 100
    orc.llm_planner = MagicMock()
    orc.llm_planner.total_tokens = 200
    orc.llm_coder = MagicMock()
    orc.llm_coder.total_tokens = 300
    orc.llm_critique = MagicMock()
    orc.llm_critique.total_tokens = 50
    orc.llm_helper = MagicMock()
    orc.llm_helper.total_tokens = 10

    orc.project_manager = MagicMock()
    orc.project_manager.load.return_value = MagicMock(tech_stack=[])
    orc.project_manager.update_status = MagicMock()
    orc.project_manager.get_version.return_value = "1.0.0"

    orc.planner_agent = MagicMock()
    orc.planner_agent.execute_plan.return_value = plan_md

    orc.code_act_agent = MagicMock()
    orc.code_act_agent.max_iterations = 15
    orc.code_act_agent.execute_plan.return_value = main_report or {
        "success": True, "summary": "全部完成", "files_created": ["main.py"],
    }

    orc.critique = critique
    orc.max_rounds = max_rounds
    orc.git_ops = None
    orc._execution_success = False
    orc._refiner_hints = {}
    orc.assess_complexity = MagicMock(return_value="medium")

    return orc


# ======================= ① refine_requirement =======================


class TestRefineRequirement:

    def test_no_refiner_passthrough(self):
        """无 refiner 时需求原样返回"""
        from autoc.core.orchestrator.scheduler import refine_requirement
        orc = _make_orc("/tmp/ws", refiner=None)
        assert refine_requirement(orc, "做个网站") == "做个网站"

    def test_refiner_enhances(self):
        """refiner 增强需求"""
        from autoc.core.orchestrator.scheduler import refine_requirement
        mock_refiner = MagicMock()
        mock_refiner.refine.return_value = RefinedRequirement(
            original="做个网站", refined="创建一个现代化博客",
            quality_before=0.3, quality_after=0.7,
            enhancements=["补充描述"],
        )
        orc = _make_orc("/tmp/ws", refiner=mock_refiner)
        assert refine_requirement(orc, "做个网站") == "创建一个现代化博客"

    def test_refiner_skipped(self):
        """高质量需求跳过优化"""
        from autoc.core.orchestrator.scheduler import refine_requirement
        mock_refiner = MagicMock()
        mock_refiner.refine.return_value = RefinedRequirement(
            original="做个网站", refined="做个网站",
            quality_before=0.8, quality_after=0.8, skipped=True,
        )
        orc = _make_orc("/tmp/ws", refiner=mock_refiner)
        assert refine_requirement(orc, "做个网站") == "做个网站"

    def test_refiner_exception_fallback(self):
        """refiner 异常时降级为原始需求"""
        from autoc.core.orchestrator.scheduler import refine_requirement
        mock_refiner = MagicMock()
        mock_refiner.refine.side_effect = Exception("LLM error")
        orc = _make_orc("/tmp/ws", refiner=mock_refiner)
        assert refine_requirement(orc, "做个网站") == "做个网站"

    def test_no_tech_stack_param(self):
        """refine_requirement 不传 tech_stack"""
        from autoc.core.orchestrator.scheduler import refine_requirement
        mock_refiner = MagicMock()
        mock_refiner.refine.return_value = RefinedRequirement(
            original="x", refined="x", skipped=True, quality_before=0.9,
        )
        orc = _make_orc("/tmp/ws", refiner=mock_refiner)
        refine_requirement(orc, "做个网站")
        assert "tech_stack" not in (mock_refiner.refine.call_args.kwargs or {})


# ======================= ③④ Planning Phase =======================


class TestPlanningPhase:

    @patch("autoc.core.orchestrator.scheduler.post_planning_phase")
    def test_planning_agent_produces_plan(self, _post, tmp_path):
        """PlanningAgent 生成计划 → post_planning_phase 被调用"""
        from autoc.core.orchestrator.scheduler import run_planning_phase

        orc = _make_orc(str(tmp_path), plan_md="# 目标\nHello World")
        result = run_planning_phase(orc, "做个 hello world", incremental=False)

        assert result == "# 目标\nHello World"
        orc.planner_agent.execute_plan.assert_called_once()
        orc.project_manager.update_status.assert_any_call(ProjectStatus.PLANNING)
        _post.assert_called_once_with(orc, "# 目标\nHello World", "做个 hello world")

    @patch("autoc.core.orchestrator.scheduler.post_planning_phase")
    def test_planning_failure_returns_none(self, _post, tmp_path):
        """PlanningAgent 异常 → 返回 None"""
        from autoc.core.orchestrator.scheduler import run_planning_phase

        orc = _make_orc(str(tmp_path))
        orc.planner_agent.execute_plan.side_effect = Exception("LLM 超时")
        result = run_planning_phase(orc, "做个网站", incremental=False)

        assert result is None
        error_calls = [c for c in orc._emit.call_args_list if c.args[0] == "error"]
        assert any("LLM 超时" in c.kwargs.get("message", "") for c in error_calls)

    @patch("autoc.core.orchestrator.scheduler.post_planning_phase")
    def test_incremental_mode_hint(self, _post, tmp_path):
        """incremental=True 时注入增量模式提示"""
        from autoc.core.orchestrator.scheduler import run_planning_phase

        orc = _make_orc(str(tmp_path))
        orc.file_ops.list_files.return_value = ["main.py"]
        run_planning_phase(orc, "添加功能", incremental=True)

        ws_info = orc.planner_agent.execute_plan.call_args.kwargs.get("workspace_info", "")
        assert "增量模式" in ws_info


# ======================= ⑤⑥ Dev/Test + Critique =======================


class TestDevAndTest:

    def test_critique_pass_first_round(self, tmp_path):
        """Critique 通过 → 单轮结束"""
        from autoc.core.orchestrator.scheduler import run_dev_and_test

        mock_critique = MagicMock()
        mock_critique.review_plan.return_value = {
            "passed": True, "total_score": 90, "summary": "优秀",
            "scores": {"correctness": 23, "quality": 22, "completeness": 23, "best_practices": 22},
            "issues": [],
        }
        orc = _make_orc(str(tmp_path), critique=mock_critique)

        run_dev_and_test(orc, "# 计划\n测试")

        assert orc._execution_success is True
        orc.code_act_agent.execute_plan.assert_called_once()
        mock_critique.review_plan.assert_called_once()
        orc.project_manager.update_status.assert_any_call(ProjectStatus.DEVELOPING)
        orc.project_manager.update_status.assert_any_call(ProjectStatus.COMPLETED)

    def test_critique_fail_then_pass(self, tmp_path):
        """Critique 第 1 轮失败 → 第 2 轮通过 (会话持续累积)"""
        from autoc.core.orchestrator.scheduler import run_dev_and_test

        mock_critique = MagicMock()
        mock_critique.review_plan.side_effect = [
            {"passed": False, "total_score": 60, "summary": "需改进",
             "scores": {"correctness": 15, "quality": 15, "completeness": 15, "best_practices": 15},
             "issues": [{"severity": "high", "description": "缺少错误处理",
                         "file_path": "main.py", "line_number": 5, "suggestion": "加 try/except"}]},
            {"passed": True, "total_score": 88, "summary": "已修复",
             "scores": {"correctness": 22, "quality": 22, "completeness": 22, "best_practices": 22},
             "issues": []},
        ]
        orc = _make_orc(str(tmp_path), critique=mock_critique, max_rounds=3)

        run_dev_and_test(orc, "# 计划\n测试")

        assert orc._execution_success is True
        assert orc.code_act_agent.execute_plan.call_count == 2

        second_call = orc.code_act_agent.execute_plan.call_args_list[1]
        feedback_arg = second_call.kwargs.get("feedback", "")
        assert feedback_arg and "缺少错误处理" in feedback_arg

    def test_critique_all_fail_reaches_max(self, tmp_path):
        """Critique 始终失败 → 达到 max_rounds → INCOMPLETE"""
        from autoc.core.orchestrator.scheduler import run_dev_and_test

        mock_critique = MagicMock()
        mock_critique.review_plan.return_value = {
            "passed": False, "total_score": 40, "summary": "质量不足",
            "scores": {"correctness": 10, "quality": 10, "completeness": 10, "best_practices": 10},
            "issues": [{"severity": "high", "description": "未实现核心功能",
                         "file_path": "", "line_number": 0, "suggestion": ""}],
        }
        orc = _make_orc(str(tmp_path), critique=mock_critique, max_rounds=2)

        run_dev_and_test(orc, "# 计划\n测试")

        assert orc._execution_success is False
        assert orc.code_act_agent.execute_plan.call_count == 2
        orc.project_manager.update_status.assert_any_call(ProjectStatus.INCOMPLETE)

    def test_no_critique_with_rule_review(self, tmp_path):
        """无 CritiqueAgent → 规则型兜底评审 → 单轮通过"""
        from autoc.core.orchestrator.scheduler import run_dev_and_test

        orc = _make_orc(str(tmp_path), critique=None)
        orc.memory.files = {"main.py": MagicMock(path="main.py")}

        run_dev_and_test(orc, "# 计划\n测试")

        assert orc._execution_success is True
        orc.code_act_agent.execute_plan.assert_called_once()
        # 无 Critique 时单轮即完成
        orc.project_manager.update_status.assert_any_call(ProjectStatus.COMPLETED)

    def test_critique_exception_degrades_to_pass(self, tmp_path):
        """CritiqueAgent 异常 → 降级自动通过（不反复重试修不了的问题）"""
        from autoc.core.orchestrator.scheduler import run_dev_and_test

        mock_critique = MagicMock()
        mock_critique.review_plan.side_effect = Exception("评审超时")
        orc = _make_orc(str(tmp_path), critique=mock_critique, max_rounds=3)

        run_dev_and_test(orc, "# 计划\n测试")

        assert orc._execution_success is True
        assert orc.code_act_agent.execute_plan.call_count == 1

    def test_code_act_agent_exception_stops_loop(self, tmp_path):
        """CodeActAgent 异常 → 立即终止循环"""
        from autoc.core.orchestrator.scheduler import run_dev_and_test

        mock_critique = MagicMock()
        orc = _make_orc(str(tmp_path), critique=mock_critique)
        orc.code_act_agent.execute_plan.side_effect = Exception("Docker 崩溃")

        run_dev_and_test(orc, "# 计划\n测试")

        assert orc._execution_success is False
        orc.code_act_agent.execute_plan.assert_called_once()
        mock_critique.review_plan.assert_not_called()


# ======================= ①→⑦ 全链路串联 =======================


class TestFullChain:
    """端到端集成测试 — 模拟完整 ①→⑦ 链路"""

    @patch("autoc.core.orchestrator.scheduler.post_planning_phase")
    def test_full_chain_with_critique_pass(self, _post, tmp_path):
        """完整链路: refine → plan → dev → critique(通过) → 成功"""
        from autoc.core.orchestrator.scheduler import (
            refine_requirement, run_planning_phase, run_dev_and_test,
        )

        mock_critique = MagicMock()
        mock_critique.review_plan.return_value = {
            "passed": True, "total_score": 92, "summary": "优秀",
            "scores": {"correctness": 23, "quality": 23, "completeness": 23, "best_practices": 23},
            "issues": [],
        }
        orc = _make_orc(str(tmp_path), critique=mock_critique)

        # ① refine
        req = refine_requirement(orc, "创建命令行应用，打印 hello")
        assert req == "创建命令行应用，打印 hello"

        # ③④ plan
        plan_md = run_planning_phase(orc, req, incremental=False)
        assert plan_md is not None
        assert "目标" in plan_md

        # ⑤⑥ dev + critique
        run_dev_and_test(orc, plan_md)
        assert orc._execution_success is True

        # 验证状态流转
        statuses = [c.args[0] for c in orc.project_manager.update_status.call_args_list]
        assert ProjectStatus.PLANNING in statuses
        assert ProjectStatus.DEVELOPING in statuses
        assert ProjectStatus.COMPLETED in statuses

    @patch("autoc.core.orchestrator.scheduler.post_planning_phase")
    def test_full_chain_planning_failure(self, _post, tmp_path):
        """完整链路: refine → plan(失败) → 不进入 dev"""
        from autoc.core.orchestrator.scheduler import (
            refine_requirement, run_planning_phase,
        )

        orc = _make_orc(str(tmp_path))
        orc.planner_agent.execute_plan.side_effect = Exception("模型不可用")

        req = refine_requirement(orc, "做个网站")
        plan_md = run_planning_phase(orc, req, incremental=False)

        assert plan_md is None
        orc.code_act_agent.execute_plan.assert_not_called()

    @patch("autoc.core.orchestrator.scheduler.post_planning_phase")
    def test_full_chain_no_critique(self, _post, tmp_path):
        """完整链路(无 Critique): refine → plan → dev → 规则评审 → 成功"""
        from autoc.core.orchestrator.scheduler import (
            refine_requirement, run_planning_phase, run_dev_and_test,
        )

        orc = _make_orc(str(tmp_path), critique=None)
        orc.memory.files = {"main.py": MagicMock(path="main.py")}

        req = refine_requirement(orc, "打印 hello")
        plan_md = run_planning_phase(orc, req, incremental=False)
        assert plan_md is not None

        run_dev_and_test(orc, plan_md)
        assert orc._execution_success is True

    @patch("autoc.core.orchestrator.scheduler.post_planning_phase")
    def test_full_chain_critique_iterates(self, _post, tmp_path):
        """完整链路: refine → plan → dev → critique(失败) → dev(修复) → critique(通过)"""
        from autoc.core.orchestrator.scheduler import (
            refine_requirement, run_planning_phase, run_dev_and_test,
        )

        mock_critique = MagicMock()
        mock_critique.review_plan.side_effect = [
            {"passed": False, "total_score": 55, "summary": "功能不完整",
             "scores": {"correctness": 10, "quality": 15, "completeness": 15, "best_practices": 15},
             "issues": [{"severity": "high", "description": "缺少输入验证",
                         "file_path": "main.py", "line_number": 3, "suggestion": ""}]},
            {"passed": True, "total_score": 90, "summary": "已修复",
             "scores": {"correctness": 23, "quality": 22, "completeness": 23, "best_practices": 22},
             "issues": []},
        ]
        orc = _make_orc(str(tmp_path), critique=mock_critique)

        req = refine_requirement(orc, "创建带验证的 CLI")
        plan_md = run_planning_phase(orc, req, incremental=False)
        run_dev_and_test(orc, plan_md)

        assert orc._execution_success is True
        assert orc.code_act_agent.execute_plan.call_count == 2
        assert mock_critique.review_plan.call_count == 2
