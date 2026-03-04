"""Benchmark Web API — 对齐 CLI 全部功能的 REST 端点"""

import json
import os
import re
import threading

from fastapi import Query, Body
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from autoc.server import router
from fastapi import HTTPException

_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TAG_RE = re.compile(r'^[a-zA-Z0-9_\-]+$')


def _validate_tag(tag: str):
    if not _TAG_RE.match(tag):
        raise HTTPException(status_code=400, detail="tag 只允许字母、数字、下划线和横线")
RESULTS_DIR = os.path.join(_project_root, "benchmarks", "results")
REPORT_DIR = os.path.join(_project_root, "benchmarks", "reports")
LOG_DIR = os.path.join(_project_root, "benchmarks", "logs")
RUNNING_DIR = os.path.join(_project_root, "benchmarks", "running")
CUSTOM_CASES_FILE = os.path.join(_project_root, "benchmarks", "cases.json")

# 实例级停止事件：每个 tag 对应一个 threading.Event，Web 端停止 benchmark 用
_stop_events: dict[str, threading.Event] = {}
_stop_events_lock = threading.Lock()


def _list_tags() -> list[str]:
    if not os.path.isdir(RESULTS_DIR):
        return []
    return sorted(
        f.replace(".json", "") for f in os.listdir(RESULTS_DIR) if f.endswith(".json")
    )


def _load_result(tag: str) -> dict | None:
    path = os.path.join(RESULTS_DIR, f"{tag}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _check_integrity(data: dict) -> str:
    """返回 ok / warn / bad"""
    cases = data.get("cases", [])
    if not cases:
        return "bad"
    version = data.get("schema_version", 1)
    if version < 3:
        return "warn"
    issues = 0
    for c in cases:
        if c.get("success"):
            if c.get("dev_iterations", 0) == 0:
                issues += 1
            if not c.get("exit_reason"):
                issues += 1
            if c.get("tasks_total", 0) == 0:
                issues += 1
    if not data.get("environment"):
        issues += 1
    if issues == 0:
        return "ok"
    return "warn" if issues <= 2 else "bad"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


# ── GET /benchmark/running ──

@router.get("/benchmark/running")
def list_running_benchmarks():
    """列出正在运行的 benchmark（CLI 或 Web 发起均包含）"""
    if not os.path.isdir(RUNNING_DIR):
        return {"running": []}
    running = []
    for fname in os.listdir(RUNNING_DIR):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(RUNNING_DIR, fname)
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            pid = data.get("pid")
            if pid and not _pid_alive(pid):
                os.remove(path)
                continue
            running.append({
                "tag": data.get("tag", ""),
                "started_at": data.get("started_at", ""),
                "total_cases": data.get("total_cases", 0),
                "cases": data.get("cases", []),
                "events_count": len(data.get("events", [])),
            })
        except Exception:
            pass
    return {"running": running}


# ── GET /benchmark/live/{tag} ──

@router.get("/benchmark/live/{tag}")
async def benchmark_live_stream(tag: str):
    """SSE: 订阅 benchmark 实时事件（CLI 或 Web 发起均支持）"""
    _validate_tag(tag)
    running_path = os.path.join(RUNNING_DIR, f"{tag}.json")

    async def _stream():
        import asyncio
        import time as _time
        sent_count = 0
        ticks_no_file = 0
        stream_started = _time.monotonic()
        MAX_STREAM_SECONDS = 4 * 3600  # 4 小时硬上限，防止进程 deadlock 但 PID 存活

        while True:
            if _time.monotonic() - stream_started > MAX_STREAM_SECONDS:
                yield f"data: {json.dumps({'type': 'run_error', 'error': 'SSE 流超过 4 小时上限'})}\n\n"
                break
            if os.path.exists(running_path):
                ticks_no_file = 0
                try:
                    with open(running_path, encoding="utf-8") as f:
                        data = json.load(f)
                    events = data.get("events", [])
                    new_events = events[sent_count:]
                    for evt in new_events:
                        yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
                    sent_count = len(events)
                    # 终态事件出现立即退出，避免文件删除后多活
                    if any(e.get("type") in ("run_complete", "run_error") for e in new_events):
                        break
                    # 进程已死但文件残留 → 推送错误并退出
                    pid = data.get("pid")
                    if pid and not _pid_alive(pid):
                        yield f"data: {json.dumps({'type': 'run_error', 'error': '执行进程已终止'})}\n\n"
                        try:
                            os.remove(running_path)
                        except Exception:
                            pass
                        break
                except Exception:
                    pass
                await asyncio.sleep(0.5)
            else:
                ticks_no_file += 1
                if ticks_no_file >= 20:
                    result = _load_result(tag)
                    if result:
                        agg = result.get("aggregates", {})
                        yield f"data: {json.dumps({'type': 'run_complete', 'tag': tag, 'success': True, 'completion_rate': agg.get('completion_rate', 0), 'total_elapsed': result.get('total_elapsed', 0), 'case_count': len(result.get('cases', []))})}\n\n"
                    break
                await asyncio.sleep(0.5)

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── 自定义用例存储 ──

def _load_custom_cases() -> list[dict]:
    if not os.path.exists(CUSTOM_CASES_FILE):
        return []
    try:
        with open(CUSTOM_CASES_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_custom_cases(cases: list[dict]):
    os.makedirs(os.path.dirname(CUSTOM_CASES_FILE), exist_ok=True)
    with open(CUSTOM_CASES_FILE, "w", encoding="utf-8") as f:
        json.dump(cases, f, ensure_ascii=False, indent=2)


class BenchmarkCaseBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=64, pattern=r'^[a-zA-Z0-9_\-]+$')
    complexity: str = Field("simple", pattern=r'^(trivial|simple|medium|complex)$')
    max_iterations: int = Field(15, ge=1, le=100)
    description: str = Field("", max_length=256)
    expected_files: list[str] = Field(default_factory=list)
    host_checks: list[str] = Field(default_factory=list)
    runtime_checks: list[str] = Field(default_factory=list)
    is_core: bool = False


_NAME_RE = re.compile(r'^[a-zA-Z0-9_\-]+$')


def _format_case(c: dict, *, source: str = "builtin", core_names: list[str] | None = None) -> dict:
    """统一用例输出格式"""
    host = c.get("host_checks", [])
    runtime = c.get("runtime_checks", [])
    return {
        "name": c["name"],
        "complexity": c["complexity"],
        "max_iterations": c["max_iterations"],
        "description": c.get("description", ""),
        "expected_files": c.get("expected_files", []),
        "host_checks": len(host) if isinstance(host, list) else host,
        "runtime_checks": len(runtime) if isinstance(runtime, list) else runtime,
        "is_core": c.get("is_core", False) or (c["name"] in (core_names or [])),
        "source": source,
    }


# ── GET /benchmark/cases ──

@router.get("/benchmark/cases")
async def list_benchmark_cases():
    from scripts.benchmark import BENCHMARK_CASES, CORE_CASES
    cases = []
    for c in BENCHMARK_CASES:
        cases.append(_format_case(c, source="builtin", core_names=CORE_CASES))
    for c in _load_custom_cases():
        cases.append(_format_case(c, source="custom"))
    return {"cases": cases, "core_cases": CORE_CASES}


# ── POST /benchmark/cases ──

@router.post("/benchmark/cases")
async def create_benchmark_case(body: BenchmarkCaseBody):
    from scripts.benchmark import BENCHMARK_CASES
    builtin_names = {c["name"] for c in BENCHMARK_CASES}
    custom_cases = _load_custom_cases()
    custom_names = {c["name"] for c in custom_cases}
    if body.name in builtin_names:
        raise HTTPException(status_code=409, detail=f"内置用例 '{body.name}' 不可覆盖")
    if body.name in custom_names:
        raise HTTPException(status_code=409, detail=f"用例 '{body.name}' 已存在")
    new_case = body.model_dump()
    custom_cases.append(new_case)
    _save_custom_cases(custom_cases)
    return {"success": True, "case": _format_case(new_case, source="custom")}


# ── PUT /benchmark/cases/{name} ──

@router.put("/benchmark/cases/{name}")
async def update_benchmark_case(name: str, body: BenchmarkCaseBody):
    from scripts.benchmark import BENCHMARK_CASES
    if not _NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="用例名只允许字母、数字、下划线和横线")
    builtin_names = {c["name"] for c in BENCHMARK_CASES}
    if name in builtin_names:
        raise HTTPException(status_code=403, detail=f"内置用例 '{name}' 不可修改")
    custom_cases = _load_custom_cases()
    found = False
    for i, c in enumerate(custom_cases):
        if c["name"] == name:
            updated = body.model_dump()
            updated["name"] = body.name if body.name else name
            # 如果改名了，检查新名字是否冲突
            if updated["name"] != name:
                all_names = builtin_names | {cc["name"] for cc in custom_cases if cc["name"] != name}
                if updated["name"] in all_names:
                    raise HTTPException(status_code=409, detail=f"用例名 '{updated['name']}' 已存在")
            custom_cases[i] = updated
            found = True
            break
    if not found:
        raise HTTPException(status_code=404, detail=f"自定义用例 '{name}' 不存在")
    _save_custom_cases(custom_cases)
    return {"success": True, "case": _format_case(custom_cases[i], source="custom")}


# ── DELETE /benchmark/cases/{name} ──

@router.delete("/benchmark/cases/{name}")
async def delete_benchmark_case(name: str):
    from scripts.benchmark import BENCHMARK_CASES
    if not _NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="用例名只允许字母、数字、下划线和横线")
    builtin_names = {c["name"] for c in BENCHMARK_CASES}
    if name in builtin_names:
        raise HTTPException(status_code=403, detail=f"内置用例 '{name}' 不可删除")
    custom_cases = _load_custom_cases()
    new_cases = [c for c in custom_cases if c["name"] != name]
    if len(new_cases) == len(custom_cases):
        raise HTTPException(status_code=404, detail=f"自定义用例 '{name}' 不存在")
    _save_custom_cases(new_cases)
    return {"success": True, "deleted": name}


# ── PATCH /benchmark/cases/{name}/core ──

@router.patch("/benchmark/cases/{name}/core")
async def toggle_case_core(name: str, is_core: bool = Body(..., embed=True)):
    """切换自定义用例的核心标记"""
    if not _NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="用例名只允许字母、数字、下划线和横线")
    custom_cases = _load_custom_cases()
    found = False
    for c in custom_cases:
        if c["name"] == name:
            c["is_core"] = is_core
            found = True
            break
    if not found:
        raise HTTPException(status_code=404, detail=f"自定义用例 '{name}' 不存在")
    _save_custom_cases(custom_cases)
    return {"success": True}


# ── GET /benchmark/history ──

@router.get("/benchmark/history")
async def list_benchmark_history():
    tags = _list_tags()
    runs = []
    for tag in tags:
        data = _load_result(tag)
        if not data:
            continue
        agg = data.get("aggregates", {})
        runs.append({
            "tag": tag,
            "timestamp": data.get("timestamp", ""),
            "git_commit": data.get("git_commit", ""),
            "git_dirty": data.get("git_dirty", False),
            "description": data.get("description", ""),
            "critique_enabled": data.get("critique_enabled", False),
            "total_elapsed": data.get("total_elapsed", 0),
            "completion_rate": agg.get("completion_rate", 0),
            "avg_tokens": agg.get("avg_tokens", 0),
            "avg_elapsed": agg.get("avg_elapsed", 0),
            "avg_iterations": agg.get("avg_iterations", 0),
            "total_tokens": agg.get("total_tokens", 0),
            "total_cost_usd": agg.get("total_cost_usd", 0),
            "avg_pc_ratio": agg.get("avg_pc_ratio", 0),
            "avg_cache_hit_rate": agg.get("avg_cache_hit_rate", 0),
            "case_count": len(data.get("cases", [])),
            "integrity": _check_integrity(data),
            "schema_version": data.get("schema_version", 1),
            "environment": data.get("environment", {}),
        })
    runs.sort(key=lambda r: r["timestamp"], reverse=True)
    return {"runs": runs}


# ── GET /benchmark/runs/{tag} ──

@router.get("/benchmark/runs/{tag}")
async def get_benchmark_run(tag: str):
    _validate_tag(tag)
    data = _load_result(tag)
    if not data:
        return JSONResponse(status_code=404, content={"error": f"未找到结果: {tag}"})
    data["integrity"] = _check_integrity(data)
    return data


# ── GET /benchmark/compare/{tag_a}/{tag_b} ──

@router.get("/benchmark/compare/{tag_a}/{tag_b}")
async def compare_benchmark_runs(tag_a: str, tag_b: str):
    _validate_tag(tag_a)
    _validate_tag(tag_b)
    a = _load_result(tag_a)
    b = _load_result(tag_b)
    if not a:
        return JSONResponse(status_code=404, content={"error": f"未找到: {tag_a}"})
    if not b:
        return JSONResponse(status_code=404, content={"error": f"未找到: {tag_b}"})

    a_cases = {c["case_name"]: c for c in a["cases"]}
    b_cases = {c["case_name"]: c for c in b["cases"]}
    common_success = [
        name for name in a_cases
        if name in b_cases
        and a_cases[name].get("success")
        and b_cases[name].get("success")
    ]

    def _avg(cases_list, field):
        if not cases_list:
            return 0
        return sum(c.get(field, 0) for c in cases_list) / len(cases_list)

    if common_success:
        a_common = [a_cases[n] for n in common_success]
        b_common = [b_cases[n] for n in common_success]
        avg_tokens_a = _avg(a_common, "total_tokens")
        avg_tokens_b = _avg(b_common, "total_tokens")
        avg_elapsed_a = _avg(a_common, "elapsed_seconds")
        avg_elapsed_b = _avg(b_common, "elapsed_seconds")
    else:
        aa, ba = a["aggregates"], b["aggregates"]
        avg_tokens_a, avg_tokens_b = aa.get("avg_tokens", 0), ba.get("avg_tokens", 0)
        avg_elapsed_a, avg_elapsed_b = aa.get("avg_elapsed", 0), ba.get("avg_elapsed", 0)

    def _delta(old, new, lower_better=True):
        if old == 0:
            return {"pct": 0, "improved": False}
        pct = (new - old) / old * 100
        improved = (pct < 0) if lower_better else (pct > 0)
        return {"pct": round(pct, 1), "improved": improved}

    all_names = sorted(set(list(a_cases.keys()) + list(b_cases.keys())))
    per_case = []
    for name in all_names:
        ca = a_cases.get(name)
        cb = b_cases.get(name)
        per_case.append({
            "name": name,
            "a_success": ca["success"] if ca else None,
            "b_success": cb["success"] if cb else None,
            "a_tokens": ca["total_tokens"] if ca else 0,
            "b_tokens": cb["total_tokens"] if cb else 0,
            "a_elapsed": ca["elapsed_seconds"] if ca else 0,
            "b_elapsed": cb["elapsed_seconds"] if cb else 0,
            "token_delta": _delta(ca["total_tokens"], cb["total_tokens"]) if ca and cb else None,
            "elapsed_delta": _delta(ca["elapsed_seconds"], cb["elapsed_seconds"]) if ca and cb else None,
        })

    return {
        "tag_a": tag_a,
        "tag_b": tag_b,
        "a_timestamp": a.get("timestamp", ""),
        "b_timestamp": b.get("timestamp", ""),
        "a_git": a.get("git_commit", ""),
        "b_git": b.get("git_commit", ""),
        "common_success": common_success,
        "aggregates": {
            "completion_rate": {
                "a": a["aggregates"].get("completion_rate", 0),
                "b": b["aggregates"].get("completion_rate", 0),
                "delta": _delta(a["aggregates"].get("completion_rate", 0),
                                b["aggregates"].get("completion_rate", 0), False),
            },
            "avg_tokens": {
                "a": avg_tokens_a, "b": avg_tokens_b,
                "delta": _delta(avg_tokens_a, avg_tokens_b),
                "label": "共同用例" if common_success else "成功用例",
            },
            "avg_elapsed": {
                "a": avg_elapsed_a, "b": avg_elapsed_b,
                "delta": _delta(avg_elapsed_a, avg_elapsed_b),
                "label": "共同用例" if common_success else "成功用例",
            },
            "total_cost": {
                "a": a["aggregates"].get("total_cost_usd", 0),
                "b": b["aggregates"].get("total_cost_usd", 0),
                "delta": _delta(a["aggregates"].get("total_cost_usd", 0),
                                b["aggregates"].get("total_cost_usd", 0)),
            },
        },
        "per_case": per_case,
    }


# ── POST /benchmark/run ──

@router.post("/benchmark/run")
async def start_benchmark_run(
    tag: str = Query(...),
    cases: str = Query(""),
    description: str = Query(""),
    critique: bool = Query(False),
    timeout: int = Query(600),
    repeat: int = Query(1),
    force: bool = Query(False),
    workers: int = Query(1),
):
    """启动 benchmark，立即返回 {tag, status}，进度通过 GET /live/{tag} 订阅"""
    _validate_tag(tag)
    workers = max(1, workers)
    existing = os.path.join(RESULTS_DIR, f"{tag}.json")
    if os.path.exists(existing) and not force:
        return JSONResponse(
            status_code=409,
            content={"error": f"标签 '{tag}' 已存在", "tags": _list_tags()},
        )
    # 防止同一 tag 并发发起（用 O_CREAT|O_EXCL 原子创建防 TOCTOU 竞态）
    running_file = os.path.join(RUNNING_DIR, f"{tag}.json")
    try:
        fd = os.open(running_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError:
        return JSONResponse(
            status_code=409,
            content={"error": f"标签 '{tag}' 正在运行中"},
        )

    # 在主线程中先创建 running 文件，确保 SSE 订阅时文件已存在
    from scripts.benchmark_lib import BenchmarkLiveWriter
    from scripts.benchmark import BENCHMARK_CASES, CORE_CASES
    all_cases = list(BENCHMARK_CASES) + _load_custom_cases()
    custom_core = [c["name"] for c in _load_custom_cases() if c.get("is_core")]
    all_core = list(CORE_CASES) + custom_core
    case_list = [c.strip() for c in cases.split(",") if c.strip()] or None
    if case_list:
        selected = [c for c in all_cases if c["name"] in case_list]
    else:
        selected = [c for c in all_cases if c["name"] in all_core]

    writer = BenchmarkLiveWriter(tag)
    writer.start(total_cases=len(selected), cases=[c["name"] for c in selected],
                 description=description)

    stop_event = threading.Event()
    with _stop_events_lock:
        _stop_events[tag] = stop_event

    def _run_in_thread():
        try:
            import time
            from scripts.benchmark_lib import BenchmarkRun
            from scripts.benchmark import (
                _run_single_case, _run_repeated_case,
                _run_cases_parallel,
                _get_git_info, _collect_environment,
                _print_summary, _save_result,
            )

            writer.push({"type": "run_start", "tag": tag,
                         "total_cases": len(selected), "cases": [c["name"] for c in selected]})

            git_commit, git_dirty = _get_git_info()
            env_info = _collect_environment()
            run = BenchmarkRun(
                tag=tag,
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
                git_commit=git_commit,
                git_dirty=git_dirty,
                description=description,
                critique_enabled=critique,
                environment=env_info,
            )

            total_start = time.time()
            if workers > 1:
                _run_cases_parallel(
                    selected, run=run, writer=writer, tag=tag,
                    no_critique=not critique, timeout=timeout,
                    repeat=repeat, workers=workers,
                    stop_event=stop_event,
                )
            else:
                def _make_progress_cb(case_name):
                    def cb(event_info):
                        writer.push({"type": "case_event", "case": case_name, **event_info})
                    return cb

                for i, case in enumerate(selected):
                    if stop_event.is_set():
                        writer.push({"type": "run_interrupted", "tag": tag,
                                     "message": "用户手动停止", "completed": i})
                        break
                    writer.push({"type": "case_start", "tag": tag, "case": case["name"],
                                 "index": i, "total": len(selected)})
                    if repeat == 1:
                        cr = _run_single_case(case, no_critique=not critique,
                                              timeout=timeout, on_progress=_make_progress_cb(case["name"]),
                                              use_alarm=False)
                    else:
                        cr = _run_repeated_case(
                            case, repeat=repeat, no_critique=not critique,
                            timeout=timeout, on_progress=_make_progress_cb(case["name"]),
                            use_alarm=False,
                        )
                    run.cases.append(cr)
                    writer.push({"type": "case_done", "tag": tag, "case": case["name"],
                                 "success": cr.success, "tokens": cr.total_tokens,
                                 "elapsed": cr.elapsed_seconds,
                                 "index": i, "completed": i + 1, "total": len(selected)})

            run.total_elapsed = round(time.time() - total_start, 1)
            _print_summary(run)
            _save_result(run)
            # run_complete 在 save 成功后推送，避免保存失败时发出错误的成功信号
            writer.push({"type": "run_complete", "tag": tag, "success": True,
                         "completion_rate": run.completion_rate,
                         "total_elapsed": run.total_elapsed,
                         "case_count": len(run.cases)})
        except Exception as e:
            writer.push({"type": "run_error", "tag": tag, "error": str(e)})
        finally:
            with _stop_events_lock:
                _stop_events.pop(tag, None)
            # live_mode=True：延迟 2s 等 SSE 端（0.5s 轮询）读取到终态事件再删文件
            writer.finish(delay=2.0)

    threading.Thread(target=_run_in_thread, daemon=True).start()
    return {"tag": tag, "status": "started"}


# ── POST /benchmark/runs/{tag}/stop ──

@router.post("/benchmark/runs/{tag}/stop")
async def stop_benchmark_run(tag: str):
    """停止正在运行的 benchmark（当前用例完成后生效）"""
    _validate_tag(tag)
    with _stop_events_lock:
        event = _stop_events.get(tag)
    if not event:
        return JSONResponse(
            status_code=404,
            content={"error": f"标签 '{tag}' 未在运行中"},
        )
    event.set()
    return {"success": True, "message": f"已发送停止信号，'{tag}' 将在当前用例完成后停止"}


# ── DELETE /benchmark/runs/{tag} ──

@router.delete("/benchmark/runs/{tag}")
async def delete_benchmark_run(tag: str):
    _validate_tag(tag)
    deleted = []
    for dir_path, ext in [(RESULTS_DIR, ".json"), (REPORT_DIR, ".md")]:
        path = os.path.join(dir_path, f"{tag}{ext}")
        if os.path.exists(path):
            os.remove(path)
            deleted.append(path)
    if not deleted:
        return JSONResponse(status_code=404, content={"error": f"未找到: {tag}"})
    return {"deleted": deleted, "tag": tag}
