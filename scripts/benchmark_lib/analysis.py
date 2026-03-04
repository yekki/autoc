"""benchmark_lib.analysis — 只读分析命令（趋势、对比、历史）。

包含：
  - show_trend     历史趋势展示
  - compare_runs   两次运行对比
  - show_history   历史列表

辅助函数（模块私有）:
  - _list_tags, _load_result, _load_result_silent
  - _fmt_delta, _print_summary
  - _export_comparison_md, _check_data_integrity
"""
from __future__ import annotations

import json
import os
import sys
import time

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .models import BenchmarkRun, SCHEMA_VERSION

_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RESULTS_DIR = os.path.join(_project_root, "benchmarks", "results")
REPORT_DIR = os.path.join(_project_root, "benchmarks", "reports")

console = Console()


# ────────────────── 工具函数 ──────────────────

def _list_tags() -> list[str]:
    if not os.path.isdir(RESULTS_DIR):
        return []
    return sorted(
        f.replace(".json", "")
        for f in os.listdir(RESULTS_DIR)
        if f.endswith(".json")
    )


def _load_result(tag: str) -> dict:
    path = os.path.join(RESULTS_DIR, f"{tag}.json")
    if not os.path.exists(path):
        console.print(f"[red]未找到结果: {tag}[/red]")
        console.print(f"[dim]可用标签: {', '.join(_list_tags())}[/dim]")
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _load_result_silent(tag: str) -> dict | None:
    path = os.path.join(RESULTS_DIR, f"{tag}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _find_previous_tag(current_tag: str) -> str | None:
    """找到当前 tag 之前的最近一次结果"""
    tags = _list_tags()
    tags = [t for t in tags if t != current_tag]
    if not tags:
        return None
    results = []
    for t in tags:
        data = _load_result_silent(t)
        if data:
            results.append((data.get("timestamp", ""), t))
    if not results:
        return None
    results.sort(reverse=True)
    return results[0][1]


def _fmt_delta(old: float, new: float, unit: str = "", lower_is_better: bool = True) -> str:
    """格式化变化量，带颜色和箭头"""
    if old == 0:
        return f"{new}{unit}"
    delta = new - old
    pct = delta / old * 100
    if abs(pct) < 1:
        return f"{new}{unit} (≈)"
    improved = (delta < 0) if lower_is_better else (delta > 0)
    color = "green" if improved else "red"
    arrow = "↓" if delta < 0 else "↑"
    return f"[{color}]{new}{unit} ({pct:+.0f}% {arrow})[/{color}]"


def _print_summary(run: BenchmarkRun):
    """打印单次运行的汇总"""
    console.print(f"\n{'═' * 70}")
    console.print(f"[bold]📊 Benchmark 汇总: {run.tag}[/bold]")
    console.print(f"{'─' * 70}")

    t = Table(show_header=True, header_style="bold", width=78)
    t.add_column("用例", width=14)
    t.add_column("复杂度", width=8, justify="center")
    t.add_column("结果", width=6, justify="center")
    t.add_column("Token", width=10, justify="right")
    t.add_column("耗时", width=8, justify="right")
    t.add_column("迭代", width=6, justify="right")
    t.add_column("任务", width=8, justify="center")
    t.add_column("质量", width=8, justify="center")

    for c in run.cases:
        icon = "[green]✓[/green]" if c.success else "[red]✗[/red]"
        if c.quality_checks:
            qv = f"{'[green]✓[/green]' if c.quality_verified else '[yellow]✗[/yellow]'} {getattr(c, 'quality_level', 'L0')}"
        else:
            qv = "—"
        repeat_tag = f" ×{c.repeat_count}" if c.repeat_count > 1 else ""
        t.add_row(
            c.case_name + repeat_tag, c.complexity, icon,
            f"{c.total_tokens:,}", f"{c.elapsed_seconds:.0f}s",
            str(c.dev_iterations), f"{c.tasks_verified}/{c.tasks_total}", qv,
        )

    console.print(t)

    passed = sum(1 for c in run.cases if c.success)
    total = len(run.cases)
    rate_style = "green" if passed == total else ("yellow" if passed > 0 else "red")

    agg = Table(show_header=False, box=None, padding=(0, 2))
    agg.add_column("k", style="dim", width=20)
    agg.add_column("v")
    agg.add_row("完成率", f"[{rate_style}]{passed}/{total} ({run.completion_rate:.0%})[/{rate_style}]")
    agg.add_row("平均 Token（成功）", f"{run.avg_tokens:,.0f}")
    agg.add_row("平均耗时（成功）", f"{run.avg_elapsed:.0f}s")
    agg.add_row("平均迭代（成功）", f"{run.avg_iterations:.1f}")
    agg.add_row("平均 P:C（含缓存）", f"{run.avg_pc_ratio:.0f}:1")
    agg.add_row("平均非缓存 P:C", f"{run.avg_nc_pc_ratio:.1f}:1")
    agg.add_row("平均缓存命中率", f"{run.avg_cache_hit_rate:.0%}")
    agg.add_row("平均 API 调用", f"{run.avg_call_count:.0f}")
    qv_passed = sum(1 for c in run.cases if c.quality_verified)
    qv_total = sum(1 for c in run.cases if c.quality_checks)
    if qv_total > 0:
        qv_style = "green" if qv_passed == qv_total else "yellow"
        agg.add_row("质量验证", f"[{qv_style}]{qv_passed}/{qv_total}[/{qv_style}]")
    agg.add_row("总 Token", f"{run.total_tokens:,}")
    agg.add_row("总耗时", f"{run.total_elapsed:.0f}s")
    agg.add_row("预估费用", f"${run.total_cost_usd:.4f}")
    console.print(agg)
    console.print(f"{'═' * 70}")


def _check_data_integrity(data: dict) -> str:
    """检查结果数据完整性，返回标记：✓/⚠/✗

    schema_version < SCHEMA_VERSION 的旧数据自动降级为 ⚠
    """
    cases = data.get("cases", [])
    if not cases:
        return "[red]✗[/red]"

    version = data.get("schema_version", 1)
    if version < SCHEMA_VERSION:
        return "[yellow]⚠[/yellow]"

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
        return "[green]✓[/green]"
    if issues <= 2:
        return "[yellow]⚠[/yellow]"
    return "[red]✗[/red]"


def _export_comparison_md(tag_a: str, tag_b: str, a: dict, b: dict):
    """导出 Markdown 对比报告（只比共同成功用例）"""
    os.makedirs(REPORT_DIR, exist_ok=True)
    filename = f"{tag_a}_vs_{tag_b}.md"
    path = os.path.join(REPORT_DIR, filename)

    a_cases = {c["case_name"]: c for c in a["cases"]}
    b_cases = {c["case_name"]: c for c in b["cases"]}
    common_success = [
        name for name in a_cases
        if name in b_cases and a_cases[name].get("success") and b_cases[name].get("success")
    ]

    aa = a["aggregates"]
    ba = b["aggregates"]

    def delta_str(old, new, lower_better=True):
        if old == 0:
            return str(new)
        pct = (new - old) / old * 100
        arrow = "↓" if pct < 0 else "↑"
        better = (pct < 0) if lower_better else (pct > 0)
        marker = "✅" if better else "⚠️"
        return f"{new} ({pct:+.0f}% {arrow}) {marker}"

    lines = [
        f"# Benchmark 对比: {tag_a} → {tag_b}",
        "",
        f"> 基线: {tag_a} ({a['timestamp'][:10]}, git {a['git_commit']})",
        f"> 当前: {tag_b} ({b['timestamp'][:10]}, git {b['git_commit']})",
    ]
    if common_success:
        lines.append(f"> 共同成功用例: {', '.join(common_success)}")
    lines.extend([
        "", "## 聚合指标", "",
        "| 指标 | 基线 | 当前 | 变化 |",
        "|------|:----:|:----:|------|",
        f"| 完成率 | {aa['completion_rate']:.0%} | {ba['completion_rate']:.0%} | {delta_str(aa['completion_rate'], ba['completion_rate'], False)} |",
    ])

    if common_success:
        prev_common = [a_cases[n] for n in common_success]
        curr_common = [b_cases[n] for n in common_success]
        avg_tok_a = sum(c["total_tokens"] for c in prev_common) / len(prev_common)
        avg_tok_b = sum(c["total_tokens"] for c in curr_common) / len(curr_common)
        avg_time_a = sum(c["elapsed_seconds"] for c in prev_common) / len(prev_common)
        avg_time_b = sum(c["elapsed_seconds"] for c in curr_common) / len(curr_common)
        lines.append(f"| 平均 Token（共同用例） | {avg_tok_a:,.0f} | {avg_tok_b:,.0f} | {delta_str(avg_tok_a, avg_tok_b)} |")
        lines.append(f"| 平均耗时（共同用例） | {avg_time_a:.0f}s | {avg_time_b:.0f}s | {delta_str(avg_time_a, avg_time_b)}s |")
    else:
        lines.append(f"| 平均 Token | {aa['avg_tokens']:,.0f} | {ba['avg_tokens']:,.0f} | {delta_str(aa['avg_tokens'], ba['avg_tokens'])} |")
        lines.append(f"| 平均耗时 | {aa['avg_elapsed']:.0f}s | {ba['avg_elapsed']:.0f}s | {delta_str(aa['avg_elapsed'], ba['avg_elapsed'])}s |")

    lines.append(f"| 预估费用 | ${aa['total_cost_usd']:.4f} | ${ba['total_cost_usd']:.4f} | {delta_str(aa['total_cost_usd'], ba['total_cost_usd'])} |")
    lines.extend(["", "## 逐用例对比", "", "| 用例 | 基线 | 当前 | Token 变化 | 耗时变化 |", "|------|:----:|:----:|-----------|---------|"])

    for name in sorted(set(list(a_cases.keys()) + list(b_cases.keys()))):
        ca = a_cases.get(name, {})
        cb = b_cases.get(name, {})
        ra = "✅" if ca.get("success") else "❌" if ca else "—"
        rb = "✅" if cb.get("success") else "❌" if cb else "—"
        tok_a = ca.get("total_tokens", 0)
        tok_b = cb.get("total_tokens", 0)
        time_a = ca.get("elapsed_seconds", 0)
        time_b = cb.get("elapsed_seconds", 0)
        lines.append(
            f"| {name} | {ra} | {rb} | "
            f"{delta_str(tok_a, tok_b) if tok_a else str(tok_b)} | "
            f"{delta_str(time_a, time_b) if time_a else f'{time_b:.0f}'}s |"
        )

    lines.extend(["", f"*生成时间: {time.strftime('%Y-%m-%d %H:%M')}*", ""])
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    console.print(f"\n[dim]报告已导出: {path}[/dim]")


# ────────────────── 公开命令 ──────────────────

def show_trend(case_filter: str | None = None, metric: str = "tokens", export: bool = False):
    """显示指定用例的历史趋势（Token / 耗时 / 费用）

    metric: "tokens" | "elapsed" | "cost"
    """
    tags = _list_tags()
    if not tags:
        console.print("[yellow]暂无历史结果，请先运行 benchmark。[/yellow]")
        return

    runs: list[tuple[str, str, dict]] = []
    for t in tags:
        d = _load_result_silent(t)
        if d:
            runs.append((d.get("timestamp", ""), t, d))
    runs.sort(key=lambda x: x[0])

    all_cases: set[str] = set()
    for _, _, d in runs:
        for c in d.get("cases", []):
            all_cases.add(c["case_name"])
    cases_to_show = sorted(all_cases)
    if case_filter:
        cases_to_show = [c for c in cases_to_show if case_filter in c]
    if not cases_to_show:
        console.print(f"[yellow]未找到匹配用例: {case_filter}[/yellow]")
        return

    metric_label = {"tokens": "Token", "elapsed": "耗时(s)", "cost": "费用(USD)"}
    label = metric_label.get(metric, "Token")

    console.print(f"\n[bold]📈 历史趋势 — {label}[/bold]")
    if case_filter:
        console.print(f"[dim]用例过滤: {case_filter}[/dim]")

    report_lines: list[str] = [f"# Benchmark 历史趋势 — {label}", ""]

    for case_name in cases_to_show:
        data_points: list[tuple[str, str, float]] = []
        for ts, tag, d in runs:
            for c in d.get("cases", []):
                if c["case_name"] == case_name and c.get("success"):
                    if metric == "tokens":
                        val = c.get("total_tokens", 0)
                    elif metric == "elapsed":
                        val = c.get("elapsed_seconds", 0)
                    else:
                        agg = d.get("aggregates", {})
                        n = max(1, len(d.get("cases", [])))
                        val = agg.get("total_cost_usd", 0) / n
                    data_points.append((ts[:10], tag, val))

        if not data_points:
            continue

        console.print(f"\n  [bold cyan]{case_name}[/bold cyan]")
        report_lines.append(f"## {case_name}")
        report_lines.append("")
        report_lines.append(f"| # | 时间 | 标签 | {label} | 变化 |")
        report_lines.append(f"|---|------|------|------:|------|")

        max_val = max(v for _, _, v in data_points) or 1
        tbl = Table(show_header=True, header_style="bold", width=72, padding=(0, 1))
        tbl.add_column("#", width=3, justify="right")
        tbl.add_column("时间", width=10)
        tbl.add_column("标签", width=22)
        tbl.add_column(label, width=12, justify="right")
        tbl.add_column("趋势", width=20)

        prev_val: float | None = None
        for i, (ts, tag, val) in enumerate(data_points, 1):
            bar_len = max(1, int(val / max_val * 18))
            bar = "█" * bar_len
            if prev_val is not None and prev_val > 0:
                pct = (val - prev_val) / prev_val * 100
                delta_str = f"{pct:+.0f}%"
                lower_better = metric in ("tokens", "elapsed", "cost")
                improved = (pct < 0) if lower_better else (pct > 0)
                color = "green" if improved else ("red" if abs(pct) > 5 else "dim")
                bar_color = "green" if improved else ("red" if abs(pct) > 5 else "yellow")
            else:
                delta_str = "—"
                color = "dim"
                bar_color = "cyan"

            if metric == "tokens":
                val_str = f"{val:,.0f}"
            elif metric == "elapsed":
                val_str = f"{val:.0f}s"
            else:
                val_str = f"${val:.4f}"

            tbl.add_row(
                str(i), ts, tag[:22],
                f"[{color}]{val_str}[/{color}]",
                f"[{bar_color}]{bar}[/{bar_color}] [{color}]{delta_str}[/{color}]",
            )
            report_lines.append(f"| {i} | {ts} | {tag} | {val_str} | {delta_str} |")
            prev_val = val

        console.print(tbl)
        report_lines.append("")

        if len(data_points) > 1:
            first_val = data_points[0][2]
            last_val = data_points[-1][2]
            if first_val > 0:
                total_pct = (last_val - first_val) / first_val * 100
                lower_better = metric in ("tokens", "elapsed", "cost")
                improved = (total_pct < 0) if lower_better else (total_pct > 0)
                summary_color = "green" if improved else "red"
                console.print(
                    f"  [dim]{case_name} 首次 → 最近: "
                    f"[{summary_color}]{total_pct:+.0f}%[/{summary_color}][/dim]"
                )

    if export:
        os.makedirs(REPORT_DIR, exist_ok=True)
        suffix = f"_{case_filter}" if case_filter else ""
        path = os.path.join(REPORT_DIR, f"trend_{metric}{suffix}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(report_lines))
        console.print(f"\n[dim]趋势报告已导出: {path}[/dim]")


def compare_runs(tag_a: str, tag_b: str, export: bool = False):
    """对比两次 benchmark 结果（只对比共同成功用例）"""
    a = _load_result(tag_a)
    b = _load_result(tag_b)

    console.print(Panel(
        f"[bold]AutoC Benchmark 对比[/bold]\n"
        f"基线: {tag_a} ({a['timestamp'][:10]}, {a['git_commit']})\n"
        f"当前: {tag_b} ({b['timestamp'][:10]}, {b['git_commit']})",
        style="cyan", width=70,
    ))

    a_cases = {c["case_name"]: c for c in a["cases"]}
    b_cases = {c["case_name"]: c for c in b["cases"]}
    common_success = [
        name for name in a_cases
        if name in b_cases and a_cases[name].get("success") and b_cases[name].get("success")
    ]

    if common_success:
        console.print(f"[dim]共同成功用例: {', '.join(common_success)}[/dim]")
        prev_common = [a_cases[n] for n in common_success]
        curr_common = [b_cases[n] for n in common_success]
        avg_tok_a = sum(c["total_tokens"] for c in prev_common) / len(prev_common)
        avg_tok_b = sum(c["total_tokens"] for c in curr_common) / len(curr_common)
        avg_time_a = sum(c["elapsed_seconds"] for c in prev_common) / len(prev_common)
        avg_time_b = sum(c["elapsed_seconds"] for c in curr_common) / len(curr_common)
    else:
        aa_d = a["aggregates"]
        ba_d = b["aggregates"]
        avg_tok_a, avg_tok_b = aa_d["avg_tokens"], ba_d["avg_tokens"]
        avg_time_a, avg_time_b = aa_d["avg_elapsed"], ba_d["avg_elapsed"]

    aa = a["aggregates"]
    ba = b["aggregates"]

    agg_tbl = Table(show_header=True, header_style="bold", width=70)
    agg_tbl.add_column("指标", width=22)
    agg_tbl.add_column(f"{tag_a}", width=14, justify="right")
    agg_tbl.add_column(f"{tag_b}", width=14, justify="right")
    agg_tbl.add_column("变化", width=18)

    agg_tbl.add_row("完成率", f"{aa['completion_rate']:.0%}", f"{ba['completion_rate']:.0%}", _fmt_delta(aa['completion_rate'], ba['completion_rate'], "", lower_is_better=False))
    tok_label = "平均 Token（共同）" if common_success else "平均 Token（成功）"
    agg_tbl.add_row(tok_label, f"{avg_tok_a:,.0f}", f"{avg_tok_b:,.0f}", _fmt_delta(avg_tok_a, avg_tok_b))
    time_label = "平均耗时（共同）" if common_success else "平均耗时（成功）"
    agg_tbl.add_row(time_label, f"{avg_time_a:.0f}s", f"{avg_time_b:.0f}s", _fmt_delta(avg_time_a, avg_time_b, "s"))
    agg_tbl.add_row("总 Token", f"{aa['total_tokens']:,}", f"{ba['total_tokens']:,}", _fmt_delta(aa['total_tokens'], ba['total_tokens']))
    agg_tbl.add_row("预估费用", f"${aa['total_cost_usd']:.4f}", f"${ba['total_cost_usd']:.4f}", _fmt_delta(aa['total_cost_usd'], ba['total_cost_usd']))
    console.print(agg_tbl)

    console.print(f"\n[bold]逐用例对比[/bold]")
    all_names = sorted(set(list(a_cases.keys()) + list(b_cases.keys())))
    ct = Table(show_header=True, header_style="bold", width=70)
    ct.add_column("用例", width=14)
    ct.add_column(f"结果 ({tag_a})", width=8, justify="center")
    ct.add_column(f"结果 ({tag_b})", width=8, justify="center")
    ct.add_column("Token 变化", width=18)
    ct.add_column("耗时变化", width=16)

    for name in all_names:
        ca = a_cases.get(name)
        cb = b_cases.get(name)
        icon_a = "[green]✓[/green]" if ca and ca["success"] else "[red]✗[/red]" if ca else "[dim]—[/dim]"
        icon_b = "[green]✓[/green]" if cb and cb["success"] else "[red]✗[/red]" if cb else "[dim]—[/dim]"
        tok_a = ca["total_tokens"] if ca else 0
        tok_b = cb["total_tokens"] if cb else 0
        time_a = ca["elapsed_seconds"] if ca else 0
        time_b = cb["elapsed_seconds"] if cb else 0
        ct.add_row(name, icon_a, icon_b, _fmt_delta(tok_a, tok_b) if tok_a > 0 else f"{tok_b:,}", _fmt_delta(time_a, time_b, "s") if time_a > 0 else f"{time_b:.0f}s")

    console.print(ct)
    if export:
        _export_comparison_md(tag_a, tag_b, a, b)


def show_history():
    """显示所有历史运行"""
    tags = _list_tags()
    if not tags:
        console.print("[yellow]还没有 benchmark 结果。运行 `python scripts/benchmark.py run --tag baseline` 开始。[/yellow]")
        return

    console.print(Panel("[bold]AutoC Benchmark 历史[/bold]", style="cyan", width=70))

    t = Table(show_header=True, header_style="bold", width=78)
    t.add_column("标签", width=20)
    t.add_column("日期", width=12)
    t.add_column("Git", width=10)
    t.add_column("完成率", width=8, justify="center")
    t.add_column("平均 Token", width=12, justify="right")
    t.add_column("平均耗时", width=10, justify="right")
    t.add_column("完整", width=4, justify="center")

    for tag in tags:
        data = _load_result(tag)
        agg_data = data.get("aggregates", {})
        integrity = _check_data_integrity(data)
        t.add_row(
            tag, data.get("timestamp", "")[:10], data.get("git_commit", "?"),
            f"{agg_data.get('completion_rate', 0):.0%}",
            f"{agg_data.get('avg_tokens', 0):,.0f}",
            f"{agg_data.get('avg_elapsed', 0):.0f}s",
            integrity,
        )

    console.print(t)
    console.print(f"\n[dim]对比命令: python scripts/benchmark.py compare <tag_a> <tag_b>[/dim]")
    console.print(f"[dim]完整性: ✓=数据完整 ⚠=有异常（旧版可能缺失字段） ✗=数据不可信[/dim]")
