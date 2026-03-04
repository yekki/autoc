"""DockerSandbox 单元测试（精简版）

完全 mock subprocess.run / shutil.which，不依赖真实 Docker 环境。
覆盖：构造 / 可用性检测 / 容器生命周期 / 命令执行 / 端口映射 /
      后台进程 / 基础工具安装 / 中国镜像 / setup 脚本 / detach / destroy
"""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from autoc.tools.sandbox import DockerSandbox


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _mock_result(returncode=0, stdout="", stderr=""):
    r = MagicMock(spec=subprocess.CompletedProcess)
    r.returncode = returncode
    r.stdout = stdout
    r.stderr = stderr
    return r


def _make_sandbox(tmp_path, **kwargs):
    defaults = dict(workspace_dir=str(tmp_path), image="python:3.12-slim")
    defaults.update(kwargs)
    return DockerSandbox(**defaults)


# ======================= 构造与镜像选择 =======================


class TestInitAndImage:

    @patch("autoc.core.project.manager.slugify_project_name", return_value="hello-world")
    def test_container_name_from_project(self, _slugify, tmp_path):
        sb = DockerSandbox(workspace_dir=str(tmp_path), project_name="Hello World")
        assert sb.container_name == "autoc-sandbox-hello-world"

    def test_container_name_priority_over_project(self, tmp_path):
        sb = DockerSandbox(
            workspace_dir=str(tmp_path),
            container_name="explicit",
            project_name="My Project",
        )
        assert sb.container_name == "explicit"


# ======================= is_available =======================


class TestIsAvailable:

    @patch("subprocess.run", return_value=_mock_result(returncode=0))
    @patch("shutil.which", return_value="/usr/local/bin/docker")
    def test_docker_available(self, _which, _run, tmp_path):
        assert _make_sandbox(tmp_path).is_available is True

    @patch("shutil.which", return_value=None)
    def test_docker_not_installed(self, _which, tmp_path):
        assert _make_sandbox(tmp_path).is_available is False

    @patch("subprocess.run", return_value=_mock_result(returncode=1))
    @patch("shutil.which", return_value="/usr/local/bin/docker")
    def test_docker_daemon_not_running(self, _which, _run, tmp_path):
        assert _make_sandbox(tmp_path).is_available is False


# ======================= 镜像操作 =======================


class TestImageOps:

    @patch("subprocess.run", return_value=_mock_result(returncode=0))
    def test_image_exists(self, _run, tmp_path):
        assert _make_sandbox(tmp_path)._image_exists() is True

    @patch("subprocess.run", return_value=_mock_result(returncode=1))
    def test_image_not_exists(self, _run, tmp_path):
        assert _make_sandbox(tmp_path)._image_exists() is False

    @patch("subprocess.run", return_value=_mock_result(returncode=0))
    def test_pull_success(self, _run, tmp_path):
        assert _make_sandbox(tmp_path)._pull_image() is True

    @patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="docker pull", timeout=300))
    def test_pull_timeout(self, _run, tmp_path):
        assert _make_sandbox(tmp_path)._pull_image() is False


# ======================= ensure_ready =======================


class TestEnsureReady:

    def test_docker_unavailable_raises(self, tmp_path):
        sb = _make_sandbox(tmp_path)
        sb._available = False
        with pytest.raises(RuntimeError, match="Docker 不可用"):
            sb.ensure_ready()

    def test_image_pull_failure_raises(self, tmp_path):
        sb = _make_sandbox(tmp_path)
        sb._available = True
        with patch.object(sb, "_image_exists", return_value=False), \
             patch.object(sb, "_pull_image", return_value=False):
            with pytest.raises(RuntimeError, match="自动拉取失败"):
                sb.ensure_ready()

    def test_progress_callback_steps(self, tmp_path):
        sb = _make_sandbox(tmp_path)
        sb._available = True
        cb = MagicMock()
        with patch.object(sb, "_image_exists", return_value=False), \
             patch.object(sb, "_pull_image", return_value=True):
            sb.ensure_ready(on_progress=cb)
        steps = [c[0][0] for c in cb.call_args_list]
        assert "image_pull" in steps
        assert "sandbox_ready" in steps


# ======================= _exec_in_container =======================


def _mock_popen(returncode=0, stdout="", stderr="", timeout_on_communicate=False):
    """构造 subprocess.Popen mock，模拟 communicate() 结果"""
    proc = MagicMock()
    proc.returncode = returncode
    if timeout_on_communicate:
        proc.communicate.side_effect = [
            subprocess.TimeoutExpired(cmd="docker exec", timeout=5),
            (stdout, stderr),  # kill 后的第二次 communicate 调用
        ]
    else:
        proc.communicate.return_value = (stdout, stderr)
    proc.kill = MagicMock()
    return proc


class TestExecInContainer:

    def test_no_container_returns_error(self, tmp_path):
        rc, out = _make_sandbox(tmp_path)._exec_in_container("ls")
        assert rc == -1 and "未连接" in out

    @patch("subprocess.Popen")
    def test_success_and_command_format(self, mock_popen, tmp_path):
        mock_popen.return_value = _mock_popen(returncode=0, stdout="hello\n")
        sb = _make_sandbox(tmp_path)
        sb._container_id = "abc123"
        rc, out = sb._exec_in_container("echo hello")
        assert rc == 0 and "hello" in out
        cmd = mock_popen.call_args[0][0]
        assert cmd == [
            "docker", "exec", "-w", "/workspace",
            "abc123", "bash", "-c", "echo hello",
        ]

    @patch("subprocess.Popen")
    def test_stderr_appended(self, mock_popen, tmp_path):
        mock_popen.return_value = _mock_popen(returncode=0, stdout="ok", stderr="warn")
        sb = _make_sandbox(tmp_path)
        sb._container_id = "abc"
        _, out = sb._exec_in_container("cmd")
        assert "[stderr]" in out and "warn" in out

    @patch("subprocess.Popen")
    def test_timeout(self, mock_popen, tmp_path):
        mock_popen.return_value = _mock_popen(returncode=-1, timeout_on_communicate=True)
        sb = _make_sandbox(tmp_path)
        sb._container_id = "abc"
        rc, out = sb._exec_in_container("sleep 999", timeout=5)
        assert rc == -1 and "超时" in out

    @patch("time.sleep")
    @patch("subprocess.Popen")
    def test_retry_on_resource_busy(self, mock_popen, _sleep, tmp_path):
        busy = _mock_popen(returncode=1, stdout="resource temporarily unavailable")
        ok = _mock_popen(returncode=0, stdout="done")
        mock_popen.side_effect = [busy, ok]
        sb = _make_sandbox(tmp_path)
        sb._container_id = "abc"
        rc, _ = sb._exec_in_container("cmd")
        assert rc == 0 and mock_popen.call_count == 2

    @patch("time.sleep")
    @patch("subprocess.Popen")
    def test_retry_exhausted(self, mock_popen, _sleep, tmp_path):
        busy = _mock_popen(returncode=1, stdout="device or resource busy")
        mock_popen.side_effect = [busy, busy, busy]
        sb = _make_sandbox(tmp_path)
        sb._container_id = "abc"
        rc, out = sb._exec_in_container("cmd")
        assert rc == -1 and "重试耗尽" in out


# ======================= execute =======================


class TestExecute:

    @patch.object(DockerSandbox, "_exec_in_container", return_value=(0, "ok"))
    @patch.object(DockerSandbox, "_ensure_container")
    def test_normal_output(self, _ensure, _exec, tmp_path):
        assert _make_sandbox(tmp_path).execute("echo ok") == "ok"

    @patch.object(DockerSandbox, "_exec_in_container", return_value=(0, ""))
    @patch.object(DockerSandbox, "_ensure_container")
    def test_empty_output(self, _ensure, _exec, tmp_path):
        assert _make_sandbox(tmp_path).execute("true") == "(无输出)"

    @patch.object(DockerSandbox, "_exec_in_container", return_value=(1, "error msg"))
    @patch.object(DockerSandbox, "_ensure_container")
    def test_nonzero_exit_code(self, _ensure, _exec, tmp_path):
        result = _make_sandbox(tmp_path).execute("false")
        assert "[退出码: 1]" in result and "error msg" in result

    @patch.object(DockerSandbox, "_exec_in_container")
    @patch.object(DockerSandbox, "_ensure_container")
    def test_long_output_truncated(self, _ensure, _exec, tmp_path):
        _exec.return_value = (0, "x" * 15000)
        result = _make_sandbox(tmp_path).execute("big")
        assert "已截断" in result and len(result) < 15000

    @patch.object(DockerSandbox, "_ensure_container", side_effect=RuntimeError("no docker"))
    def test_container_start_failure(self, _ensure, tmp_path):
        result = _make_sandbox(tmp_path).execute("echo hi")
        assert "沙箱错误" in result


# ======================= execute_background =======================


class TestExecuteBackground:

    @patch.object(DockerSandbox, "_exec_in_container", return_value=(0, "42:/tmp/bg_autoc_42.log"))
    @patch.object(DockerSandbox, "_ensure_container")
    def test_returns_pid(self, _ensure, _exec, tmp_path):
        sb = _make_sandbox(tmp_path)
        pid = sb.execute_background("python -m http.server")
        assert pid == "42" and "42" in sb._bg_pids

    @patch.object(DockerSandbox, "_exec_in_container", return_value=(1, "failed"))
    @patch.object(DockerSandbox, "_ensure_container")
    def test_failure_returns_error(self, _ensure, _exec, tmp_path):
        sb = _make_sandbox(tmp_path)
        result = sb.execute_background("bad cmd")
        assert "错误" in result and sb._bg_pids == []


# ======================= 端口映射 =======================


class TestPortMapping:

    def test_add_new_mapping(self, tmp_path):
        sb = _make_sandbox(tmp_path)
        sb.add_port_mapping(9090, 80)
        assert (9090, 80) in sb.port_mappings

    def test_skip_duplicate_container_port(self, tmp_path):
        sb = _make_sandbox(tmp_path, port_mappings=[(9090, 80)])
        sb.add_port_mapping(9999, 80)
        assert len([p for p in sb.port_mappings if p[1] == 80]) == 1

    def test_add_port_mapping_raises_when_running(self, tmp_path):
        """容器已运行时添加新端口映射会抛出异常（安全策略：容器仅随项目删除时重建）"""
        sb = _make_sandbox(tmp_path)
        sb._container_id = "abc"
        with pytest.raises(RuntimeError, match="容器已运行|项目删除"):
            sb.add_port_mapping(9090, 443)

    @patch("subprocess.run")
    def test_sync_port_mappings_parses_output(self, mock_run, tmp_path):
        mock_run.return_value = _mock_result(
            stdout="3000/tcp -> 0.0.0.0:32768\n8080/tcp -> 0.0.0.0:32769\n"
        )
        sb = _make_sandbox(tmp_path)
        sb._container_id = "abc"
        sb._sync_port_mappings()
        container_ports = {cp for _, cp in sb.port_mappings}
        assert 3000 in container_ports and 8080 in container_ports


# ======================= 容器生命周期 =======================


class TestContainerLifecycle:

    @patch("subprocess.run", return_value=_mock_result(stdout="true\n"))
    def test_ensure_reuses_running(self, mock_run, tmp_path):
        sb = _make_sandbox(tmp_path)
        sb._container_id = "running123"
        sb._ensure_container()
        assert sb._container_id == "running123"

    @patch("subprocess.run")
    def test_try_reuse_success(self, mock_run, tmp_path):
        mock_run.return_value = _mock_result(stdout="true abc123def456 python:3.12-slim\n")
        sb = _make_sandbox(tmp_path)
        assert sb._try_reuse_existing() is True
        assert sb._container_id == "abc123def456"

    @patch("subprocess.run", return_value=_mock_result(returncode=1))
    def test_try_reuse_no_container(self, _run, tmp_path):
        assert _make_sandbox(tmp_path)._try_reuse_existing() is False

    @patch("subprocess.run")
    def test_try_reuse_wrong_image(self, mock_run, tmp_path):
        """镜像不匹配时自动销毁旧容器并返回 False（由调用方重建）"""
        mock_run.return_value = _mock_result(stdout="true abc123 node:22-slim\n")
        sb = _make_sandbox(tmp_path, image="python:3.12-slim")
        assert sb._try_reuse_existing() is False

    @patch.object(DockerSandbox, "_start_action_server")
    @patch.object(DockerSandbox, "_configure_cn_mirrors")
    @patch.object(DockerSandbox, "_install_base_tools")
    @patch("autoc.core.infra.cn_mirror.use_cn_mirror", return_value=False)
    @patch("autoc.core.runtime.preview.find_free_port", return_value=32000)
    @patch("subprocess.run", return_value=_mock_result(stdout="abcdef123456789\n"))
    def test_create_container_success(self, _run, _port, _cn, _tools, _mirrors, _action, tmp_path):
        sb = _make_sandbox(tmp_path)
        sb._create_container()
        assert sb._container_id == "abcdef123456"

    @patch.object(DockerSandbox, "_start_action_server")
    @patch.object(DockerSandbox, "_install_base_tools")
    @patch("autoc.core.infra.cn_mirror.use_cn_mirror", return_value=False)
    @patch("autoc.core.runtime.preview.find_free_port", return_value=32000)
    @patch("subprocess.run", return_value=_mock_result(stdout="abcdef123456789\n"))
    def test_create_container_security_hardening(self, _run, _port, _cn, _tools, _action, tmp_path):
        sb = _make_sandbox(tmp_path)
        sb._create_container()
        cmd = _run.call_args[0][0]
        assert "--security-opt" in cmd
        assert "--cap-drop" in cmd

    @patch("autoc.core.runtime.preview.find_free_port", return_value=32000)
    @patch("subprocess.run", return_value=_mock_result(returncode=1, stderr="out of space"))
    def test_create_container_failure_raises(self, _run, _port, tmp_path):
        with pytest.raises(RuntimeError, match="启动 Docker 容器失败"):
            _make_sandbox(tmp_path)._create_container()



# ======================= 基础工具安装 =======================


class TestInstallBaseTools:

    @patch.object(DockerSandbox, "_exec_in_container", return_value=(0, "/usr/bin/git"))
    def test_all_present_skips_apt(self, _exec, tmp_path):
        sb = _make_sandbox(tmp_path)
        sb._container_id = "abc"
        sb._install_base_tools()
        cmds = [c[0][0] for c in _exec.call_args_list]
        assert not any("apt-get" in c for c in cmds)

    @patch.object(DockerSandbox, "_apt_install_optional")
    @patch.object(DockerSandbox, "_apt_install_with_retry")
    @patch.object(DockerSandbox, "_exec_in_container")
    def test_missing_required_triggers_install(self, _exec, _retry, _opt, tmp_path):
        def which_side(cmd, timeout=60):
            if cmd.startswith("which"):
                tool = cmd.split()[-1]
                return (1, "") if tool in ("git", "curl") else (0, f"/usr/bin/{tool}")
            return (0, "")
        _exec.side_effect = which_side
        sb = _make_sandbox(tmp_path)
        sb._container_id = "abc"
        sb._install_base_tools()
        _retry.assert_called_once()
        installed = _retry.call_args[0][0]
        assert "git" in installed and "curl" in installed


# ======================= apt 安装重试 =======================


class TestAptInstall:

    @patch("time.sleep")
    @patch.object(DockerSandbox, "_exec_in_container")
    def test_success_first_attempt(self, _exec, _sleep, tmp_path):
        calls = iter([(0, ""), (0, ""), (0, "/usr/bin/git")])
        _exec.side_effect = lambda cmd, timeout=60: next(calls)
        sb = _make_sandbox(tmp_path)
        sb._container_id = "abc"
        sb._apt_install_with_retry(["git"])
        _sleep.assert_not_called()

    @patch("time.sleep")
    @patch.object(DockerSandbox, "_exec_in_container", return_value=(1, "error"))
    def test_all_retries_exhausted(self, _exec, _sleep, tmp_path):
        sb = _make_sandbox(tmp_path)
        sb._container_id = "abc"
        sb._apt_install_with_retry(["git"])
        assert _exec.call_count >= 2


# ======================= setup 脚本 =======================


class TestRunSetupScript:

    @patch.object(DockerSandbox, "_exec_in_container", return_value=(1, ""))
    def test_no_script_returns_none(self, _exec, tmp_path):
        sb = _make_sandbox(tmp_path)
        sb._container_id = "abc"
        assert sb.run_setup_script() is None

    @patch.object(DockerSandbox, "_exec_in_container")
    def test_finds_and_runs_script(self, _exec, tmp_path):
        def side_effect(cmd, timeout=60):
            if "test -f .autoc/setup.sh" in cmd:
                return (0, "EXISTS")
            if "bash .autoc/setup.sh" in cmd:
                return (0, "setup done")
            return (1, "")
        _exec.side_effect = side_effect
        sb = _make_sandbox(tmp_path)
        sb._container_id = "abc"
        assert sb.run_setup_script() == "setup done"

    @patch.object(DockerSandbox, "_exec_in_container", return_value=(1, ""))
    def test_only_runs_once(self, _exec, tmp_path):
        sb = _make_sandbox(tmp_path)
        sb._container_id = "abc"
        sb.run_setup_script()
        _exec.reset_mock()
        assert sb.run_setup_script() is None
        _exec.assert_not_called()


# ======================= 后台进程与生命周期 =======================


class TestBackgroundAndLifecycle:

    def test_stop_background_processes(self, tmp_path):
        sb = _make_sandbox(tmp_path)
        sb._container_id = "abc"
        sb._bg_pids = ["100", "200"]
        with patch.object(sb, "_exec_in_container"):
            sb.stop_background_processes()
        assert sb._bg_pids == []

    def test_detach_clears_state(self, tmp_path):
        sb = _make_sandbox(tmp_path)
        sb._container_id = "abc"
        sb._bg_pids = ["1"]
        sb.detach()
        assert sb._container_id is None and sb._bg_pids == []

    @patch("subprocess.run", return_value=_mock_result())
    def test_destroy_removes_container(self, mock_run, tmp_path):
        sb = _make_sandbox(tmp_path)
        sb._container_id = "abc123"
        sb.destroy()
        assert sb._container_id is None
        assert "rm" in mock_run.call_args[0][0]

    @patch("subprocess.run", side_effect=Exception("cannot rm"))
    def test_destroy_handles_exception(self, _run, tmp_path):
        sb = _make_sandbox(tmp_path)
        sb._container_id = "abc"
        sb.destroy()
        assert sb._container_id is None


# ======================= 中国镜像 =======================


class TestCnMirrors:

    @patch.object(DockerSandbox, "_exec_in_container", return_value=(0, ""))
    def test_configures_all_three(self, _exec, tmp_path):
        sb = _make_sandbox(tmp_path)
        sb._container_id = "abc"
        with patch("autoc.core.infra.cn_mirror.PIP_INDEX_URL", "x"), \
             patch("autoc.core.infra.cn_mirror.PIP_TRUSTED_HOST", "x"), \
             patch("autoc.core.infra.cn_mirror.NPM_REGISTRY", "x"), \
             patch("autoc.core.infra.cn_mirror.GO_PROXY", "x"):
            sb._configure_cn_mirrors()
        cmds = [c[0][0] for c in _exec.call_args_list]
        assert any("pip.conf" in c for c in cmds)
        assert any(".npmrc" in c for c in cmds)
        assert any("GOPROXY" in c for c in cmds)

    @patch.object(DockerSandbox, "_exec_in_container", return_value=(1, "not found"))
    def test_skips_missing_tools(self, _exec, tmp_path):
        sb = _make_sandbox(tmp_path)
        sb._container_id = "abc"
        with patch("autoc.core.infra.cn_mirror.PIP_INDEX_URL", "x"), \
             patch("autoc.core.infra.cn_mirror.PIP_TRUSTED_HOST", "x"), \
             patch("autoc.core.infra.cn_mirror.NPM_REGISTRY", "x"), \
             patch("autoc.core.infra.cn_mirror.GO_PROXY", "x"):
            sb._configure_cn_mirrors()
        assert _exec.call_count == 3  # 只调用 3 次 which
