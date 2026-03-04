"""测试安全门控"""
import pytest
from unittest.mock import MagicMock
from autoc.core.orchestrator.gates import check_token_budget, infer_rollback_commit, AUTOC_INTERNAL_FILES


class TestCheckTokenBudget:
    def test_budget_ok_when_no_budget(self):
        orc = MagicMock()
        orc._token_budget = 0
        assert check_token_budget(orc, "dev") is True

    def test_budget_ok_when_under_limit(self):
        orc = MagicMock()
        orc._token_budget = 10000
        orc.total_tokens = 5000
        assert check_token_budget(orc, "dev") is True

    def test_budget_exceeded(self):
        orc = MagicMock()
        orc._token_budget = 10000
        orc.total_tokens = 15000
        assert check_token_budget(orc, "dev") is False

    def test_budget_warning_at_80_percent(self):
        orc = MagicMock()
        orc._token_budget = 10000
        orc.total_tokens = 8500
        result = check_token_budget(orc, "dev")
        assert result is True

    def test_budget_exact_limit(self):
        orc = MagicMock()
        orc._token_budget = 10000
        orc.total_tokens = 10000
        assert check_token_budget(orc, "dev") is False


class TestAutocInternalFiles:
    def test_contains_expected_files(self):
        assert "autoc-progress.txt" in AUTOC_INTERNAL_FILES
        assert ".autoc.db" in AUTOC_INTERNAL_FILES
        assert ".gitignore" in AUTOC_INTERNAL_FILES
        assert ".git" in AUTOC_INTERNAL_FILES

    def test_contains_wal_files(self):
        assert ".autoc.db-shm" in AUTOC_INTERNAL_FILES
        assert ".autoc.db-wal" in AUTOC_INTERNAL_FILES


class TestInferRollbackCommit:
    def test_no_git_ops_returns_empty(self):
        orc = MagicMock()
        orc.git_ops = None
        result = infer_rollback_commit(orc, ["task-1"])
        assert result == ""

    def test_strategy1_task_id_match(self):
        orc = MagicMock()
        orc.git_ops._run_git.side_effect = [
            (0, "abc1234 chore: init\ndef5678 feat: task-1 impl"),
            (0, "def5678 feat: task-1 impl\nabc1234 chore: init"),
        ]
        result = infer_rollback_commit(orc, ["task-1"])
        assert result == "abc1234"

    def test_strategy2_project_plan(self):
        orc = MagicMock()
        orc.git_ops._run_git.side_effect = [
            (0, "abc1234 chore: init\ndef5678 feat: something"),
            (0, "ghi9012 feat: project plan\ndef5678 feat: something\nabc1234 chore: init"),
        ]
        result = infer_rollback_commit(orc, [])
        assert result == "ghi9012"

    def test_empty_log_returns_empty(self):
        orc = MagicMock()
        orc.git_ops._run_git.return_value = (0, "")
        result = infer_rollback_commit(orc, [])
        assert result == ""

    def test_git_error_returns_empty(self):
        orc = MagicMock()
        orc.git_ops._run_git.return_value = (1, "fatal: not a git repo")
        result = infer_rollback_commit(orc, [])
        assert result == ""
