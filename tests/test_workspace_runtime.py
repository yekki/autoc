"""WorkspaceRuntime 单元测试"""

import os
import pytest

from autoc.core.runtime.workspace import (
    WorkspaceRuntime,
    LocalWorkspaceRuntime,
    DockerWorkspaceRuntime,
    RemoteWorkspaceRuntime,
    RuntimeInfo,
    create_workspace_runtime,
)


class TestLocalWorkspaceRuntime:
    """本地运行时测试"""

    def _make_runtime(self, tmp_path):
        return LocalWorkspaceRuntime(str(tmp_path))

    def test_name(self, tmp_path):
        rt = self._make_runtime(tmp_path)
        assert rt.name == "local"

    def test_read_write_file(self, tmp_path):
        rt = self._make_runtime(tmp_path)
        rt.write_file("hello.txt", "Hello, World!")
        content = rt.read_file("hello.txt")
        assert content == "Hello, World!"

    def test_write_creates_parent_dirs(self, tmp_path):
        rt = self._make_runtime(tmp_path)
        rt.write_file("a/b/c.txt", "nested")
        assert rt.file_exists("a/b/c.txt")
        assert rt.read_file("a/b/c.txt") == "nested"

    def test_file_exists(self, tmp_path):
        rt = self._make_runtime(tmp_path)
        assert not rt.file_exists("nope.txt")
        rt.write_file("yes.txt", "y")
        assert rt.file_exists("yes.txt")

    def test_delete_file(self, tmp_path):
        rt = self._make_runtime(tmp_path)
        rt.write_file("del.txt", "del")
        assert rt.delete_file("del.txt") is True
        assert not rt.file_exists("del.txt")
        assert rt.delete_file("del.txt") is False

    def test_mkdir(self, tmp_path):
        rt = self._make_runtime(tmp_path)
        rt.mkdir("x/y/z")
        assert os.path.isdir(tmp_path / "x" / "y" / "z")

    def test_list_files_flat(self, tmp_path):
        rt = self._make_runtime(tmp_path)
        rt.write_file("a.py", "a")
        rt.write_file("b.py", "b")
        files = rt.list_files()
        assert "a.py" in files
        assert "b.py" in files

    def test_list_files_recursive(self, tmp_path):
        rt = self._make_runtime(tmp_path)
        rt.write_file("src/main.py", "main")
        rt.write_file("src/utils/helper.py", "helper")
        files = rt.list_files(".", recursive=True)
        assert any("main.py" in f for f in files)
        assert any("helper.py" in f for f in files)

    def test_list_files_skips_hidden(self, tmp_path):
        rt = self._make_runtime(tmp_path)
        rt.write_file("visible.txt", "yes")
        os.makedirs(tmp_path / ".git", exist_ok=True)
        (tmp_path / ".git" / "config").write_text("gitconfig")
        files = rt.list_files(".", recursive=True)
        assert all(".git" not in f for f in files)

    def test_path_escape_raises(self, tmp_path):
        rt = self._make_runtime(tmp_path)
        with pytest.raises(ValueError, match="路径越界"):
            rt.read_file("../../etc/passwd")

    def test_execute(self, tmp_path):
        rt = self._make_runtime(tmp_path)
        output = rt.execute("echo hello")
        assert "hello" in output

    def test_execute_timeout(self, tmp_path):
        rt = self._make_runtime(tmp_path)
        output = rt.execute("sleep 10", timeout=1)
        assert "超时" in output

    def test_execute_background(self, tmp_path):
        rt = self._make_runtime(tmp_path)
        pid = rt.execute_background("sleep 0.1")
        assert pid.isdigit()

    def test_is_available(self, tmp_path):
        rt = self._make_runtime(tmp_path)
        assert rt.is_available() is True

    def test_get_info(self, tmp_path):
        rt = self._make_runtime(tmp_path)
        info = rt.get_info()
        assert isinstance(info, RuntimeInfo)
        assert info.name == "local"
        assert info.available is True


class TestDockerWorkspaceRuntime:
    """Docker 运行时测试（使用 Mock Sandbox）"""

    class MockSandbox:
        is_available = True
        image = "python:3.12-slim"
        _container_id = "abc123"

        def execute(self, command, timeout=60):
            return f"[mock] {command}"

        def execute_background(self, command):
            return "mock-pid-1"

        def stop_background_processes(self):
            pass

    def test_file_ops_delegate_to_local(self, tmp_path):
        """文件操作应代理给 LocalWorkspaceRuntime"""
        sandbox = self.MockSandbox()
        rt = DockerWorkspaceRuntime(str(tmp_path), sandbox)
        rt.write_file("test.txt", "hello")
        assert rt.read_file("test.txt") == "hello"
        assert rt.file_exists("test.txt")
        assert "test.txt" in rt.list_files()

    def test_execute_delegates_to_sandbox(self, tmp_path):
        """命令执行应代理给 Sandbox"""
        sandbox = self.MockSandbox()
        rt = DockerWorkspaceRuntime(str(tmp_path), sandbox)
        output = rt.execute("ls -la")
        assert "[mock] ls -la" in output

    def test_name(self, tmp_path):
        rt = DockerWorkspaceRuntime(str(tmp_path), self.MockSandbox())
        assert rt.name == "docker"

    def test_get_info(self, tmp_path):
        rt = DockerWorkspaceRuntime(str(tmp_path), self.MockSandbox())
        info = rt.get_info()
        assert info.name == "docker"
        assert info.details["container"] == "abc123"


class TestRemoteWorkspaceRuntime:
    """远程运行时测试"""

    def test_not_implemented_methods(self, tmp_path):
        rt = RemoteWorkspaceRuntime(str(tmp_path), api_endpoint="https://api.example.com")
        with pytest.raises(NotImplementedError):
            rt.read_file("test.txt")

    def test_is_available_without_endpoint(self, tmp_path):
        rt = RemoteWorkspaceRuntime(str(tmp_path))
        assert rt.is_available() is False

    def test_is_available_with_endpoint(self, tmp_path):
        rt = RemoteWorkspaceRuntime(str(tmp_path), api_endpoint="https://api.example.com")
        assert rt.is_available() is True

    def test_get_info(self, tmp_path):
        rt = RemoteWorkspaceRuntime(str(tmp_path), api_endpoint="https://x.com")
        info = rt.get_info()
        assert info.name == "remote"
        assert info.details["endpoint"] == "https://x.com"


class TestCreateWorkspaceRuntime:
    """工厂函数测试"""

    def test_create_local(self, tmp_path):
        rt = create_workspace_runtime("local", str(tmp_path))
        assert isinstance(rt, LocalWorkspaceRuntime)

    def test_create_docker_without_sandbox_raises(self, tmp_path):
        with pytest.raises(RuntimeError, match="DockerSandbox"):
            create_workspace_runtime("docker", str(tmp_path))

    def test_create_docker_with_sandbox(self, tmp_path):
        class FakeSandbox:
            is_available = True
        rt = create_workspace_runtime("docker", str(tmp_path), sandbox=FakeSandbox())
        assert isinstance(rt, DockerWorkspaceRuntime)

    def test_create_remote(self, tmp_path):
        rt = create_workspace_runtime(
            "remote", str(tmp_path),
            config={"api_endpoint": "https://api.example.com"},
        )
        assert isinstance(rt, RemoteWorkspaceRuntime)

    def test_create_unknown_raises(self, tmp_path):
        with pytest.raises(ValueError, match="未知运行时类型"):
            create_workspace_runtime("kubernetes", str(tmp_path))
