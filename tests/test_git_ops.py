"""测试 GitOps — 仓库隔离验证、初始化、提交"""

import os
from unittest.mock import patch

from autoc.tools.git_ops import GitOps


class TestVerifyRepoIsolation:
    """_verify_repo_isolation() symlink 与路径规范化"""

    def test_matching_paths_pass(self, tmp_path):
        """相同真实路径应通过隔离验证"""
        git = GitOps(str(tmp_path), auto_init=True)
        assert git._verify_repo_isolation() is True

    def test_symlink_resolved_correctly(self, tmp_path):
        """symlink 路径（如 macOS /var → /private/var）应正确解析"""
        real_dir = tmp_path / "real_workspace"
        real_dir.mkdir()
        link_dir = tmp_path / "link_workspace"
        os.symlink(str(real_dir), str(link_dir))

        git = GitOps(str(link_dir), auto_init=True)
        assert git._initialized is True
        assert git._verify_repo_isolation() is True

    def test_mismatch_rejected(self, tmp_path):
        """repo root 与 workspace 不一致时应拒绝"""
        git = GitOps(str(tmp_path), auto_init=False)
        git._initialized = True

        with patch.object(git, "_run_git") as mock_git:
            mock_git.return_value = (0, "/some/other/path")
            assert git._verify_repo_isolation() is False
            assert git._initialized is False

    def test_git_error_rejected(self, tmp_path):
        """git rev-parse 失败时应拒绝"""
        git = GitOps(str(tmp_path), auto_init=False)
        git._initialized = True

        with patch.object(git, "_run_git") as mock_git:
            mock_git.return_value = (128, "fatal: not a git repo")
            assert git._verify_repo_isolation() is False


class TestEnsureInit:
    """ensure_init() 仓库初始化"""

    def test_init_creates_repo(self, tmp_path):
        git = GitOps(str(tmp_path), auto_init=False)
        assert git._initialized is False
        result = git.ensure_init()
        assert result is True
        assert git._initialized is True
        assert (tmp_path / ".git").is_dir()
        assert (tmp_path / ".gitignore").exists()

    def test_init_idempotent(self, tmp_path):
        git = GitOps(str(tmp_path), auto_init=True)
        assert git._initialized is True
        result = git.ensure_init()
        assert result is True

    def test_auto_init_on_construction(self, tmp_path):
        git = GitOps(str(tmp_path))
        assert git._initialized is True
        assert (tmp_path / ".git").is_dir()


class TestCommit:
    """commit() 提交流程"""

    def test_commit_with_changes(self, tmp_path):
        git = GitOps(str(tmp_path), auto_init=True)
        (tmp_path / "test.py").write_text("print('hello')")
        result = git.commit("test: add test file")
        assert "已提交" in result

    def test_commit_no_changes(self, tmp_path):
        git = GitOps(str(tmp_path), auto_init=True)
        result = git.commit("empty commit")
        assert "跳过" in result

    def test_commit_checks_isolation(self, tmp_path):
        """commit 前应验证仓库隔离"""
        git = GitOps(str(tmp_path), auto_init=True)
        (tmp_path / "file.txt").write_text("data")

        with patch.object(git, "_verify_repo_isolation", return_value=False):
            with patch.object(git, "ensure_init", return_value=False):
                result = git.commit("should fail")
                assert "隔离失败" in result or "跳过" in result


class TestLogAndDiff:
    def test_log_after_commit(self, tmp_path):
        git = GitOps(str(tmp_path), auto_init=True)
        log = git.log()
        assert "init" in log

    def test_diff_empty_on_clean(self, tmp_path):
        git = GitOps(str(tmp_path), auto_init=True)
        assert git.diff() == ""

    def test_get_current_hash(self, tmp_path):
        git = GitOps(str(tmp_path), auto_init=True)
        h = git.get_current_hash()
        assert len(h) >= 7
