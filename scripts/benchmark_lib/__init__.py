"""benchmark_lib — benchmark.py 拆出的子模块包。

公开接口：
  from benchmark_lib.models import CaseResult, BenchmarkRun, BenchmarkLiveWriter
  from benchmark_lib.analysis import show_trend, compare_runs, show_history
"""
from .models import CaseResult, BenchmarkRun, BenchmarkLiveWriter, SCHEMA_VERSION
from .analysis import show_trend, compare_runs, show_history

__all__ = [
    "CaseResult", "BenchmarkRun", "BenchmarkLiveWriter", "SCHEMA_VERSION",
    "show_trend", "compare_runs", "show_history",
]
