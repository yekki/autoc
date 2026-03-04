#!/usr/bin/env python3
"""AutoC Benchmark — 持续效果度量体系

跑基线 → 做优化 → 再跑 → 自动对比 → 看趋势。

用法:
    # 跑全部用例，打标签存结果
    python scripts/benchmark.py run --tag baseline

    # 只跑指定用例
    python scripts/benchmark.py run --tag baseline --cases hello,calculator

    # 对比两次结果
    python scripts/benchmark.py compare baseline after_edit_file

    # 查看历史所有运行
    python scripts/benchmark.py history

    # 查看 Token 趋势（所有用例）
    python scripts/benchmark.py trend

    # 查看指定用例的耗时趋势并导出报告
    python scripts/benchmark.py trend --case flask_todo --metric elapsed --export

    # 导出对比报告（Markdown）
    python scripts/benchmark.py compare baseline current --export

前置条件:
    1. config/models.json 已配置 API Key
    2. Docker 已运行
"""

import argparse
import concurrent.futures
import json
import os
import platform
import signal
import subprocess
import sys
import tempfile
import threading as _threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
_scripts_dir = os.path.dirname(os.path.abspath(__file__))
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

RESULTS_DIR = os.path.join(_project_root, "benchmarks", "results")
REPORT_DIR = os.path.join(_project_root, "benchmarks", "reports")
RUNNING_DIR = os.path.join(_project_root, "benchmarks", "running")
LOG_DIR = os.path.join(_project_root, "benchmarks", "logs")

DEFAULT_CASE_TIMEOUT = 600  # 单用例默认超时 10 分钟

# ──────────────────────────── 子模块导入 ────────────────────────────
# 数据模型、分析命令已拆分到 benchmark_lib 包，benchmark.py 保留执行引擎
from benchmark_lib.models import (
    _pid_alive, BenchmarkLiveWriter, SCHEMA_VERSION,
    CaseResult, BenchmarkRun,
)
from benchmark_lib.analysis import (
    show_trend, compare_runs, show_history,
    _list_tags, _load_result_silent, _print_summary, _fmt_delta,
    _check_data_integrity, _find_previous_tag,
)

# 为 _save_result / _generate_run_report 保留 _find_previous_tag 和 _load_result_silent
# （analysis 模块已导出，直接复用）

BENCHMARK_CASES = [
    {
        "name": "hello",
        "complexity": "trivial",
        "max_iterations": 5,
        "description": "Hello World 冒烟测试",
        "expected_files": ["main.py"],
        # host_checks: 宿主机可安全执行（只依赖 Python 标准库）
        "host_checks": ["python -m py_compile main.py"],
        # runtime_checks: 需要项目依赖，best-effort（失败不影响 quality_verified）
        "runtime_checks": ["python main.py"],
    },
    {
        "name": "calculator",
        "complexity": "simple",
        "max_iterations": 15,
        "description": "Python Calculator 类（四则运算 + 验证）",
        "expected_files": ["calculator.py", "main.py"],
        "host_checks": [
            "python -m py_compile calculator.py",
            "python -m py_compile main.py",
        ],
        "runtime_checks": [
            "python -c \"from calculator import Calculator; c = Calculator(); assert c.add(1, 2) == 3\"",
        ],
    },
    {
        "name": "flask_config",
        "complexity": "medium",
        "max_iterations": 15,
        "description": "Flask App Factory + CORS + 日志配置",
        "expected_files": ["requirements.txt"],
        "host_checks": [
            "python -m py_compile app.py || python -m py_compile app/__init__.py",
        ],
        "runtime_checks": [
            'python -c "import os; os.environ.setdefault(\'FLASK_SECRET_KEY\',\'test\'); __import__(\'app\')"',
        ],
    },
    {
        "name": "flask_todo",
        "complexity": "complex",
        "max_iterations": 20,
        "description": "Flask Todo REST API + SQLite",
        "expected_files": ["app.py", "requirements.txt"],
        "host_checks": [
            "python -m py_compile app.py",
            "python -m py_compile database.py || python -m py_compile models.py || true",
        ],
        "runtime_checks": [
            # L2: 基础导入验证
            'python -c "from app import app; assert app is not None" || python -c "from app import create_app; assert create_app() is not None"',
        ],
        # L3: CRUD 端到端验证（仅用标准库，兼容 app 实例和 factory 模式）
        "l3_checks": [
            """python -c "
import subprocess, time, sys, os, json, random
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

PORT = random.randint(49152, 65500)
# 兼容两种 Flask 启动方式：直接 app 实例 or create_app() factory
startup_code = (
    'try:\\n'
    '    from app import app\\n'
    'except ImportError:\\n'
    '    from app import create_app; app = create_app()\\n'
    'app.run(host=\"127.0.0.1\", port=%d, debug=False)' % PORT
)
env = {**os.environ, 'FLASK_APP': 'app.py', 'FLASK_ENV': 'testing'}
proc = subprocess.Popen(
    [sys.executable, '-c', startup_code],
    env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

def http_request(url, data=None, method='GET'):
    '''urllib wrapper: 返回 (status, body) 而非对 4xx/5xx 抛异常'''
    headers = {'Content-Type': 'application/json'} if data else {}
    req = Request(url, data=data, headers=headers, method=method)
    try:
        resp = urlopen(req, timeout=5)
        return resp.status, resp.read()
    except HTTPError as e:
        return e.code, e.read()

try:
    # 等待 Flask 启动，最多重试 5 次（共约 5s）
    for i in range(5):
        time.sleep(1)
        if proc.poll() is not None:
            raise RuntimeError(f'Flask exited (code={proc.returncode}): {proc.stderr.read().decode()[:200]}')
        try:
            urlopen(f'http://127.0.0.1:{PORT}/', timeout=1)
            break
        except HTTPError:
            break  # 收到 HTTP 响应（如 404）说明服务已就绪
        except (URLError, OSError):
            if i == 4:
                raise RuntimeError('Flask did not start within 5s')

    base = f'http://127.0.0.1:{PORT}'
    # 探测 API 路径：plan 指定 /api/todos，但 Agent 可能用 /todos
    for prefix in ('/api/todos', '/todos'):
        status, _ = http_request(f'{base}{prefix}')
        if status != 404:
            todos_path = prefix
            break
    else:
        raise RuntimeError('Neither /api/todos nor /todos responded (both 404)')
    # POST 创建
    body = json.dumps({'title': 'benchmark_test'}).encode()
    status, _ = http_request(f'{base}{todos_path}', data=body, method='POST')
    assert status in (200, 201), f'POST {todos_path} failed: {status}'
    # GET 列表
    status, raw = http_request(f'{base}{todos_path}')
    assert status == 200, f'GET {todos_path} failed: {status}'
    data = json.loads(raw)
    assert isinstance(data, (list, dict)), f'GET {todos_path} unexpected type: {type(data)}'
    print('L3 CRUD OK: POST+GET verified')
finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
" """,
        ],
    },
    {
        "name": "calculator_extend",
        "complexity": "medium",
        "max_iterations": 15,
        "description": "在已有 Calculator 基础上增加历史记录功能（验证 edit_file）",
        "expected_files": ["calculator.py", "main.py"],
        "host_checks": [
            "python -m py_compile calculator.py",
            "python -m py_compile main.py",
        ],
        "runtime_checks": [
            'python -c "from calculator import Calculator; c = Calculator(); c.add(1,2); assert len(c.history) >= 1"',
        ],
        "seed_files": {
            "calculator.py": (
                "class Calculator:\n"
                "    def add(self, a: float, b: float) -> float:\n"
                "        return a + b\n\n"
                "    def subtract(self, a: float, b: float) -> float:\n"
                "        return a - b\n\n"
                "    def multiply(self, a: float, b: float) -> float:\n"
                "        return a * b\n\n"
                "    def divide(self, a: float, b: float) -> float:\n"
                "        if b == 0:\n"
                "            raise ValueError('Cannot divide by zero')\n"
                "        return a / b\n"
            ),
            "main.py": (
                "from calculator import Calculator\n\n"
                "def main():\n"
                "    calc = Calculator()\n"
                "    print('Calculator ready. Enter: num1 op num2')\n"
                "    line = input().strip()\n"
                "    parts = line.split()\n"
                "    a, op, b = float(parts[0]), parts[1], float(parts[2])\n"
                "    ops = {'+': calc.add, '-': calc.subtract,\n"
                "           '*': calc.multiply, '/': calc.divide}\n"
                "    print(ops[op](a, b))\n\n"
                "if __name__ == '__main__':\n"
                "    main()\n"
            ),
        },
    },
]

# 默认运行的核心用例（不含 hello 冒烟测试和增量用例）
CORE_CASES = ["calculator", "flask_config", "flask_todo"]


# ──────────────────────────── 环境信息采集 ────────────────────────────


def _collect_environment() -> dict:
    """采集运行环境信息，用于可重复性"""
    env: dict = {
        "python_version": platform.python_version(),
        "os": f"{platform.system()} {platform.release()}",
        "arch": platform.machine(),
    }
    try:
        docker_ver = subprocess.check_output(
            ["docker", "--version"], stderr=subprocess.DEVNULL,
        ).decode().strip()
        env["docker"] = docker_ver
    except Exception:
        env["docker"] = "unknown"

    try:
        from autoc.core.llm.model_config import ModelConfigManager
        mcm = ModelConfigManager()
        active = mcm.data.get("active", {})
        coder_cfg = active.get("coder", {})
        env["model"] = coder_cfg.get("model", "") or ""
        env["provider"] = coder_cfg.get("provider", "") or ""
    except Exception:
        env["model"] = ""
        env["provider"] = ""

    # Fallback: ModelConfigManager 失败或返回空值时，直接读 config/models.json
    if not env.get("model") or not env.get("provider"):
        try:
            cfg_path = os.path.join(_project_root, "config", "models.json")
            if os.path.exists(cfg_path):
                with open(cfg_path) as f:
                    raw = json.load(f)
                active = raw.get("active", {})
                coder_cfg = active.get("coder", {})
                env["model"] = env.get("model") or coder_cfg.get("model", "unknown")
                env["provider"] = env.get("provider") or coder_cfg.get("provider", "unknown")
        except Exception:
            pass
    if not env.get("model"):
        env["model"] = "unknown"
    if not env.get("provider"):
        env["provider"] = "unknown"

    return env


# ──────────────────────────── 执行引擎 ────────────────────────────


def _get_git_info() -> tuple[str, bool]:
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=_project_root, stderr=subprocess.DEVNULL,
        ).decode().strip()
        dirty = bool(subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=_project_root, stderr=subprocess.DEVNULL,
        ).decode().strip())
        return commit, dirty
    except Exception:
        return "unknown", False


def _build_event_logger():
    """构建事件记录器，实时打印关键事件并记录时间戳"""
    events: list[dict] = []

    def on_event(event: dict):
        event["_ts"] = time.time()
        events.append(event)
        etype = event.get("type", "")
        data = event.get("data", {})

        if etype == "sandbox_ready":
            console.print("  [green]✓ 沙箱就绪[/green]")
        elif etype == "planning_analyzing":
            console.print("  [cyan]📋 PlanningAgent 开始分析需求...[/cyan]")
        elif etype == "plan_ready":
            plan_len = len(data.get("plan_md", ""))
            console.print(f"  [green]✓ PLAN.md 已生成 ({plan_len} 字符)[/green]")
        elif etype == "phase_start":
            console.print(f"  [bold blue]▸ {data.get('phase')}: {data.get('title')}[/bold blue]")
        elif etype == "iteration_start":
            console.print(f"  [dim]  迭代 {data.get('iteration')} — {data.get('phase', '')}[/dim]")
        elif etype == "iteration_done":
            phase = data.get("phase", "")
            ok = data.get("success", False)
            secs = data.get("elapsed_seconds", 0)
            if phase == "critique":
                icon = "[green]✅[/green]" if ok else "[yellow]⚠[/yellow]"
                console.print(f"  {icon} Critique 评审{'通过' if ok else '未通过'} ({secs:.1f}s)")
            elif phase == "rule_review":
                icon = "[green]✓[/green]" if ok else "[yellow]⚠[/yellow]"
                console.print(f"  {icon} 规则评审{'通过' if ok else '未通过'}")
        elif etype == "execution_complete":
            console.print("  [bold green]✅ 执行完成[/bold green]")
        elif etype == "execution_failed":
            reason = data.get("failure_reason", "")[:80]
            console.print(f"  [bold red]❌ 执行失败: {reason}[/bold red]")
        elif etype == "summary":
            console.print("  [dim]📊 生成总结报告...[/dim]")
        elif etype == "done":
            ok = data.get("success", False)
            console.print(f"  [bold]{'✅' if ok else '❌'} 全流程结束[/bold]")

    return on_event, events


_PROGRESS_EVENTS = frozenset({
    "sandbox_preparing", "sandbox_ready",
    "planning_analyzing", "plan_ready",
    "phase_start", "iteration_start", "iteration_done",
    "task_start", "task_complete", "task_verified",
    "file_created", "test_result",
    "tool_call",
    "execution_complete", "execution_failed",
    "summary", "done",
})


def _simplify_event_data(etype: str, data: dict) -> dict:
    """提取事件中用于进度展示的关键字段，剥离大体积数据"""
    if etype == "sandbox_preparing":
        return {"step": data.get("step", ""), "message": data.get("message", ""), "progress": data.get("progress", 0)}
    if etype == "plan_ready":
        return {"plan_length": len(data.get("plan_md", ""))}
    if etype == "phase_start":
        return {"phase": data.get("phase", ""), "title": data.get("title", "")}
    if etype in ("iteration_start", "iteration_done"):
        return {k: data[k] for k in ("iteration", "phase", "success", "elapsed_seconds") if k in data}
    if etype == "task_start":
        return {"task_id": data.get("task_id", ""), "task_title": data.get("task_title", "") or data.get("title", "")}
    if etype == "task_complete":
        return {
            "task_id": data.get("task_id", ""),
            "task_title": data.get("task_title", "") or data.get("title", ""),
            "success": data.get("success", True),
            "tokens_used": data.get("tokens_used", 0),
        }
    if etype == "task_verified":
        return {"task_id": data.get("task_id", ""), "passes": data.get("passes", False)}
    if etype == "file_created":
        path = data.get("path", "") or data.get("file", "")
        # 只保留文件名部分，路径过长时截断
        filename = path.split("/")[-1] if path else ""
        return {"path": filename, "full_path": path[:80], "language": data.get("language", "")}
    if etype == "test_result":
        return {
            "bug_count": data.get("bug_count", 0),
            "verified_tasks": data.get("verified_tasks", 0),
            "total_tasks": data.get("total_tasks", 0),
        }
    if etype == "tool_call":
        tool = data.get("tool", "")
        args = str(data.get("args", ""))
        # 保留第一个有意义的参数值（通常是路径或命令）
        return {"tool": tool, "args": args[:80] if args else ""}
    if etype == "execution_failed":
        return {"failure_reason": str(data.get("failure_reason", ""))[:100]}
    if etype == "done":
        return {"success": data.get("success", False)}
    return {}


_PIPELINE_STAGES = [
    ("sandbox",   "沙箱准备",       ["sandbox_preparing"],      ["sandbox_ready"]),
    ("refine",    "需求优化",       ["iteration_done:refine"],   ["iteration_done:refine"]),
    ("planning",  "需求分析与规划", ["planning_analyzing"],      ["plan_ready"]),
    ("dev_test",  "开发与评审",     ["execution_start"],         ["execution_complete", "execution_failed"]),
    ("finalize",  "收尾与总结",     ["summary"],                 ["done"]),
    ("preview",   "预览生成",       ["preview_ready"],           ["preview_ready"]),
]


def _compute_stage_timings(events: list[dict]) -> list[dict]:
    """从事件流中提取各核心阶段的耗时和状态"""
    ts_by_key: dict[str, list[float]] = {}
    for ev in events:
        etype = ev.get("type", "")
        ts = ev.get("_ts", 0)
        data = ev.get("data", {})
        if not ts:
            continue
        ts_by_key.setdefault(etype, []).append(ts)
        if etype == "iteration_done" and "phase" in data:
            synthetic = f"iteration_done:{data['phase']}"
            ts_by_key.setdefault(synthetic, []).append(ts)

    stages = []
    for stage_id, label, start_types, end_types in _PIPELINE_STAGES:
        start_ts = None
        end_ts = None
        for st in start_types:
            if st in ts_by_key:
                start_ts = ts_by_key[st][0]
                break
        for et in end_types:
            if et in ts_by_key:
                end_ts = ts_by_key[et][-1]
                break

        if start_ts and end_ts and end_ts >= start_ts:
            stages.append({
                "id": stage_id, "label": label,
                "duration": round(end_ts - start_ts, 1),
                "status": "pass",
            })
        elif start_ts and not end_ts:
            stages.append({
                "id": stage_id, "label": label,
                "duration": None,
                "status": "timeout",
            })
        else:
            stages.append({
                "id": stage_id, "label": label,
                "duration": None,
                "status": "skip",
            })
    return stages


def _extract_profile(events: list[dict], result: dict) -> dict:
    """从事件流中提取瓶颈分析数据"""
    profile: dict = {"stage_timings": {}, "tool_calls": {}, "tool_errors": {}, "agent_tokens": {}}

    stages = _compute_stage_timings(events)
    for s in stages:
        if s["duration"] is not None:
            profile["stage_timings"][s["id"]] = s["duration"]

    for ev in events:
        if ev.get("type") == "tool_call":
            tool = ev.get("data", {}).get("tool", "unknown")
            profile["tool_calls"][tool] = profile["tool_calls"].get(tool, 0) + 1
        elif ev.get("type") == "tool_error":
            tool = ev.get("data", {}).get("tool", "unknown")
            profile["tool_errors"][tool] = profile["tool_errors"].get(tool, 0) + 1

    at = result.get("agent_tokens", {})
    profile["agent_tokens"] = {k: v for k, v in at.items() if not k.startswith("_") and v > 0}

    return profile


class _CaseTimeout(Exception):
    pass


def _run_single_case(case: dict, *, no_critique: bool = True,
                     timeout: int = DEFAULT_CASE_TIMEOUT,
                     on_progress: callable | None = None,
                     use_alarm: bool = True) -> CaseResult:
    """跑单个用例，返回结构化结果 + 瓶颈数据

    Args:
        no_critique: 关闭 Critique 评审（默认 True，benchmark 聚焦核心执行效率）
        timeout: 单用例超时秒数（默认 600s）
        on_progress: 可选回调，接收 {"event_type": str, "data": dict}，用于 Web 实时推送
        use_alarm: 是否使用 SIGALRM 超时（主线程可用；worker 线程中需传 False）
    """
    import shutil
    from autoc.app import build_orchestrator
    from autoc.config import load_config
    from autoc.testing.mock_plans import get_test_case

    name = case["name"]
    workspace = tempfile.mkdtemp(prefix=f"autoc-bench-{name}-")
    tc = get_test_case(name)
    requirement = tc["requirement"]

    # 预置 seed 文件（增量修改用例需要已有代码）
    for rel_path, content in case.get("seed_files", {}).items():
        full = os.path.join(workspace, rel_path)
        parent = os.path.dirname(full)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        with open(full, "w") as f:
            f.write(content)

    critique_label = " [dim](no critique)[/dim]" if no_critique else ""
    console.print(
        f"\n  [bold cyan]▸ {name}[/bold cyan] ({case['complexity']}) "
        f"— {case['description']}{critique_label} [dim](timeout {timeout}s)[/dim]"
    )

    cr = CaseResult(case_name=name, complexity=case["complexity"])
    on_event, events = _build_event_logger()

    if on_progress:
        _inner_on_event = on_event
        def on_event(event):
            _inner_on_event(event)
            etype = event.get("type", "")
            if etype in _PROGRESS_EVENTS:
                try:
                    on_progress({
                        "event_type": etype,
                        "data": _simplify_event_data(etype, event.get("data", {})),
                    })
                except Exception:
                    pass

    # SIGALRM 仅主线程可用；worker 线程中 use_alarm=False，超时由 future.result() 兜底
    _has_alarm = hasattr(signal, "SIGALRM") and use_alarm

    def _timeout_handler(signum, frame):
        raise _CaseTimeout(f"用例 {name} 超时（{timeout}s）")

    old_handler = None
    if _has_alarm:
        old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(timeout)

    orc = None
    try:
        config = load_config()
        orc = build_orchestrator(config=config, project_path=workspace, on_event=on_event)
        if no_critique:
            orc.critique = None

        start = time.time()
        r = orc.run(requirement, max_iterations=case["max_iterations"])
        cr.elapsed_seconds = round(time.time() - start, 1)

        cr.success = r.get("success", False)
        cr.tasks_completed = r.get("tasks_completed", 0)
        cr.tasks_total = r.get("tasks_total", 0)
        cr.tasks_verified = r.get("tasks_verified", 0)
        cr.total_tokens = r.get("total_tokens", 0)
        cr.prompt_tokens = r.get("prompt_tokens", 0)
        cr.completion_tokens = r.get("completion_tokens", 0)
        cr.cached_tokens = r.get("cached_tokens", 0)
        cr.dev_iterations = r.get("dev_iterations", 0)
        cr.call_count = r.get("call_count", 0)
        cr.error_calls = r.get("error_calls", 0)
        cr.exit_reason = r.get("exit_reason", "")
        cr.files_generated = len(r.get("files", []))

        profile = _extract_profile(events, r)
        cr.agent_tokens = profile["agent_tokens"]
        cr.stage_timings = profile["stage_timings"]
        cr.tool_calls = profile["tool_calls"]
        cr.tool_errors = profile["tool_errors"]
    except _CaseTimeout as e:
        cr.error = str(e)
        cr.exit_reason = "timeout"
        cr.elapsed_seconds = float(timeout)
        console.print(f"    [red bold]✗ 超时: {e}[/red bold]")
    except Exception as e:
        cr.error = str(e)
        console.print(f"    [red]✗ 异常: {e}[/red]")
    finally:
        if _has_alarm:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
        if cr.success:
            # 传入 sandbox（销毁前），L2/L3 验证可在容器内执行
            sandbox = getattr(orc, "sandbox", None) if orc else None
            cr.quality_checks, cr.quality_verified, cr.quality_level = _verify_output_quality(
                workspace, case, sandbox=sandbox
            )
        if not cr.success and events:
            _save_case_log(name, events, cr, orc=orc)
        if orc:
            try:
                orc.destroy_sandbox()
            except Exception:
                pass
        shutil.rmtree(workspace, ignore_errors=True)

    icon = "[green]✓[/green]" if cr.success else "[red]✗[/red]"
    qv = " [green]Q✓[/green]" if cr.quality_verified else (
        " [yellow]Q✗[/yellow]" if cr.success and cr.quality_checks else ""
    )
    console.print(
        f"    {icon} {cr.elapsed_seconds:.0f}s | "
        f"{cr.total_tokens:,} tokens | "
        f"{cr.dev_iterations} 迭代 | "
        f"任务 {cr.tasks_verified}/{cr.tasks_total}{qv}"
    )
    return cr


def _verify_output_quality(
    workspace: str, case: dict, sandbox=None
) -> tuple[list[dict], bool, str]:
    """分层产出质量验证（workspace 清理前、沙箱销毁前执行）

    验证分三层：
    - L1（决定 quality_verified）: 文件存在 + host_checks（只用标准库，宿主机安全）
    - L2（仅记录，不影响 quality_verified）: runtime_checks（需要第三方依赖，在容器内执行）
    - L3（决定 quality_verified）: l3_checks 端到端功能验证（在容器内启动服务 → CRUD 断言）

    Args:
        workspace: 宿主机工作区路径（bind-mount 到容器 /workspace）
        case: benchmark 用例定义
        sandbox: DockerSandbox 实例（若传入，L2/L3 在容器内执行，避免宿主机缺少依赖）

    Returns:
        (checks, quality_passed, quality_level)
        quality_level: L0(未过L1) | L1 | L2 | L3，反映验证深度
    """
    checks: list[dict] = []
    quality_passed = True  # L1 + L3 共同决定 quality_verified

    # L1: 文件存在性（宿主机检查，bind-mount 后文件直接可见）
    for f in case.get("expected_files", []):
        exists = os.path.exists(os.path.join(workspace, f))
        checks.append({"name": f"文件存在: {f}", "passed": exists, "level": "L1"})
        if not exists:
            quality_passed = False

    # L1: 宿主机安全检查（py_compile 等只依赖标准库的命令）
    for cmd in case.get("host_checks", []):
        passed, output = _run_check_cmd(cmd, workspace)
        checks.append({"name": f"语法: {cmd[:50]}", "passed": passed, "level": "L1",
                        "output": output if not passed else ""})
        if not passed:
            quality_passed = False

    # L2: 运行时检查（需要第三方依赖）
    # 优先在容器内执行（依赖已在容器中安装），fallback 到宿主机
    for cmd in case.get("runtime_checks", []):
        passed, output = _run_check_cmd_in_sandbox(cmd, workspace, sandbox, timeout=30)
        checks.append({"name": f"运行时: {cmd[:50]}", "passed": passed, "level": "L2",
                        "output": output if not passed else ""})

    # L3: 端到端功能验证（在容器内启动服务 → CRUD 断言）
    # 必须在容器内执行：第三方依赖（flask 等）只装在容器里
    for cmd in case.get("l3_checks", []):
        passed, output = _run_check_cmd_in_sandbox(cmd, workspace, sandbox, timeout=90)
        checks.append({"name": "L3 CRUD 端到端", "passed": passed, "level": "L3",
                        "output": output if not passed else ""})
        if not passed:
            quality_passed = False

    # 推导 quality_level（L0/L1/L2/L3）—— 取已通过的最高验证层级
    has_l1_fail = any(not c["passed"] for c in checks if c["level"] == "L1")
    has_l2_fail = any(not c["passed"] for c in checks if c["level"] == "L2")
    has_l3_fail = any(not c["passed"] for c in checks if c["level"] == "L3")
    has_l3 = any(c["level"] == "L3" for c in checks)
    if has_l1_fail:
        quality_level = "L0"
    elif has_l3 and not has_l2_fail and not has_l3_fail:
        quality_level = "L3"
    elif not has_l2_fail:
        quality_level = "L2"
    else:
        quality_level = "L1"

    if checks:
        l1_total = sum(1 for c in checks if c["level"] == "L1")
        l1_ok = sum(1 for c in checks if c["level"] == "L1" and c["passed"])
        l2_total = sum(1 for c in checks if c["level"] == "L2")
        l2_ok = sum(1 for c in checks if c["level"] == "L2" and c["passed"])
        l3_total = sum(1 for c in checks if c["level"] == "L3")
        l3_ok = sum(1 for c in checks if c["level"] == "L3" and c["passed"])
        style = "green" if quality_passed else "yellow"
        l2_info = f" | L2 {l2_ok}/{l2_total}" if l2_total > 0 else ""
        l3_info = f" | L3 {l3_ok}/{l3_total}" if l3_total > 0 else ""
        console.print(f"    [{style}]  质量验证: L1 {l1_ok}/{l1_total}{l2_info}{l3_info} → {quality_level}[/{style}]")

    return checks, quality_passed, quality_level


def _run_check_cmd(cmd: str, cwd: str, timeout: int = 30) -> tuple[bool, str]:
    """在宿主机执行验证命令（仅用于 L1 标准库检查）"""
    try:
        result = subprocess.run(
            cmd, shell=True, cwd=cwd, timeout=timeout,
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return True, ""
        return False, (result.stderr or result.stdout)[:200]
    except subprocess.TimeoutExpired:
        return False, f"超时({timeout}s)"
    except Exception as e:
        return False, str(e)[:200]


import logging as _logging
_bench_logger = _logging.getLogger("autoc.benchmark")


def _kill_leaked_procs_in_container(container_id: str) -> None:
    """清理容器内因超时泄漏的 Flask/python 子进程（P1-1/P1-2）

    pkill -f 使用 POSIX ERE：| 是交替符（不转义），实现两个模式的 OR。
    """
    try:
        subprocess.run(
            ["docker", "exec", container_id, "bash", "-c",
             # ERE 中 | 是交替符（不是 \|），两个模式覆盖：
             # 1. L3 启动 Flask 的 python -c 脚本
             # 2. 可能残留的 urllib/urlopen 验证脚本
             "pkill -f 'python -c.*import subprocess.*Flask|python -c.*urlopen' 2>/dev/null || true"],
            timeout=5,
            capture_output=True,
        )
    except Exception:
        pass


def _run_check_cmd_in_sandbox(
    cmd: str, workspace: str, sandbox, timeout: int = 90
) -> tuple[bool, str]:
    """优先在 Docker 容器内执行验证命令，fallback 到宿主机

    L2/L3 验证命令需要项目依赖（flask/requests 等），这些依赖只装在容器里。

    P1-1: 执行前先清理上次遗留的 Flask 进程
    P1-2: 超时后主动 pkill 容器内子进程，防止端口泄漏
    P1-3: fallback 时打印 warning，不再静默失败
    """
    if sandbox is not None:
        container_id = getattr(sandbox, "_container_id", None)
        if container_id:
            # P1-1: 执行前清理上次可能泄漏的进程
            _kill_leaked_procs_in_container(container_id)
            try:
                result = subprocess.run(
                    ["docker", "exec", "-w", "/workspace", container_id,
                     "bash", "-c", cmd],
                    capture_output=True, text=True, timeout=timeout,
                )
                if result.returncode == 0:
                    return True, ""
                return False, (result.stderr or result.stdout)[:400]
            except subprocess.TimeoutExpired:
                # P1-2: 超时后清理容器内残留进程
                _kill_leaked_procs_in_container(container_id)
                return False, f"超时({timeout}s)"
            except Exception as e:
                # P1-3: docker exec 失败时记录 warning 再 fallback
                _bench_logger.warning(
                    "docker exec 失败（container=%s），fallback 到宿主机: %s", container_id, e
                )

    # Fallback: 宿主机执行（L2 可能因缺少依赖失败，L3 几乎必然失败）
    # P1-3: 如果 sandbox 存在但走到这里，说明容器执行失败了
    if sandbox is not None:
        _bench_logger.warning(
            "L2/L3 验证在宿主机上执行，结果可能因缺少依赖而不准确"
        )
    return _run_check_cmd(cmd, workspace, timeout=timeout)


def _save_case_log(case_name: str, events: list[dict], cr: CaseResult,
                   orc=None):
    """失败用例：保存事件流日志 + 完整 Agent 对话供事后分析"""
    os.makedirs(LOG_DIR, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    path = os.path.join(LOG_DIR, f"{case_name}_{ts}.json")
    log_data = {
        "case_name": case_name,
        "timestamp": ts,
        "error": cr.error,
        "exit_reason": cr.exit_reason,
        "elapsed_seconds": cr.elapsed_seconds,
        "total_tokens": cr.total_tokens,
        "events_count": len(events),
        "events": [
            {k: v for k, v in ev.items() if k != "_ts"}
            for ev in events[-50:]
        ],
    }
    if orc:
        log_data["conversations"] = _extract_conversations(orc)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(log_data, f, ensure_ascii=False, indent=2, default=str)
        console.print(f"    [dim]日志已保存: {path}[/dim]")
    except Exception:
        pass


def _extract_conversations(orc) -> dict:
    """从 orchestrator 提取各 Agent 的对话历史（截断超长 tool result）"""
    result = {}
    agents = [
        ("planner", getattr(orc, "planner_agent", None)),
        ("coder", getattr(orc, "code_act_agent", None)),
        ("critique", getattr(orc, "critique", None)),
    ]
    for name, agent in agents:
        if agent is None:
            continue
        history = getattr(agent, "conversation_history", None)
        if not history:
            continue
        sanitized = []
        for msg in history:
            entry = {"role": msg.get("role", ""), "content": _truncate_for_log(msg)}
            if "tool_calls" in msg:
                entry["tool_calls"] = [
                    {"name": tc.get("function", {}).get("name", ""),
                     "arguments_preview": str(tc.get("function", {}).get("arguments", ""))[:300]}
                    for tc in msg["tool_calls"]
                ]
            if "tool_call_id" in msg:
                entry["tool_call_id"] = msg["tool_call_id"]
            sanitized.append(entry)
        result[name] = {"message_count": len(history), "messages": sanitized}
    return result


def _truncate_for_log(msg: dict, max_chars: int = 2000) -> str:
    """截断消息内容，防止日志过大"""
    content = str(msg.get("content", ""))
    if len(content) <= max_chars:
        return content
    half = max_chars // 2
    return content[:half] + f"\n\n... [{len(content) - max_chars} chars truncated] ...\n\n" + content[-half:]


def _run_repeated_case(case: dict, *, repeat: int,
                       no_critique: bool, timeout: int,
                       on_progress: callable | None = None,
                       use_alarm: bool = True) -> CaseResult:
    """多次运行同一用例，取中位数作为最终结果

    use_alarm: 是否使用 SIGALRM 超时；worker 线程中需传 False。
    """
    name = case["name"]
    console.print(f"\n  [bold cyan]↻ {name}[/bold cyan] × {repeat} 次运行")
    runs: list[CaseResult] = []
    for i in range(repeat):
        if _interrupted:
            break
        console.print(f"    [dim]第 {i + 1}/{repeat} 次[/dim]")
        if on_progress:
            try:
                on_progress({"event_type": "repeat_round",
                             "data": {"run_index": i + 1, "total_runs": repeat}})
            except Exception:
                pass
        cr = _run_single_case(case, no_critique=no_critique, timeout=timeout,
                              on_progress=on_progress, use_alarm=use_alarm)
        runs.append(cr)

    if not runs:
        return CaseResult(case_name=name, complexity=case["complexity"], error="所有重复运行被中断")

    success_runs = [r for r in runs if r.success]
    source = success_runs if success_runs else runs

    median_cr = CaseResult(
        case_name=name,
        complexity=case["complexity"],
        success=len(success_runs) > len(runs) / 2,
        repeat_count=len(runs),
    )

    numeric_fields = [
        "total_tokens", "prompt_tokens", "completion_tokens", "cached_tokens",
        "elapsed_seconds", "dev_iterations", "call_count", "error_calls",
        "files_generated", "tasks_completed", "tasks_total", "tasks_verified",
    ]
    for field_name in numeric_fields:
        vals = sorted(getattr(r, field_name) for r in source)
        mid = len(vals) // 2
        median_val = vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2
        if isinstance(getattr(source[0], field_name), int):
            median_val = int(round(median_val))
        else:
            median_val = round(median_val, 1)
        setattr(median_cr, field_name, median_val)

    # 瓶颈数据取中位耗时最接近的那次 run（而非固定第一次）
    representative = min(
        source, key=lambda r: abs(r.elapsed_seconds - median_cr.elapsed_seconds)
    )
    median_cr.exit_reason = representative.exit_reason
    median_cr.agent_tokens = representative.agent_tokens
    median_cr.stage_timings = representative.stage_timings
    median_cr.tool_calls = representative.tool_calls
    median_cr.tool_errors = representative.tool_errors
    median_cr.quality_verified = representative.quality_verified
    median_cr.quality_level = representative.quality_level
    median_cr.quality_checks = representative.quality_checks

    median_cr.repeat_runs = []
    for r in runs:
        median_cr.repeat_runs.append({
            "success": r.success,
            "elapsed_seconds": r.elapsed_seconds,
            "total_tokens": r.total_tokens,
            "dev_iterations": r.dev_iterations,
            "quality_verified": r.quality_verified,
            "error": r.error,
        })

    success_rate = len(success_runs) / len(runs) * 100
    elapsed_vals = [r.elapsed_seconds for r in source]
    console.print(
        f"    [bold]汇总[/bold]: 成功率 {success_rate:.0f}% | "
        f"耗时 {min(elapsed_vals):.0f}s ~ {max(elapsed_vals):.0f}s (中位 {median_cr.elapsed_seconds:.0f}s)"
    )
    return median_cr


# Ctrl+C 优雅中断：保存已完成的用例
_interrupted = False
_interrupted_lock = _threading.Lock()


def _setup_interrupt_handler():
    global _interrupted

    def _handler(signum, frame):
        global _interrupted
        with _interrupted_lock:
            if _interrupted:
                console.print("\n[red bold]再次中断，强制退出[/red bold]")
                sys.exit(1)
            _interrupted = True
        console.print("\n[yellow bold]⚠ 收到中断信号，当前用例完成后保存已有结果...[/yellow bold]")

    signal.signal(signal.SIGINT, _handler)


def _run_case_worker(
    idx: int, case: dict, *,
    no_critique: bool, timeout: int,
    writer: "BenchmarkLiveWriter", tag: str, total: int,
    repeat: int, completed_counter: list,
) -> tuple[int, CaseResult]:
    """并行模式的 worker 函数，在线程池中执行单个用例"""
    if _interrupted:
        cr = CaseResult(case_name=case["name"], complexity=case["complexity"],
                        error="用户中断", exit_reason="interrupted")
        return idx, cr

    writer.push({"type": "case_start", "tag": tag,
                 "case": case["name"], "index": idx, "total": total})

    def on_progress(info):
        writer.push({"type": "case_event", "case": case["name"], **info})

    if repeat == 1:
        cr = _run_single_case(case, no_critique=no_critique, timeout=timeout,
                              on_progress=on_progress, use_alarm=False)
    else:
        cr = _run_repeated_case(case, repeat=repeat, no_critique=no_critique,
                                timeout=timeout, on_progress=on_progress,
                                use_alarm=False)

    with _interrupted_lock:
        completed_counter[0] += 1
        done = completed_counter[0]

    writer.push({"type": "case_done", "tag": tag, "case": case["name"],
                 "success": cr.success, "tokens": cr.total_tokens,
                 "elapsed": cr.elapsed_seconds,
                 "index": idx, "completed": done, "total": total})
    return idx, cr


def _run_cases_parallel(
    selected: list[dict], *,
    run: "BenchmarkRun",
    writer: "BenchmarkLiveWriter",
    tag: str,
    no_critique: bool,
    timeout: int,
    repeat: int,
    workers: int,
    stop_event: "threading.Event | None" = None,
) -> None:
    """并行执行多用例，结果按原始顺序写入 run.cases。

    并行模式注意事项：
    - SIGALRM 在 worker 线程中不可用，改用 future.result(timeout) 作为超时兜底
    - 各 worker 使用独立的 tempdir 和 Docker 容器，互不干扰
    - Console 输出可能交叉，但每条消息原子完整
    - stop_event 由 Web API 注入，用于支持 /stop 接口中断并行运行
    """
    total = len(selected)
    completed_counter = [0]  # mutable container 供 worker 原子更新
    results: dict[int, CaseResult] = {}

    future_to_idx: dict[concurrent.futures.Future, int] = {}

    console.print(f"\n[bold cyan]⚡ 并行模式：{workers} workers，共 {total} 个用例[/bold cyan]")

    # 全局超时：所有用例的最大墙钟时间（含 30s 余量），防止单用例卡死导致永久阻塞
    total_timeout = timeout * (repeat if repeat > 1 else 1) * total + 30

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        for idx, case in enumerate(selected):
            if _interrupted or (stop_event is not None and stop_event.is_set()):
                writer.push({"type": "run_interrupted", "tag": tag,
                             "message": "用户手动停止", "completed": idx})
                break
            future = executor.submit(
                _run_case_worker,
                idx, case,
                no_critique=no_critique,
                timeout=timeout,
                writer=writer,
                tag=tag,
                total=total,
                repeat=repeat,
                completed_counter=completed_counter,
            )
            future_to_idx[future] = idx

        try:
            for future in concurrent.futures.as_completed(future_to_idx, timeout=total_timeout):
                idx = future_to_idx[future]
                case_name = selected[idx]["name"]
                try:
                    result_idx, cr = future.result()
                    results[result_idx] = cr
                except Exception as e:
                    console.print(f"  [red]✗ {case_name} worker 异常: {e}[/red]")
                    cr = CaseResult(case_name=case_name, complexity=selected[idx]["complexity"],
                                    error=str(e), exit_reason="error")
                    results[idx] = cr
        except concurrent.futures.TimeoutError:
            console.print(f"  [red bold]⚠ 并行整体超时（>{total_timeout}s），放弃未完成用例[/red bold]")
            for future, idx in future_to_idx.items():
                if idx not in results:
                    case_name = selected[idx]["name"]
                    results[idx] = CaseResult(
                        case_name=case_name, complexity=selected[idx]["complexity"],
                        error=f"并行超时（>{total_timeout}s）", exit_reason="timeout",
                        elapsed_seconds=float(total_timeout))
            executor.shutdown(wait=False, cancel_futures=True)

    # 按原始用例顺序写入 run.cases
    for idx in sorted(results):
        run.cases.append(results[idx])


def run_benchmark(tag: str, cases: list[str] | None = None,
                  description: str = "", *,
                  no_critique: bool = True,
                  timeout: int = DEFAULT_CASE_TIMEOUT,
                  force: bool = False,
                  repeat: int = 1,
                  live_mode: bool = False,
                  workers: int = 1) -> BenchmarkRun:
    """执行完整 benchmark

    Args:
        no_critique: 关闭 Critique 评审（默认 True）。
        timeout: 单用例超时秒数。
        force: 允许覆盖已有同名 tag。
        repeat: 每个用例重复运行次数（>1 时取中位数，解决 LLM 随机性）。
        live_mode: 是否有 SSE 客户端订阅。True 时 finish() 延迟 2s 等 SSE 读取；
                   CLI 调用时保持默认 False，Web 线程调用时传 True。
        workers: 并行 worker 数量（默认 1 = 串行）。>1 时启用多线程并行执行多用例。
                 注意：并行模式下 SIGALRM 超时降级为 future.result(timeout) 兜底。
    """
    # tag 覆盖保护
    existing = os.path.join(RESULTS_DIR, f"{tag}.json")
    if os.path.exists(existing) and not force:
        console.print(f"[red]标签 '{tag}' 已存在！使用 --force 覆盖，或换一个标签。[/red]")
        console.print(f"[dim]已有标签: {', '.join(_list_tags())}[/dim]")
        sys.exit(1)

    repeat = max(1, repeat)

    global _interrupted
    _interrupted = False

    git_commit, git_dirty = _get_git_info()
    env_info = _collect_environment()

    if cases:
        selected = [c for c in BENCHMARK_CASES if c["name"] in cases]
        if not selected:
            console.print(f"[red]未找到用例: {cases}[/red]")
            sys.exit(1)
    else:
        selected = [c for c in BENCHMARK_CASES if c["name"] in CORE_CASES]

    workers = max(1, workers)
    critique_status = "[red]OFF[/red]" if no_critique else "[green]ON[/green]"
    repeat_info = f"  |  重复: {repeat}x" if repeat > 1 else ""
    parallel_info = f"  |  并行: {workers}×" if workers > 1 else ""
    console.print(Panel(
        f"[bold]AutoC Benchmark[/bold]\n"
        f"标签: {tag}  |  用例: {len(selected)}{repeat_info}{parallel_info}  |  "
        f"Git: {git_commit}{'*' if git_dirty else ''}  |  "
        f"Critique: {critique_status}  |  "
        f"超时: {timeout}s/用例\n"
        f"模型: {env_info.get('model', '?')}  |  "
        f"Python: {env_info.get('python_version', '?')}",
        style="cyan", width=70,
    ))

    _setup_interrupt_handler()

    run = BenchmarkRun(
        tag=tag,
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
        git_commit=git_commit,
        git_dirty=git_dirty,
        description=description,
        critique_enabled=not no_critique,
        environment=env_info,
    )

    writer = BenchmarkLiveWriter(tag)
    writer.start(total_cases=len(selected), cases=[c["name"] for c in selected],
                 description=description)
    writer.push({"type": "run_start", "tag": tag,
                 "total_cases": len(selected), "cases": [c["name"] for c in selected]})

    total_start = time.time()
    _early_return = False
    try:
        if workers > 1:
            _run_cases_parallel(
                selected, run=run, writer=writer, tag=tag,
                no_critique=no_critique, timeout=timeout, repeat=repeat,
                workers=workers,
            )
        else:
            for i, case in enumerate(selected):
                if _interrupted:
                    console.print(f"[yellow]跳过剩余用例（已中断）[/yellow]")
                    break

                writer.push({"type": "case_start", "tag": tag,
                             "case": case["name"], "index": i, "total": len(selected)})

                def _make_progress_cb(case_name):
                    def cb(info):
                        writer.push({"type": "case_event", "case": case_name, **info})
                    return cb

                if repeat == 1:
                    cr = _run_single_case(case, no_critique=no_critique, timeout=timeout,
                                          on_progress=_make_progress_cb(case["name"]))
                else:
                    cr = _run_repeated_case(
                        case, repeat=repeat, no_critique=no_critique, timeout=timeout,
                        on_progress=_make_progress_cb(case["name"]),
                    )
                run.cases.append(cr)

                writer.push({"type": "case_done", "tag": tag, "case": case["name"],
                             "success": cr.success, "tokens": cr.total_tokens,
                             "elapsed": cr.elapsed_seconds,
                             "index": i, "completed": len(run.cases), "total": len(selected)})
    finally:
        run.total_elapsed = round(time.time() - total_start, 1)

        if _interrupted and not run.cases:
            console.print("[red]没有完成任何用例，不保存结果。[/red]")
            writer.push({"type": "run_error", "tag": tag,
                         "error": "用户中断，无用例完成"})
            _early_return = True

        if not _early_return:
            _print_summary(run)
            _print_bottleneck_analysis(run)
            _print_anomaly_warnings(run)
            _save_result(run)

            writer.push({"type": "run_complete", "tag": tag, "success": True,
                         "interrupted": _interrupted,  # 中断但有部分完成用例时标记
                         "completion_rate": run.completion_rate,
                         "total_elapsed": run.total_elapsed,
                         "case_count": len(run.cases)})

        writer.finish(delay=2.0 if live_mode else 0)

    return run


# ──────────────────────────── 异常值检测 ────────────────────────────


def _print_anomaly_warnings(run: BenchmarkRun):
    """检测并标红异常值"""
    warnings: list[str] = []

    for c in run.cases:
        if c.success and c.dev_iterations == 0:
            warnings.append(f"🔴 {c.case_name}: dev_iterations=0（成功但无迭代记录，数据采集可能异常）")
        if c.success and not c.exit_reason:
            warnings.append(f"🔴 {c.case_name}: exit_reason 为空（缺少退出原因）")
        if c.success and c.tasks_total == 0:
            warnings.append(f"🔴 {c.case_name}: tasks_total=0（任务数据缺失）")
        if c.pc_ratio > 30:
            warnings.append(f"🟡 {c.case_name}: P:C 比值 {c.pc_ratio:.0f}:1（system prompt 可能过重）")
        if c.success and c.total_tokens == 0:
            warnings.append(f"🔴 {c.case_name}: Token=0（数据未采集）")
        if c.exit_reason == "timeout":
            warnings.append(f"🔴 {c.case_name}: 超时退出（{c.elapsed_seconds:.0f}s）")

    # 单 Agent Token 占比 > 95%
    agent_totals: dict[str, int] = {}
    for c in run.cases:
        for agent, tok in c.agent_tokens.items():
            agent_totals[agent] = agent_totals.get(agent, 0) + tok
    if agent_totals:
        total_tok = sum(agent_totals.values())
        for agent, tok in agent_totals.items():
            if total_tok > 0 and tok / total_tok > 0.95:
                warnings.append(f"🟡 {agent} 消耗 {tok/total_tok:.0%} Token（其余 Agent 几乎无消耗，检查 LLM 实例是否共享）")

    # simple 比 complex 慢的横向对比异常
    case_map = {c.case_name: c for c in run.cases if c.success}
    for ca in run.cases:
        for cb in run.cases:
            if (ca.success and cb.success
                    and ca.complexity == "simple" and cb.complexity == "complex"
                    and ca.elapsed_seconds > cb.elapsed_seconds * 1.5):
                warnings.append(
                    f"🟡 {ca.case_name}(simple, {ca.elapsed_seconds:.0f}s) 比 "
                    f"{cb.case_name}(complex, {cb.elapsed_seconds:.0f}s) 慢，复杂度与耗时倒挂"
                )

    if warnings:
        console.print(f"\n[bold red]⚠ 异常值检测[/bold red]")
        for w in warnings:
            console.print(f"    {w}")
    else:
        console.print(f"\n[green]✓ 未检测到异常值[/green]")

    return warnings


def _generate_anomaly_section(data: dict) -> list[str]:
    """为 Markdown 报告生成异常值段落"""
    warnings: list[str] = []
    cases = data.get("cases", [])

    for c in cases:
        if c.get("success") and c.get("dev_iterations", 0) == 0:
            warnings.append(f"- **{c['case_name']}**: `dev_iterations=0`（成功但无迭代记录）")
        if c.get("success") and not c.get("exit_reason"):
            warnings.append(f"- **{c['case_name']}**: `exit_reason` 为空")
        if c.get("success") and c.get("tasks_total", 0) == 0:
            warnings.append(f"- **{c['case_name']}**: `tasks_total=0`（任务数据缺失）")
        comp = c.get("completion_tokens", 0)
        prompt = c.get("prompt_tokens", 0)
        if comp > 0 and prompt / comp > 30:
            warnings.append(f"- **{c['case_name']}**: P:C 比值 {prompt/comp:.0f}:1（system prompt 可能过重）")
        if c.get("exit_reason") == "timeout":
            warnings.append(f"- **{c['case_name']}**: 超时退出（{c.get('elapsed_seconds', 0):.0f}s）")
        if c.get("success") and not c.get("quality_verified") and c.get("quality_checks"):
            failed_checks = [ch["name"] for ch in c.get("quality_checks", []) if not ch.get("passed")]
            warnings.append(
                f"- **{c['case_name']}**: 执行成功但质量验证未通过（{', '.join(failed_checks[:3])}）"
            )

    agent_totals: dict[str, int] = {}
    for c in cases:
        for agent, tok in c.get("agent_tokens", {}).items():
            agent_totals[agent] = agent_totals.get(agent, 0) + tok
    if agent_totals:
        total_tok = sum(agent_totals.values())
        for agent, tok in agent_totals.items():
            if total_tok > 0 and tok / total_tok > 0.95:
                warnings.append(f"- **{agent}** 消耗 {tok/total_tok:.0%} Token（其余 Agent 几乎无消耗）")

    return warnings


# ──────────────────────────── 瓶颈分析 ────────────────────────────


def _print_bottleneck_analysis(run: BenchmarkRun):
    """打印瓶颈分析：时间花在哪？Token 花在哪？工具调用分布？"""
    console.print(f"\n[bold]🔍 瓶颈分析[/bold]")

    # 1. 阶段耗时分布（跨用例聚合）
    stage_totals: dict[str, float] = {}
    for c in run.cases:
        for stage, dur in c.stage_timings.items():
            stage_totals[stage] = stage_totals.get(stage, 0) + dur

    if stage_totals:
        total_time = sum(stage_totals.values())
        console.print(f"\n  [bold]⏱ 时间分布[/bold]（各阶段占比）")
        st = Table(show_header=True, header_style="bold", width=50, padding=(0, 1))
        st.add_column("阶段", width=16)
        st.add_column("耗时", width=10, justify="right")
        st.add_column("占比", width=10, justify="right")
        st.add_column("", width=10)
        for stage, dur in sorted(stage_totals.items(), key=lambda x: -x[1]):
            pct = dur / total_time * 100 if total_time > 0 else 0
            bar_len = int(pct / 5)
            bar = "█" * bar_len
            style = "red" if pct > 50 else ("yellow" if pct > 30 else "green")
            st.add_row(stage, f"{dur:.0f}s", f"[{style}]{pct:.0f}%[/{style}]", f"[{style}]{bar}[/{style}]")
        console.print(st)

    # 2. Token 按 Agent 分布
    agent_totals: dict[str, int] = {}
    for c in run.cases:
        for agent, tokens in c.agent_tokens.items():
            agent_totals[agent] = agent_totals.get(agent, 0) + tokens

    if agent_totals:
        total_tok = sum(agent_totals.values())
        console.print(f"\n  [bold]💰 Token 分布[/bold]（按 Agent）")
        at = Table(show_header=True, header_style="bold", width=50, padding=(0, 1))
        at.add_column("Agent", width=16)
        at.add_column("Token", width=12, justify="right")
        at.add_column("占比", width=10, justify="right")
        at.add_column("", width=10)
        for agent, tok in sorted(agent_totals.items(), key=lambda x: -x[1]):
            pct = tok / total_tok * 100 if total_tok > 0 else 0
            bar_len = int(pct / 5)
            bar = "█" * bar_len
            style = "red" if pct > 50 else ("yellow" if pct > 30 else "dim")
            at.add_row(agent, f"{tok:,}", f"[{style}]{pct:.0f}%[/{style}]", f"[{style}]{bar}[/{style}]")
        console.print(at)

    # 3. Token 效率指标
    console.print(f"\n  [bold]📊 Token 效率[/bold]")
    eff = Table(show_header=True, header_style="bold", width=72, padding=(0, 1))
    eff.add_column("用例", width=14)
    eff.add_column("P:C（含缓存）", width=12, justify="right")
    eff.add_column("非缓存 P:C", width=10, justify="right")
    eff.add_column("缓存命中", width=10, justify="right")
    eff.add_column("API 调用", width=10, justify="right")
    eff.add_column("Token/调用", width=10, justify="right")
    for c in run.cases:
        pc = f"{c.pc_ratio:.0f}:1" if c.completion_tokens > 0 else "N/A"
        nc_pc = f"{c.nc_pc_ratio:.1f}:1" if c.completion_tokens > 0 else "N/A"
        cache = f"{c.cache_hit_rate:.0%}" if c.prompt_tokens > 0 else "N/A"
        tpc = f"{c.total_tokens // c.call_count:,}" if c.call_count > 0 else "N/A"
        pc_style = "red" if c.pc_ratio > 30 else ("yellow" if c.pc_ratio > 20 else "")
        nc_pc_style = "yellow" if c.nc_pc_ratio > 10 else ("green" if c.nc_pc_ratio < 6 else "")
        cache_style = "green" if c.cache_hit_rate > 0.5 else ""
        eff.add_row(
            c.case_name,
            f"[{pc_style}]{pc}[/{pc_style}]" if pc_style else pc,
            f"[{nc_pc_style}]{nc_pc}[/{nc_pc_style}]" if nc_pc_style else nc_pc,
            f"[{cache_style}]{cache}[/{cache_style}]" if cache_style else cache,
            str(c.call_count),
            tpc,
        )
    console.print(eff)

    # 4. 工具调用频次 TOP 10
    tool_totals: dict[str, int] = {}
    error_totals: dict[str, int] = {}
    for c in run.cases:
        for tool, cnt in c.tool_calls.items():
            tool_totals[tool] = tool_totals.get(tool, 0) + cnt
        for tool, cnt in c.tool_errors.items():
            error_totals[tool] = error_totals.get(tool, 0) + cnt

    if tool_totals:
        console.print(f"\n  [bold]🔧 工具调用 TOP 10[/bold]")
        tt = Table(show_header=True, header_style="bold", width=50, padding=(0, 1))
        tt.add_column("工具", width=22)
        tt.add_column("调用", width=8, justify="right")
        tt.add_column("错误", width=8, justify="right")
        tt.add_column("错误率", width=8, justify="right")
        for tool, cnt in sorted(tool_totals.items(), key=lambda x: -x[1])[:10]:
            errs = error_totals.get(tool, 0)
            err_rate = errs / cnt * 100 if cnt > 0 else 0
            err_style = "red" if err_rate > 20 else ("yellow" if err_rate > 5 else "green")
            tt.add_row(
                tool, str(cnt),
                f"[red]{errs}[/red]" if errs > 0 else "[dim]0[/dim]",
                f"[{err_style}]{err_rate:.0f}%[/{err_style}]",
            )
        console.print(tt)

    # 5. 一句话瓶颈诊断
    console.print(f"\n  [bold]📋 瓶颈诊断[/bold]")
    bottlenecks = []
    if stage_totals:
        worst_stage = max(stage_totals, key=stage_totals.get)
        worst_pct = stage_totals[worst_stage] / sum(stage_totals.values()) * 100
        if worst_pct > 60:
            bottlenecks.append(f"⚠️  {worst_stage} 阶段占总时间 {worst_pct:.0f}%，是最大时间瓶颈")
    if agent_totals:
        worst_agent = max(agent_totals, key=agent_totals.get)
        worst_pct = agent_totals[worst_agent] / sum(agent_totals.values()) * 100
        if worst_pct > 60:
            bottlenecks.append(f"⚠️  {worst_agent} 消耗 {worst_pct:.0f}% Token，是最大 Token 瓶颈")
    if error_totals:
        total_errors = sum(error_totals.values())
        total_calls = sum(tool_totals.values())
        if total_errors > 0:
            worst_err_tool = max(error_totals, key=error_totals.get)
            bottlenecks.append(f"⚠️  {worst_err_tool} 错误最多（{error_totals[worst_err_tool]} 次），总错误率 {total_errors/total_calls*100:.0f}%")
    if tool_totals.get("read_file", 0) > tool_totals.get("write_file", 0) * 3:
        bottlenecks.append(f"⚠️  read_file ({tool_totals['read_file']}次) 远多于 write_file ({tool_totals.get('write_file', 0)}次)，Agent 可能在反复探索")
    avg_pc = run.avg_pc_ratio
    if avg_pc > 25:
        bottlenecks.append(f"⚠️  平均 P:C 比值 {avg_pc:.0f}:1，system prompt / 工具 schema 占比过重")

    if bottlenecks:
        for b in bottlenecks:
            console.print(f"    {b}")
    else:
        console.print(f"    [green]✓ 未发现明显瓶颈[/green]")


# ──────────────────────────── 结果持久化 ────────────────────────────


def _save_result(run: BenchmarkRun):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, f"{run.tag}.json")
    data = {
        "schema_version": SCHEMA_VERSION,
        "tag": run.tag,
        "timestamp": run.timestamp,
        "git_commit": run.git_commit,
        "git_dirty": run.git_dirty,
        "description": run.description,
        "critique_enabled": run.critique_enabled,
        "environment": run.environment,
        "total_elapsed": run.total_elapsed,
        "aggregates": {
            "completion_rate": run.completion_rate,
            "avg_tokens": run.avg_tokens,
            "avg_elapsed": run.avg_elapsed,
            "avg_iterations": run.avg_iterations,
            "total_tokens": run.total_tokens,
            "total_cost_usd": run.total_cost_usd,
            "avg_pc_ratio": run.avg_pc_ratio,
            "avg_nc_pc_ratio": run.avg_nc_pc_ratio,
            "avg_cache_hit_rate": run.avg_cache_hit_rate,
            "avg_call_count": run.avg_call_count,
        },
        "cases": [asdict(c) for c in run.cases],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    console.print(f"\n[dim]结果已保存: {path}[/dim]")

    _generate_run_report(run, data)


def _generate_run_report(run: BenchmarkRun, data: dict):
    """每次 run 自动生成标准 Markdown 报告"""
    os.makedirs(REPORT_DIR, exist_ok=True)
    path = os.path.join(REPORT_DIR, f"{run.tag}.md")
    agg = data["aggregates"]
    env = data.get("environment", {})

    critique_label = "ON" if run.critique_enabled else "OFF"
    lines = [
        f"# Benchmark 报告: {run.tag}",
        "",
        f"> 时间: {run.timestamp}",
        f"> Git: `{run.git_commit}`{'（有未提交改动）' if run.git_dirty else ''}",
        f"> 描述: {run.description or '—'}",
        f"> Critique: {critique_label}",
        f"> 总耗时: {run.total_elapsed:.0f}s",
        "",
    ]

    # 环境信息
    if env:
        lines.extend([
            "### 运行环境",
            "",
            f"| 项目 | 值 |",
            f"|------|:---|",
            f"| 模型 | {env.get('model', '?')} |",
            f"| Provider | {env.get('provider', '?')} |",
            f"| Python | {env.get('python_version', '?')} |",
            f"| OS | {env.get('os', '?')} |",
            f"| Docker | {env.get('docker', '?')} |",
            "",
        ])

    lines.extend([
        "## 汇总",
        "",
        "| 指标 | 值 |",
        "|------|:--:|",
        f"| 完成率 | {agg['completion_rate']:.0%} |",
        f"| 平均 Token（成功用例） | {agg['avg_tokens']:,.0f} |",
        f"| 平均耗时（成功用例） | {agg['avg_elapsed']:.0f}s |",
        f"| 平均迭代（成功用例） | {agg['avg_iterations']:.1f} |",
        f"| 平均 P:C 比值（含缓存） | {agg.get('avg_pc_ratio', 0):.0f}:1 |",
        f"| 平均非缓存 P:C 比值 | {agg.get('avg_nc_pc_ratio', 0):.1f}:1 |",
        f"| 平均缓存命中率 | {agg.get('avg_cache_hit_rate', 0):.0%} |",
        f"| 平均 API 调用次数 | {agg.get('avg_call_count', 0):.0f} |",
        f"| 总 Token | {agg['total_tokens']:,} |",
        f"| 预估费用 | ${agg['total_cost_usd']:.4f} |",
        "",
        "## 逐用例结果",
        "",
        "| 用例 | 复杂度 | 结果 | 质量 | Token | Planner | Coder | 耗时 | 迭代 | 任务 | P:C | 缓存 | API | 退出原因 |",
        "|------|:------:|:----:|:----:|------:|--------:|------:|-----:|-----:|:----:|----:|-----:|----:|---------|",
    ])
    for c in data["cases"]:
        icon = "✅" if c["success"] else "❌"
        if c.get("quality_checks"):
            ql = c.get("quality_level", "L0")
            qv = f"{'✅' if c.get('quality_verified') else '⚠️'} {ql}"
        else:
            qv = "—"
        comp = c.get("completion_tokens", 0)
        prompt = c.get("prompt_tokens", 0)
        cached = c.get("cached_tokens", 0)
        pc = f"{prompt/comp:.0f}:1" if comp > 0 else "—"
        cache_rate = f"{cached/prompt:.0%}" if prompt > 0 else "—"
        at = c.get("agent_tokens", {})
        # planner+coder 合并键表示"无法拆分"，两列都显示 — 而非错误地将全量归入 Planner（缺陷 #2）
        if "planner+coder" in at:
            planner_str = coder_str = f"—({at['planner+coder']:,})"
        else:
            planner_tok = at.get("planner")
            coder_tok = at.get("coder")
            # 用 is not None 区分"值为 0"和"数据不存在"（缺陷 #5）
            planner_str = f"{planner_tok:,}" if planner_tok is not None else "—"
            coder_str = f"{coder_tok:,}" if coder_tok is not None else "—"
        lines.append(
            f"| {c['case_name']} | {c['complexity']} | {icon} | {qv} | "
            f"{c['total_tokens']:,} | {planner_str} | {coder_str} | {c['elapsed_seconds']:.0f}s | "
            f"{c['dev_iterations']} | {c['tasks_verified']}/{c['tasks_total']} | "
            f"{pc} | {cache_rate} | {c.get('call_count', 0)} | "
            f"{c['exit_reason'] or '—'} |"
        )

    # 瓶颈分析
    lines.extend(["", "## 瓶颈分析", ""])

    # 阶段耗时
    stage_totals: dict[str, float] = {}
    for c in data["cases"]:
        for stage, dur in c.get("stage_timings", {}).items():
            stage_totals[stage] = stage_totals.get(stage, 0) + dur
    if stage_totals:
        total_time = sum(stage_totals.values())
        lines.extend(["### 时间分布", "", "| 阶段 | 耗时 | 占比 |", "|------|-----:|-----:|"])
        for stage, dur in sorted(stage_totals.items(), key=lambda x: -x[1]):
            pct = dur / total_time * 100 if total_time > 0 else 0
            lines.append(f"| {stage} | {dur:.0f}s | {pct:.0f}% |")

    # Token 分布
    agent_totals: dict[str, int] = {}
    for c in data["cases"]:
        for agent, tok in c.get("agent_tokens", {}).items():
            agent_totals[agent] = agent_totals.get(agent, 0) + tok
    if agent_totals:
        total_tok = sum(agent_totals.values())
        lines.extend(["", "### Token 分布（按 Agent）", "", "| Agent | Token | 占比 |", "|-------|------:|-----:|"])
        for agent, tok in sorted(agent_totals.items(), key=lambda x: -x[1]):
            pct = tok / total_tok * 100 if total_tok > 0 else 0
            lines.append(f"| {agent} | {tok:,} | {pct:.0f}% |")

    # Token 效率
    lines.extend([
        "", "### Token 效率",
        "", "| 用例 | P:C（含缓存） | 非缓存 P:C | 缓存命中 | API 调用 | Token/调用 |",
        "|------|------------:|----------:|--------:|--------:|---------:|",
    ])
    for c in data["cases"]:
        comp = c.get("completion_tokens", 0)
        prompt = c.get("prompt_tokens", 0)
        cached = c.get("cached_tokens", 0)
        calls = c.get("call_count", 0)
        total = c.get("total_tokens", 0)
        pc = f"{prompt/comp:.0f}:1" if comp > 0 else "—"
        nc_pc = f"{max(0, prompt - cached)/comp:.1f}:1" if comp > 0 else "—"
        cache_rate = f"{cached/prompt:.0%}" if prompt > 0 else "—"
        tpc = f"{total//calls:,}" if calls > 0 else "—"
        lines.append(f"| {c['case_name']} | {pc} | {nc_pc} | {cache_rate} | {calls} | {tpc} |")

    # 工具调用
    tool_totals: dict[str, int] = {}
    error_totals: dict[str, int] = {}
    for c in data["cases"]:
        for tool, cnt in c.get("tool_calls", {}).items():
            tool_totals[tool] = tool_totals.get(tool, 0) + cnt
        for tool, cnt in c.get("tool_errors", {}).items():
            error_totals[tool] = error_totals.get(tool, 0) + cnt
    if tool_totals:
        lines.extend(["", "### 工具调用", "", "| 工具 | 调用 | 错误 | 错误率 |", "|------|-----:|-----:|-------:|"])
        for tool, cnt in sorted(tool_totals.items(), key=lambda x: -x[1])[:10]:
            errs = error_totals.get(tool, 0)
            err_rate = errs / cnt * 100 if cnt > 0 else 0
            lines.append(f"| {tool} | {cnt} | {errs} | {err_rate:.0f}% |")

    # 产出质量验证
    has_qv = any(c.get("quality_checks") for c in data["cases"])
    if has_qv:
        lines.extend(["", "## 产出质量验证", ""])
        for c in data["cases"]:
            checks = c.get("quality_checks", [])
            if not checks:
                continue
            passed = sum(1 for ch in checks if ch.get("passed"))
            total_checks = len(checks)
            ql = c.get("quality_level", "L0")
            icon = "✅" if c.get("quality_verified") else "⚠️"
            lines.append(f"### {c['case_name']} {icon} {ql} ({passed}/{total_checks})")
            lines.append("")
            for ch in checks:
                ch_icon = "✅" if ch.get("passed") else "❌"
                lines.append(f"- {ch_icon} {ch['name']}")
                if not ch.get("passed") and ch.get("output"):
                    lines.append(f"  > {ch['output'][:100]}")
            lines.append("")

    # 多次运行统计
    has_repeat = any(c.get("repeat_count", 1) > 1 for c in data["cases"])
    if has_repeat:
        lines.extend(["", "## 多次运行统计", ""])
        for c in data["cases"]:
            repeat_runs = c.get("repeat_runs", [])
            if len(repeat_runs) <= 1:
                continue
            success_count = sum(1 for r in repeat_runs if r.get("success"))
            elapsed_vals = [r["elapsed_seconds"] for r in repeat_runs]
            token_vals = [r["total_tokens"] for r in repeat_runs]
            lines.extend([
                f"### {c['case_name']} ({c.get('repeat_count', 1)}x)",
                "",
                f"- 成功率: {success_count}/{len(repeat_runs)}",
                f"- 耗时: {min(elapsed_vals):.0f}s / {c.get('elapsed_seconds', 0):.0f}s(中位) / {max(elapsed_vals):.0f}s",
                f"- Token: {min(token_vals):,} / {c.get('total_tokens', 0):,}(中位) / {max(token_vals):,}",
                "",
            ])

    # 异常值检测
    anomalies = _generate_anomaly_section(data)
    if anomalies:
        lines.extend(["", "## ⚠ 异常值检测", ""])
        lines.extend(anomalies)

    # 自动对比上一次（只比共同成功用例）
    prev_tag = _find_previous_tag(run.tag)
    if prev_tag:
        prev = _load_result_silent(prev_tag)
        if prev:
            _append_comparison_section(lines, run, data, prev_tag, prev)

    lines.extend(["", f"---", f"*自动生成于 {time.strftime('%Y-%m-%d %H:%M')}*", ""])

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    console.print(f"[dim]报告已生成: {path}[/dim]")


def _append_comparison_section(lines: list[str], run: BenchmarkRun,
                               data: dict, prev_tag: str, prev: dict):
    """只对比两次都成功的共同用例，避免统计谬误"""
    pa = prev["aggregates"]
    agg = data["aggregates"]

    prev_cases = {c["case_name"]: c for c in prev["cases"]}
    curr_cases = {c["case_name"]: c for c in data["cases"]}
    common_success = [
        name for name in prev_cases
        if name in curr_cases
        and prev_cases[name].get("success")
        and curr_cases[name].get("success")
    ]

    lines.extend([
        "", "## 与上次对比",
        "",
        f"> 对比基线: {prev_tag} ({prev['timestamp'][:10]}, git `{prev['git_commit']}`)",
    ])

    if common_success:
        lines.append(f"> 共同成功用例: {', '.join(common_success)}（仅对比这些用例的平均值）")
    lines.append("")

    def _delta(old, new, lower_better=True):
        if old == 0:
            return "—"
        pct = (new - old) / old * 100
        arrow = "↓" if pct < 0 else "↑"
        better = (pct < 0) if lower_better else (pct > 0)
        marker = "✅" if better else "⚠️"
        return f"{pct:+.0f}% {arrow} {marker}"

    # 总体对比（完成率用全量）
    lines.extend([
        "| 指标 | 上次 | 本次 | 变化 |",
        "|------|-----:|-----:|------|",
        f"| 完成率 | {pa['completion_rate']:.0%} | {agg['completion_rate']:.0%} | {_delta(pa['completion_rate'], agg['completion_rate'], False)} |",
    ])

    # 对比用共同成功用例的平均值
    if common_success:
        prev_common = [prev_cases[n] for n in common_success]
        curr_common = [curr_cases[n] for n in common_success]

        avg_tok_prev = sum(c["total_tokens"] for c in prev_common) / len(prev_common)
        avg_tok_curr = sum(c["total_tokens"] for c in curr_common) / len(curr_common)
        avg_time_prev = sum(c["elapsed_seconds"] for c in prev_common) / len(prev_common)
        avg_time_curr = sum(c["elapsed_seconds"] for c in curr_common) / len(curr_common)

        lines.append(f"| 平均 Token（共同用例） | {avg_tok_prev:,.0f} | {avg_tok_curr:,.0f} | {_delta(avg_tok_prev, avg_tok_curr)} |")
        lines.append(f"| 平均耗时（共同用例） | {avg_time_prev:.0f}s | {avg_time_curr:.0f}s | {_delta(avg_time_prev, avg_time_curr)} |")
    else:
        lines.append(f"| 平均 Token | {pa['avg_tokens']:,.0f} | {agg['avg_tokens']:,.0f} | {_delta(pa['avg_tokens'], agg['avg_tokens'])} |")
        lines.append(f"| 平均耗时 | {pa['avg_elapsed']:.0f}s | {agg['avg_elapsed']:.0f}s | {_delta(pa['avg_elapsed'], agg['avg_elapsed'])} |")

    lines.append(f"| 预估费用 | ${pa['total_cost_usd']:.4f} | ${agg['total_cost_usd']:.4f} | {_delta(pa['total_cost_usd'], agg['total_cost_usd'])} |")


# ──────────────────────── 对抗性测试框架 ─────────────────────────
#
# 用途：验证 LLM-as-Judge 守门员的"视力"——能否检测到确定性注入的功能缺陷。
#
# 运行方式：
#   python scripts/benchmark.py adversarial --case flask_todo
#   python scripts/benchmark.py adversarial --case calculator
#   python scripts/benchmark.py adversarial --all
#
# 输出：
#   - 每个缺陷的 Judge 判定结果（pass/fail）
#   - 拦截率 = Judge 检测到的缺陷数 / 注入的缺陷总数
#   - Markdown 报告（可选 --export）


import re as _re


def _collect_py_files(workspace: str) -> list[str]:
    """递归收集 workspace 下所有 .py 文件（P0-5: 修复只搜顶层目录的问题）"""
    result = []
    for root, dirs, files in os.walk(workspace):
        # 跳过虚拟环境和缓存目录
        dirs[:] = [d for d in dirs if d not in (".venv", "venv", "__pycache__", ".git", "node_modules")]
        for fname in files:
            if fname.endswith(".py"):
                result.append(os.path.join(root, fname))
    return result


# ── 缺陷定义 ────────────────────────────────────────────────────

def _inject_hollow_function(workspace: str, pattern: str) -> dict:
    """将匹配 pattern 的函数体替换为 pass（模拟"写了签名但忘了实现"）

    优先选择有 @app.route / @bp.route / @*.route 装饰器的函数（P0-6），
    递归搜索所有 .py 文件（P0-5）。

    Returns: {"injected": bool, "description": str, "file": str}
    """
    py_files = _collect_py_files(workspace)
    fn_re = _re.compile(
        rf"((?:@\w+\.route[^\n]*\n)+)(def\s+(?:{pattern})\w*\([^)]*\)[^:]*:)(.*?)(?=\n(?:@|\s*def\s)|\Z)",
        _re.DOTALL,
    )
    # 第二遍：无装饰器的普通函数（fallback）
    fn_re_bare = _re.compile(
        rf"(def\s+(?:{pattern})\w*\([^)]*\)[^:]*:)(.*?)(?=\n\s*def\s|\Z)",
        _re.DOTALL,
    )

    for fpath in py_files:
        try:
            with open(fpath, encoding="utf-8") as f:
                src = f.read()

            # 优先匹配有路由装饰器的函数
            match = fn_re.search(src)
            if match:
                body_start = match.start(3)
                body_end = match.end(3)
                indent = "    "
                new_src = src[:body_start] + f"\n{indent}pass  # [缺陷注入] 函数体已清空\n" + src[body_end:]
                with open(fpath, "w", encoding="utf-8") as f:
                    f.write(new_src)
                fname = os.path.relpath(fpath, workspace)
                return {"injected": True, "description": f"清空 {fname} 路由函数（匹配 '{pattern}'）", "file": fname}

            # Fallback: 匹配普通函数
            match = fn_re_bare.search(src)
            if match:
                body_start = match.start(2)
                body_end = match.end(2)
                indent = "    "
                new_src = src[:body_start] + f"\n{indent}pass  # [缺陷注入] 函数体已清空\n" + src[body_end:]
                with open(fpath, "w", encoding="utf-8") as f:
                    f.write(new_src)
                fname = os.path.relpath(fpath, workspace)
                return {"injected": True, "description": f"清空 {fname} 中匹配 '{pattern}' 的函数体", "file": fname}
        except Exception:
            continue
    return {"injected": False, "description": f"未找到匹配 '{pattern}' 的函数", "file": ""}


def _inject_remove_route_method(workspace: str, method: str = "GET") -> dict:
    """从 Flask 路由中删除指定 HTTP 方法（P0-5: 递归；P2-11: 支持隐式 GET 路由）

    两种注入策略：
    1. 显式 methods=['GET', 'POST'] → 从列表中删除 GET
    2. 隐式 @app.route('/path')（默认 GET）→ 加上 methods=['POST'] 覆盖
    """
    py_files = _collect_py_files(workspace)
    methods_re = _re.compile(
        rf"(methods\s*=\s*\[)([^\]]*'{method}'[^\]]*)(\])", _re.IGNORECASE
    )
    # 隐式 GET: @app.route('/path') 或 @bp.route('/path') 不带 methods
    implicit_re = _re.compile(
        r"(@\w+\.route\(['\"][^'\"]+['\"])(\s*\))", _re.IGNORECASE
    )

    for fpath in py_files:
        try:
            with open(fpath, encoding="utf-8") as f:
                src = f.read()

            # 策略 1: 显式 methods 列表
            if methods_re.search(src):
                new_src = _re.sub(rf",?\s*'{method}'\s*,?", "", src, flags=_re.IGNORECASE)
                new_src = _re.sub(r"\[\s*,", "[", new_src)
                new_src = _re.sub(r",\s*\]", "]", new_src)
                with open(fpath, "w", encoding="utf-8") as f:
                    f.write(new_src)
                fname = os.path.relpath(fpath, workspace)
                return {"injected": True, "description": f"从 {fname} 显式路由中删除 {method} 方法", "file": fname}

            # 策略 2: 隐式 GET（无 methods 参数）→ 强制限定为 POST only
            if method == "GET" and implicit_re.search(src):
                new_src = implicit_re.sub(r"\1, methods=['POST']\2", src, count=1)
                with open(fpath, "w", encoding="utf-8") as f:
                    f.write(new_src)
                fname = os.path.relpath(fpath, workspace)
                return {"injected": True, "description": f"给 {fname} 隐式 GET 路由强制加 methods=['POST']", "file": fname}
        except Exception:
            continue
    return {"injected": False, "description": f"未找到包含 '{method}' 的路由定义", "file": ""}


def _inject_broken_return(workspace: str, function_name: str, broken_value: str = "0") -> dict:
    """将函数的所有 return 语句替换为返回固定值（P0-5: 递归；P1-10: 替换全部 return）

    替换函数体内所有非 None/空 return，确保正常路径也被破坏。
    """
    py_files = _collect_py_files(workspace)
    # 先定位函数体范围
    fn_start_re = _re.compile(
        rf"^([ \t]*)def\s+{_re.escape(function_name)}\s*\(", _re.MULTILINE
    )
    return_re = _re.compile(r"^([ \t]+)return\s+(?!None\b)(.+)$", _re.MULTILINE)

    for fpath in py_files:
        try:
            with open(fpath, encoding="utf-8") as f:
                src = f.read()
            m_start = fn_start_re.search(src)
            if not m_start:
                continue

            fn_indent = m_start.group(1)
            body_start = m_start.start()

            # 找到函数结束位置（下一个同缩进的 def/class 或文件末尾）
            next_fn_re = _re.compile(
                rf"^{_re.escape(fn_indent)}(?:def|class)\s", _re.MULTILINE
            )
            m_end = next_fn_re.search(src, m_start.end())
            body_end = m_end.start() if m_end else len(src)

            fn_body = src[body_start:body_end]
            # 替换函数体内所有 return 语句
            replaced, count = return_re.subn(
                rf"\1return {broken_value}  # [缺陷注入]",
                fn_body,
            )
            if count == 0:
                continue

            new_src = src[:body_start] + replaced + src[body_end:]
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(new_src)
            fname = os.path.relpath(fpath, workspace)
            return {
                "injected": True,
                "description": f"将 {fname}::{function_name} 的 {count} 个 return 替换为 {broken_value}",
                "file": fname,
            }
        except Exception:
            continue
    return {"injected": False, "description": f"未找到函数 '{function_name}'", "file": ""}


# ── 用例级缺陷集 ──────────────────────────────────────────────

ADVERSARIAL_DEFECTS: dict[str, list[dict]] = {
    "flask_todo": [
        {
            "id": "hollow_delete",
            "description": "DELETE 端点函数体清空为 pass（删除功能失效）",
            "inject": lambda ws: _inject_hollow_function(ws, r"delete|remove"),
        },
        {
            "id": "missing_get_method",
            "description": "GET 方法从路由定义中删除（读取列表返回 405）",
            "inject": lambda ws: _inject_remove_route_method(ws, "GET"),
        },
    ],
    "calculator": [
        {
            "id": "broken_add",
            "description": "add 方法返回硬编码 0（加法永远返回 0）",
            "inject": lambda ws: _inject_broken_return(ws, "add", "0"),
        },
        {
            "id": "broken_divide",
            "description": "divide 方法返回硬编码 1（除法永远返回 1）",
            "inject": lambda ws: _inject_broken_return(ws, "divide", "1"),
        },
    ],
}


# ── 对抗性测试执行器 ──────────────────────────────────────────

def run_adversarial(case_name: str, *, export: bool = False) -> dict:
    """对指定用例执行对抗性测试

    流程：
    1. 正常跑一次 Agent，完成任务（自报告 pass）
    2. 快照 workspace 到临时目录（不销毁沙箱）
    3. 对每个缺陷：注入 → 调用 Judge → 记录判定结果 → 还原
    4. 输出拦截率报告

    Returns:
        {
            "case": str,
            "defects_injected": int,
            "defects_detected": int,
            "intercept_rate": float,
            "results": [{"id", "description", "injected", "judge_passed", "judge_skipped", "reasoning"}]
        }
    """
    import shutil
    from autoc.app import build_orchestrator
    from autoc.config import load_config
    from autoc.testing.mock_plans import get_test_case

    defects = ADVERSARIAL_DEFECTS.get(case_name, [])
    if not defects:
        console.print(f"[yellow]⚠ 用例 '{case_name}' 没有定义缺陷集，可选: {list(ADVERSARIAL_DEFECTS.keys())}[/yellow]")
        return {}

    case_def = next((c for c in BENCHMARK_CASES if c["name"] == case_name), None)
    if not case_def:
        console.print(f"[red]✗ 未找到 benchmark 用例: {case_name}[/red]")
        return {}

    console.print(Panel(
        f"[bold cyan]对抗性测试: {case_name}[/bold cyan]\n"
        f"缺陷数量: {len(defects)}  |  "
        f"目标: 验证 LLM-as-Judge 是否能检测到确定性注入的功能缺陷",
        title="adversarial",
    ))

    # Step 1: 正常跑 Agent
    tc = get_test_case(case_name)
    workspace = tempfile.mkdtemp(prefix=f"autoc-adv-{case_name}-")
    console.print(f"\n  [bold]Step 1[/bold]: 运行 Agent 完成任务...")

    orc = None
    agent_result = None
    changed_files: list[str] = []
    git_ops = None

    try:
        config = load_config()
        orc = build_orchestrator(config=config, project_path=workspace)
        orc.critique = None  # 对抗测试聚焦 Judge，不需要 Critique
        agent_result = orc.run(tc["requirement"], max_iterations=case_def["max_iterations"])
        success = agent_result.get("success", False)
        if not success:
            console.print(f"  [yellow]⚠ Agent 未完成任务（exit={agent_result.get('exit_reason', '?')}），对抗测试无意义，跳过[/yellow]")
            # P1-9: Agent 失败时也要清理 workspace，避免磁盘泄漏
            shutil.rmtree(workspace, ignore_errors=True)
            return {}
        console.print(f"  [green]✓ Agent 完成（tokens={agent_result.get('total_tokens', 0):,}）[/green]")
        # 收集变更文件（递归）
        changed_files = []
        for root, dirs, files in os.walk(workspace):
            dirs[:] = [d for d in dirs if d not in (".venv", "venv", "__pycache__", ".git", "node_modules")]
            for fname in files:
                if not fname.startswith("."):
                    rel = os.path.relpath(os.path.join(root, fname), workspace)
                    changed_files.append(rel)
        git_ops = getattr(orc, "git_ops", None)
    except Exception as e:
        console.print(f"  [red]✗ Agent 执行异常: {e}[/red]")
        shutil.rmtree(workspace, ignore_errors=True)
        return {}
    finally:
        if orc:
            try:
                orc.destroy_sandbox()
            except Exception:
                pass

    # Step 2: 快照 workspace（P0-7: 建立 git 历史，让 Judge 可以看到真实 diff）
    snapshot = workspace + "_snapshot"
    shutil.copytree(workspace, snapshot)
    _snapshot_git_ready = False
    try:
        # 初始化 git 仓库：将 Agent 生成的文件作为"初始提交"，
        # 后续注入缺陷后再提交为"污染提交"，Judge 可以通过 git diff HEAD~1 看到差异。
        # P1-C: 每步都用 check=True，任一步失败立即抛出 CalledProcessError，
        # 避免产出"半成品" git 仓库导致 diff 输出错误。
        subprocess.run(["git", "init"], cwd=snapshot, capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "autoc-benchmark@local"],
            cwd=snapshot, capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "autoc-benchmark"],
            cwd=snapshot, capture_output=True, check=True,
        )
        subprocess.run(["git", "add", "-A"], cwd=snapshot, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "initial: agent output (clean)"],
            cwd=snapshot, capture_output=True, check=True,
        )
        _snapshot_git_ready = True
        console.print("  [dim]git 历史初始化完成（Judge 将使用 git diff 模式）[/dim]")
    except subprocess.CalledProcessError as e:
        console.print(
            f"  [yellow]⚠ git 初始化失败（cmd: {e.cmd}，Judge 将 fallback 到文件内容模式）[/yellow]"
        )
    except Exception as e:
        console.print(f"  [dim]⚠ git 初始化异常（Judge 将 fallback 到文件内容模式）: {e}[/dim]")

    # Step 3: 对每个缺陷执行注入 → Judge → 还原
    console.print(f"\n  [bold]Step 2[/bold]: 依次注入 {len(defects)} 个缺陷并调用 Judge...\n")

    results = []
    llm_judge = None
    # P1-8: 直接用 ModelConfigManager 构造 LLM critique 实例，
    # 不再创建完整 Orchestrator（原做法会启动 Docker 沙箱，造成容器泄漏）
    try:
        from autoc.core.llm.model_config import ModelConfigManager
        from autoc.core.llm import LLMClient
        from autoc.config import PROJECT_ROOT as _proj_root
        mcm = ModelConfigManager(_proj_root)
        critique_cfg = mcm.build_llm_config_for_agent("critique") or mcm.build_llm_config_for_agent("coder")
        if critique_cfg and critique_cfg.api_key:
            llm_judge = LLMClient(critique_cfg)
        else:
            console.print("  [yellow]⚠ 未找到 critique/coder LLM 配置，Judge 将 skipped[/yellow]")
    except Exception as e:
        console.print(f"  [yellow]⚠ LLM Judge 初始化失败: {e}，将记录 skipped[/yellow]")

    from autoc.core.verification import judge_task_completion

    for defect in defects:
        defect_id = defect["id"]
        description = defect["description"]

        # 复制快照到注入工作区（含 .git 历史，P0-7）
        inject_ws = workspace + f"_inject_{defect_id}"
        if os.path.exists(inject_ws):
            shutil.rmtree(inject_ws)
        shutil.copytree(snapshot, inject_ws)

        # 注入缺陷
        inject_result = defect["inject"](inject_ws)
        injected = inject_result.get("injected", False)

        console.print(f"  [cyan]▸ {defect_id}[/cyan]: {description}")
        if not injected:
            console.print(f"    [yellow]⚠ 注入失败: {inject_result.get('description', '')}[/yellow]")
            results.append({
                "id": defect_id, "description": description,
                "injected": False, "judge_passed": None,
                "judge_skipped": True, "reasoning": "注入失败",
            })
            shutil.rmtree(inject_ws, ignore_errors=True)
            continue

        console.print(f"    注入: {inject_result['description']}")

        # P0-7: 将注入的缺陷提交为新 commit，让 Judge 通过 git diff HEAD~1 看到真实变化
        # 只有 snapshot git 初始化成功时才有意义
        if _snapshot_git_ready:
            try:
                subprocess.run(
                    ["git", "add", "-A"], cwd=inject_ws, capture_output=True, check=True
                )
                # 按字节安全截断（避免多字节字符中间截断导致 git 命令乱码）
                msg_suffix = description.encode("utf-8")[:60].decode("utf-8", errors="ignore")
                subprocess.run(
                    ["git", "commit", "-m", f"defect: {defect_id} - {msg_suffix}"],
                    cwd=inject_ws, capture_output=True, check=True,
                )
            except subprocess.CalledProcessError as e:
                console.print(f"    [dim]⚠ 缺陷 commit 失败（{e.cmd}），Judge 将用文件内容模式[/dim]")
            except Exception as e:
                console.print(f"    [dim]⚠ 缺陷 commit 异常: {e}[/dim]")

        # 调用 Judge
        # P1-B: 不传 git_ops（git_ops 指向原始 workspace，会读到错误的 diff）。
        # 强制走 _try_git_diff 的 subprocess fallback 路径：
        #   git diff HEAD~1 cwd=inject_ws → 精确看到注入的缺陷变更
        task_desc = tc["requirement"][:400]
        judge_result = judge_task_completion(
            llm=llm_judge,
            task_title=case_name,
            task_description=task_desc,
            acceptance_criteria=[],
            changed_files=changed_files,
            workspace_dir=inject_ws,
            dev_report_summary="Agent 自报告：任务完成，所有验证通过。",
            git_ops=None,  # 不传，让 Judge 直接在 inject_ws 跑 git diff HEAD~1
        )

        icon = "✅" if judge_result.skipped else ("❌" if not judge_result.passed else "⚠️ 漏过")
        detected = not judge_result.passed and not judge_result.skipped
        console.print(
            f"    Judge: {icon}  "
            f"passed={judge_result.passed}  skipped={judge_result.skipped}\n"
            f"    理由: {(judge_result.reasoning or '')[:120]}"
        )

        results.append({
            "id": defect_id, "description": description,
            "injected": True,
            "judge_passed": judge_result.passed,
            "judge_skipped": judge_result.skipped,
            "reasoning": judge_result.reasoning or "",
            "risk_points": judge_result.risk_points or "",
        })

        shutil.rmtree(inject_ws, ignore_errors=True)

    # 清理
    shutil.rmtree(workspace, ignore_errors=True)
    shutil.rmtree(snapshot, ignore_errors=True)

    # 统计
    injected_ok = [r for r in results if r["injected"]]
    detected = [r for r in injected_ok if not r.get("judge_passed") and not r.get("judge_skipped")]
    intercept_rate = len(detected) / len(injected_ok) if injected_ok else 0.0

    console.print(f"\n  {'─'*50}")
    console.print(f"  [bold]对抗性测试完成[/bold]")
    console.print(f"  注入成功: {len(injected_ok)}/{len(defects)}")
    console.print(f"  Judge 检测到: {len(detected)}/{len(injected_ok)}")

    rate_color = "green" if intercept_rate >= 0.6 else ("yellow" if intercept_rate >= 0.3 else "red")
    console.print(f"  [bold {rate_color}]拦截率: {intercept_rate:.0%}[/bold {rate_color}]")

    summary = {
        "case": case_name,
        "defects_injected": len(injected_ok),
        "defects_detected": len(detected),
        "intercept_rate": intercept_rate,
        "results": results,
    }

    if export:
        _export_adversarial_report(summary)

    return summary


def _export_adversarial_report(summary: dict) -> None:
    """导出对抗性测试 Markdown 报告"""
    os.makedirs(REPORT_DIR, exist_ok=True)
    case = summary["case"]
    ts = time.strftime("%Y%m%d_%H%M%S")
    path = os.path.join(REPORT_DIR, f"adversarial_{case}_{ts}.md")

    rate = summary["intercept_rate"]
    rate_str = f"{rate:.0%}"
    verdict = "✅ 优秀" if rate >= 0.8 else ("⚠️ 可接受" if rate >= 0.5 else "❌ 不足")

    lines = [
        f"# 对抗性测试报告: {case}",
        "",
        f"> 时间: {time.strftime('%Y-%m-%d %H:%M')}",
        f"> Git: `{_get_git_info()[0]}`",
        "",
        "## 总结",
        "",
        f"| 指标 | 值 |",
        f"|------|:--:|",
        f"| 注入缺陷数 | {summary['defects_injected']} |",
        f"| Judge 检测到 | {summary['defects_detected']} |",
        f"| **拦截率** | **{rate_str}** {verdict} |",
        "",
        "## 逐缺陷结果",
        "",
        "| 缺陷 ID | 描述 | 注入 | Judge 判定 | 理由摘要 |",
        "|---------|------|:----:|:----------:|---------|",
    ]

    for r in summary["results"]:
        injected = "✅" if r["injected"] else "❌"
        if not r["injected"] or r.get("judge_skipped"):
            judge_str = "⏭️ skip"
        elif not r.get("judge_passed"):
            judge_str = "🛑 拦截"
        else:
            judge_str = "⚠️ 漏过"
        reasoning = (r.get("reasoning") or "")[:60].replace("|", "\\|")
        lines.append(f"| {r['id']} | {r['description'][:40]} | {injected} | {judge_str} | {reasoning} |")

    lines += ["", "---", f"*自动生成于 {time.strftime('%Y-%m-%d %H:%M')}*"]

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    console.print(f"\n  报告已导出: {path}")


# ──────────────────────────── CLI ────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="AutoC Benchmark — 持续效果度量",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")

    # run
    p_run = sub.add_parser("run", help="执行 benchmark")
    p_run.add_argument("--tag", required=True, help="结果标签（如 baseline, after_edit_file）")
    p_run.add_argument("--cases", type=str, help="逗号分隔的用例名（默认全部）")
    p_run.add_argument("--description", type=str, default="", help="本次运行的描述")
    p_run.add_argument("--critique", action="store_true", default=False,
                       help="启用 Critique 评审（默认关闭以聚焦执行效率）")
    p_run.add_argument("--timeout", type=int, default=DEFAULT_CASE_TIMEOUT,
                       help=f"单用例超时秒数（默认 {DEFAULT_CASE_TIMEOUT}）")
    p_run.add_argument("--force", action="store_true", default=False,
                       help="允许覆盖已有同名标签")
    p_run.add_argument("--repeat", type=int, default=3,
                       help="每用例重复次数（默认 3，取中位数解决 LLM 随机性）")
    p_run.add_argument("--quick", action="store_true", default=False,
                       help="快速模式：每用例只跑 1 次（等价于 --repeat 1）")
    p_run.add_argument("--workers", type=int, default=1,
                       help="并行 worker 数（默认 1=串行）。注意：并行时 SIGALRM 降级为 future 超时兜底")
    p_run.add_argument("--parallel", action="store_true", default=False,
                       help="并行模式快捷选项（等价于 --workers 2）")

    # compare
    p_cmp = sub.add_parser("compare", help="对比两次结果")
    p_cmp.add_argument("tag_a", help="基线标签")
    p_cmp.add_argument("tag_b", help="当前标签")
    p_cmp.add_argument("--export", action="store_true", help="导出 Markdown 报告")

    # history
    sub.add_parser("history", help="查看历史运行")

    # trend
    p_trend = sub.add_parser("trend", help="查看指标历史趋势（Token/耗时/费用）")
    p_trend.add_argument("--case", type=str, default=None, help="过滤用例名（支持子串匹配）")
    p_trend.add_argument("--metric", choices=["tokens", "elapsed", "cost"], default="tokens",
                         help="展示指标（默认 tokens）")
    p_trend.add_argument("--export", action="store_true", help="导出 Markdown 趋势报告")

    # list
    sub.add_parser("cases", help="列出可用测试用例")

    # adversarial
    p_adv = sub.add_parser("adversarial", help="对抗性测试 — 注入缺陷验证 Judge 拦截率")
    p_adv_group = p_adv.add_mutually_exclusive_group(required=True)
    p_adv_group.add_argument("--case", type=str, help=f"指定用例（可选: {list(ADVERSARIAL_DEFECTS.keys())}）")
    p_adv_group.add_argument("--all", action="store_true", help="对所有已定义缺陷集的用例执行")
    p_adv.add_argument("--export", action="store_true", help="导出 Markdown 报告")

    args = parser.parse_args()

    if args.command == "run":
        cases = args.cases.split(",") if args.cases else None
        repeat = 1 if args.quick else args.repeat
        workers = 2 if args.parallel else args.workers
        run_benchmark(
            tag=args.tag, cases=cases, description=args.description,
            no_critique=not args.critique,
            timeout=args.timeout,
            force=args.force,
            repeat=repeat,
            workers=workers,
        )

    elif args.command == "compare":
        compare_runs(args.tag_a, args.tag_b, export=args.export)

    elif args.command == "history":
        show_history()

    elif args.command == "trend":
        show_trend(
            case_filter=args.case,
            metric=args.metric,
            export=args.export,
        )

    elif args.command == "cases":
        t = Table(show_header=True, header_style="bold")
        t.add_column("名称", style="cyan")
        t.add_column("复杂度")
        t.add_column("迭代上限", justify="right")
        t.add_column("验证项", justify="right")
        t.add_column("描述")
        for c in BENCHMARK_CASES:
            n_checks = (len(c.get("expected_files", []))
                        + len(c.get("host_checks", []))
                        + len(c.get("runtime_checks", []))
                        + len(c.get("l3_checks", [])))
            t.add_row(
                c["name"], c["complexity"], str(c["max_iterations"]),
                str(n_checks), c["description"],
            )
        console.print(t)
        console.print(f"\n[dim]核心用例（默认运行）: {', '.join(CORE_CASES)}[/dim]")
        console.print(f"[dim]全部用例: {', '.join(c['name'] for c in BENCHMARK_CASES)}[/dim]")

    elif args.command == "adversarial":
        if args.all:
            all_results = []
            for cn in ADVERSARIAL_DEFECTS:
                r = run_adversarial(cn, export=args.export)
                if r:
                    all_results.append(r)
            if all_results:
                total_injected = sum(r["defects_injected"] for r in all_results)
                total_detected = sum(r["defects_detected"] for r in all_results)
                overall_rate = total_detected / total_injected if total_injected else 0
                rate_color = "green" if overall_rate >= 0.6 else ("yellow" if overall_rate >= 0.3 else "red")
                console.print(f"\n[bold]全局拦截率: [{rate_color}]{overall_rate:.0%}[/{rate_color}][/bold]  ({total_detected}/{total_injected})")
        else:
            run_adversarial(args.case, export=args.export)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
