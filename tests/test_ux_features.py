"""产品体验改进（S/R 系列）功能测试

覆盖范围:
  - S-002: Planning 审批门（gates.py 跨线程通信）
  - S-001: quick-start API 参数校验
  - R-013: event_enricher 新增事件类型
  - event_enricher 已有事件回归
"""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest


# ======================= S-002: Planning 审批门 =======================


class TestPlanApprovalGate:
    """gates.py 中的审批门跨线程通信机制"""

    def test_register_and_set_approval(self):
        from autoc.core.orchestrator.gates import (
            register_approval_gate, set_approval_result,
            get_approval_result, cleanup_approval_gate,
        )
        sid = "test-001"
        evt = register_approval_gate(sid)
        assert not evt.is_set()

        ok = set_approval_result(sid, approved=True, feedback="LGTM")
        assert ok is True
        assert evt.is_set()

        result = get_approval_result(sid)
        assert result == {"approved": True, "feedback": "LGTM"}
        cleanup_approval_gate(sid)

    def test_set_approval_for_nonexistent_gate(self):
        from autoc.core.orchestrator.gates import set_approval_result
        ok = set_approval_result("nonexistent-sid", approved=True)
        assert ok is False

    def test_reject_approval(self):
        from autoc.core.orchestrator.gates import (
            register_approval_gate, set_approval_result,
            get_approval_result, cleanup_approval_gate,
        )
        sid = "test-reject"
        evt = register_approval_gate(sid)

        set_approval_result(sid, approved=False, feedback="计划不合理")
        result = get_approval_result(sid)
        assert result["approved"] is False
        assert result["feedback"] == "计划不合理"
        cleanup_approval_gate(sid)

    def test_cleanup_removes_gate(self):
        from autoc.core.orchestrator.gates import (
            register_approval_gate, has_approval_gate, cleanup_approval_gate,
        )
        sid = "test-cleanup"
        register_approval_gate(sid)
        assert has_approval_gate(sid) is True
        cleanup_approval_gate(sid)
        assert has_approval_gate(sid) is False

    def test_cross_thread_wakeup(self):
        """验证跨线程唤醒：主线程注册，子线程 set，主线程 wait"""
        from autoc.core.orchestrator.gates import (
            register_approval_gate, set_approval_result,
            get_approval_result, cleanup_approval_gate,
        )
        sid = "test-cross-thread"
        evt = register_approval_gate(sid)
        woke_up = {"value": False}

        def worker():
            time.sleep(0.1)
            set_approval_result(sid, approved=True, feedback="from-worker")

        t = threading.Thread(target=worker)
        t.start()

        fired = evt.wait(timeout=5.0)
        assert fired is True
        result = get_approval_result(sid)
        assert result["approved"] is True
        assert result["feedback"] == "from-worker"

        t.join()
        cleanup_approval_gate(sid)

    def test_timeout_returns_false(self):
        """验证 wait 超时返回 False"""
        from autoc.core.orchestrator.gates import register_approval_gate, cleanup_approval_gate
        sid = "test-timeout"
        evt = register_approval_gate(sid)

        fired = evt.wait(timeout=0.05)
        assert fired is False
        cleanup_approval_gate(sid)

    def test_multiple_sessions_isolated(self):
        """多个 session 的审批门互不干扰"""
        from autoc.core.orchestrator.gates import (
            register_approval_gate, set_approval_result,
            get_approval_result, cleanup_approval_gate,
        )
        evt_a = register_approval_gate("sid-a")
        evt_b = register_approval_gate("sid-b")

        set_approval_result("sid-a", approved=True, feedback="approve-a")
        assert evt_a.is_set()
        assert not evt_b.is_set()

        result_a = get_approval_result("sid-a")
        result_b = get_approval_result("sid-b")
        assert result_a["approved"] is True
        assert result_b is None

        cleanup_approval_gate("sid-a")
        cleanup_approval_gate("sid-b")


# ======================= Event Enricher =======================


class TestEventEnricher:
    """event_enricher.py 事件富化"""

    def test_enrich_plan_approval_required(self):
        from autoc.server.event_enricher import enrich_event
        event = {
            "type": "plan_approval_required",
            "agent": "system",
            "data": {"timeout_seconds": 600, "plan_md": "# Plan", "session_id": "abc"},
        }
        result = enrich_event(event)
        data = result["data"]
        assert "user_message" in data
        assert "确认" in data["user_message"] or "等待" in data["user_message"]
        assert "approve_plan" in data["available_actions"]
        assert "reject_plan" in data["available_actions"]

    def test_enrich_plan_ready_unchanged(self):
        """回归：plan_ready 事件富化不受影响"""
        from autoc.server.event_enricher import enrich_event
        event = {
            "type": "plan_ready",
            "agent": "system",
            "data": {"plan_md": "# My Plan\nsome content"},
        }
        result = enrich_event(event)
        data = result["data"]
        assert "user_message" in data
        assert "规划完成" in data["user_message"]

    def test_enrich_done_success(self):
        """回归：done 成功事件"""
        from autoc.server.event_enricher import enrich_event
        event = {"type": "done", "agent": "system", "data": {"success": True}}
        result = enrich_event(event)
        assert "完成" in result["data"]["user_message"]

    def test_enrich_done_failure(self):
        """回归：done 失败事件"""
        from autoc.server.event_enricher import enrich_event
        event = {
            "type": "done", "agent": "system",
            "data": {"success": False, "failure_reason": "timeout"},
        }
        result = enrich_event(event)
        assert "retry" in result["data"]["available_actions"] or "modify_requirement" in result["data"]["available_actions"]

    def test_enrich_test_result_with_bugs(self):
        """回归：test_result 有 bug 时的描述"""
        from autoc.server.event_enricher import enrich_event
        event = {
            "type": "test_result", "agent": "system",
            "data": {"tests_passed": 3, "tests_total": 5, "bug_count": 2},
        }
        result = enrich_event(event)
        assert "2" in result["data"]["user_message"]

    def test_enrich_unknown_event_passthrough(self):
        """未注册事件类型不报错，直接透传"""
        from autoc.server.event_enricher import enrich_event
        event = {"type": "some_unknown_event", "data": {"foo": "bar"}}
        result = enrich_event(event)
        assert "user_message" not in result.get("data", {})


# ======================= S-002: Orchestrator _wait_for_plan_approval =======================


class TestOrchestratorPlanApproval:
    """facade.py 中 _wait_for_plan_approval 的集成行为"""

    def _make_mock_orchestrator(self):
        orc = MagicMock()
        orc.session_id = "mock-session"
        orc.memory.plan_md = "# Mock Plan"
        orc._emit = MagicMock()
        return orc

    def test_no_session_id_auto_approve(self):
        """无 session_id 时自动批准"""
        from autoc.core.orchestrator.facade import Orchestrator
        orc = self._make_mock_orchestrator()
        orc.session_id = ""
        result = Orchestrator._wait_for_plan_approval(orc)
        assert result is True

    def test_approval_approved(self):
        """用户批准 → 返回 True"""
        from autoc.core.orchestrator.facade import Orchestrator
        from autoc.core.orchestrator.gates import (
            register_approval_gate, set_approval_result, cleanup_approval_gate,
        )
        orc = self._make_mock_orchestrator()
        sid = orc.session_id

        def approve_async():
            time.sleep(0.05)
            set_approval_result(sid, approved=True)

        t = threading.Thread(target=approve_async)
        t.start()

        result = Orchestrator._wait_for_plan_approval(orc, timeout=5.0)
        assert result is True
        t.join()
        cleanup_approval_gate(sid)

    def test_approval_rejected(self):
        """用户拒绝 → 返回 False"""
        from autoc.core.orchestrator.facade import Orchestrator
        from autoc.core.orchestrator.gates import (
            register_approval_gate, set_approval_result, cleanup_approval_gate,
        )
        orc = self._make_mock_orchestrator()
        sid = orc.session_id

        def reject_async():
            time.sleep(0.05)
            set_approval_result(sid, approved=False, feedback="不满意")

        t = threading.Thread(target=reject_async)
        t.start()

        result = Orchestrator._wait_for_plan_approval(orc, timeout=5.0)
        assert result is False
        t.join()
        cleanup_approval_gate(sid)

    def test_approval_timeout_auto_approve(self):
        """超时 → 自动批准"""
        from autoc.core.orchestrator.facade import Orchestrator
        orc = self._make_mock_orchestrator()

        result = Orchestrator._wait_for_plan_approval(orc, timeout=0.05)
        assert result is True

    def test_emit_event_on_wait(self):
        """等待时应发射 plan_approval_required 事件"""
        from autoc.core.orchestrator.facade import Orchestrator
        from autoc.core.orchestrator.gates import set_approval_result, cleanup_approval_gate
        orc = self._make_mock_orchestrator()
        sid = orc.session_id

        def approve_async():
            time.sleep(0.05)
            set_approval_result(sid, approved=True)

        t = threading.Thread(target=approve_async)
        t.start()

        Orchestrator._wait_for_plan_approval(orc, timeout=5.0)
        orc._emit.assert_called()
        call_args = orc._emit.call_args_list[0]
        assert call_args[0][0] == "plan_approval_required"

        t.join()
        cleanup_approval_gate(sid)
