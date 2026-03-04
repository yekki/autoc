"""benchmark_lib.models — 纯数据模型，无外部项目依赖。

包含：
  - _pid_alive          OS 进程存活检查
  - BenchmarkLiveWriter 渠道无关的实时运行状态写入器
  - SCHEMA_VERSION      数据格式版本号
  - CaseResult          单用例运行结果
  - BenchmarkRun        一次完整 benchmark 运行
"""
from __future__ import annotations

import json
import os
import threading as _threading
import time
from dataclasses import dataclass, field

# 默认 RUNNING_DIR（可在构造 BenchmarkLiveWriter 时覆盖）
_DEFAULT_RUNNING_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "benchmarks", "running",
)


def _pid_alive(pid: int) -> bool:
    """检查 PID 对应的进程是否存活（跨平台）"""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False
    except Exception:
        return False


class BenchmarkLiveWriter:
    """渠道无关的实时运行状态写入器。

    CLI 和 Web 触发的 benchmark 均写入 benchmarks/running/{tag}.json，
    Web 端通过 GET /benchmark/live/{tag} SSE 订阅，实现「CLI 跑 Web 看」。

    文件格式:
        {tag, started_at, pid, total_cases, cases, events: [...]}
    """

    def __init__(self, tag: str, running_dir: str | None = None):
        self.tag = tag
        self._path = os.path.join(running_dir or _DEFAULT_RUNNING_DIR, f"{tag}.json")
        self._lock = _threading.Lock()

    def start(self, total_cases: int, cases: list[str], **meta):
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        self._write({
            "tag": self.tag,
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "pid": os.getpid(),
            "total_cases": total_cases,
            "cases": cases,
            "events": [],
            **meta,
        })

    def push(self, event: dict):
        with self._lock:
            data = self._read()
            if data is not None:
                data["events"].append(event)
                self._write(data)

    def finish(self, delay: float = 2.0):
        """删除运行状态文件。

        delay: 删除前等待秒数，给 SSE 端留出读取终态事件的时间窗口。
        """
        if delay > 0:
            time.sleep(delay)
        try:
            if os.path.exists(self._path):
                os.remove(self._path)
        except Exception:
            pass

    def _read(self) -> dict | None:
        try:
            with open(self._path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def _write(self, data: dict):
        tmp = self._path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, default=str)
            os.replace(tmp, self._path)
        except Exception:
            pass


SCHEMA_VERSION = 3  # 数据格式版本：v1=初版 v2=+环境+效率 v3=+质量验证+分层


@dataclass
class CaseResult:
    case_name: str
    complexity: str
    success: bool = False
    tasks_completed: int = 0
    tasks_total: int = 0
    tasks_verified: int = 0
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    elapsed_seconds: float = 0.0
    dev_iterations: int = 0
    call_count: int = 0
    error_calls: int = 0
    exit_reason: str = ""
    files_generated: int = 0
    error: str | None = None
    # ── 瓶颈分析数据 ──
    agent_tokens: dict[str, int] = field(default_factory=dict)
    stage_timings: dict[str, float] = field(default_factory=dict)
    tool_calls: dict[str, int] = field(default_factory=dict)
    tool_errors: dict[str, int] = field(default_factory=dict)
    # ── 产出质量验证 ──
    quality_verified: bool = False
    quality_level: str = "L0"   # L0(未过L1)/L1/L2/L3，反映验证深度
    quality_checks: list[dict] = field(default_factory=list)
    # ── 多次运行数据（--repeat） ──
    repeat_runs: list[dict] = field(default_factory=list)
    repeat_count: int = 1

    @property
    def pc_ratio(self) -> float:
        """prompt:completion 比值（含缓存，反映上下文整体规模）"""
        if self.completion_tokens == 0:
            return 0.0
        return self.prompt_tokens / self.completion_tokens

    @property
    def nc_pc_ratio(self) -> float:
        """非缓存 prompt:completion 比值（排除缓存后的真实效率指标）"""
        if self.completion_tokens == 0:
            return 0.0
        non_cached = max(0, self.prompt_tokens - self.cached_tokens)
        return non_cached / self.completion_tokens

    @property
    def cache_hit_rate(self) -> float:
        """缓存命中率"""
        if self.prompt_tokens == 0:
            return 0.0
        return self.cached_tokens / self.prompt_tokens


@dataclass
class BenchmarkRun:
    tag: str
    timestamp: str = ""
    git_commit: str = ""
    git_dirty: bool = False
    description: str = ""
    critique_enabled: bool = False
    environment: dict = field(default_factory=dict)
    cases: list[CaseResult] = field(default_factory=list)
    total_elapsed: float = 0.0

    @property
    def completion_rate(self) -> float:
        if not self.cases:
            return 0.0
        return sum(1 for c in self.cases if c.success) / len(self.cases)

    @property
    def avg_tokens(self) -> float:
        completed = [c for c in self.cases if c.success]
        if not completed:
            return 0.0
        return sum(c.total_tokens for c in completed) / len(completed)

    @property
    def avg_elapsed(self) -> float:
        completed = [c for c in self.cases if c.success]
        if not completed:
            return 0.0
        return sum(c.elapsed_seconds for c in completed) / len(completed)

    @property
    def avg_iterations(self) -> float:
        completed = [c for c in self.cases if c.success]
        if not completed:
            return 0.0
        return sum(c.dev_iterations for c in completed) / len(completed)

    @property
    def total_tokens(self) -> int:
        return sum(c.total_tokens for c in self.cases)

    @property
    def total_cost_usd(self) -> float:
        """粗略估算（用 GLM-4.7 定价）"""
        prompt = sum(c.prompt_tokens for c in self.cases)
        completion = sum(c.completion_tokens for c in self.cases)
        cached = sum(c.cached_tokens for c in self.cases)
        non_cached_prompt = prompt - cached
        return (
            non_cached_prompt * 0.60 / 1_000_000
            + cached * 0.11 / 1_000_000
            + completion * 2.20 / 1_000_000
        )

    @property
    def avg_pc_ratio(self) -> float:
        completed = [c for c in self.cases if c.success and c.completion_tokens > 0]
        if not completed:
            return 0.0
        return sum(c.pc_ratio for c in completed) / len(completed)

    @property
    def avg_nc_pc_ratio(self) -> float:
        """平均非缓存 P:C 比值"""
        completed = [c for c in self.cases if c.success and c.completion_tokens > 0]
        if not completed:
            return 0.0
        return sum(c.nc_pc_ratio for c in completed) / len(completed)

    @property
    def avg_cache_hit_rate(self) -> float:
        completed = [c for c in self.cases if c.success and c.prompt_tokens > 0]
        if not completed:
            return 0.0
        return sum(c.cache_hit_rate for c in completed) / len(completed)

    @property
    def avg_call_count(self) -> float:
        completed = [c for c in self.cases if c.success]
        if not completed:
            return 0.0
        return sum(c.call_count for c in completed) / len(completed)
