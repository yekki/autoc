"""ConsolePresenter — 美化控制台输出

从 Orchestrator 抽取的展示逻辑，负责所有 Rich 控制台输出。
Orchestrator 通过依赖注入使用 Presenter，实现关注点分离。

支持 compact 模式：减少装饰和空行，适合 CI/CD 或日志收集场景。
"""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

# 阶段图标映射（用于 print_phase 的视觉增强）
_PHASE_ICONS: dict[str, str] = {
    "Helper": "📋",
    "Developer": "💻",
    "Tester": "🧪",
    "Fix": "🔧",
    "Quality": "✨",
    "Refine": "🔍",
    "Preview": "👁️",
}


class ConsolePresenter:
    """控制台美化输出

    Args:
        compact: 紧凑模式，减少装饰性输出（适合 CI 或日志场景）
    """

    def __init__(self, compact: bool = False):
        self._compact = compact

    def print_header(self, requirement: str, features: list[str]):
        """打印执行头部信息"""
        if self._compact:
            feat_str = f"  [{', '.join(features)}]" if features else ""
            console.print(f"[bold bright_blue]▶ AutoC[/bold bright_blue]{feat_str}")
            console.print(f"  [dim]{requirement[:120]}{'…' if len(requirement) > 120 else ''}[/dim]")
            return

        features_str = f"\n[dim]已启用: {', '.join(features)}[/dim]" if features else ""
        console.print()
        console.print(
            Panel(
                f"[bold]🚀 AutoC - 全自动开发系统[/bold]\n\n"
                f"[dim]需求:[/dim] {requirement[:200]}{'...' if len(requirement) > 200 else ''}"
                f"{features_str}",
                border_style="bright_blue",
                expand=False,
            )
        )
        console.print()

    def print_phase(self, phase: str, title: str, color: str):
        """打印阶段分隔线"""
        icon = _PHASE_ICONS.get(phase, "▸")

        if self._compact:
            console.print(f"  [{color}]{icon} {phase}: {title}[/{color}]")
            return

        console.print()
        console.rule(
            f"[bold {color}]{icon} {phase}: {title}[/bold {color}]",
            characters="─",
        )
        console.print()

    def print_step(self, message: str, style: str = "dim"):
        """打印阶段内的子步骤信息（新增）"""
        prefix = "  •" if self._compact else "    •"
        console.print(f"{prefix} [{style}]{message}[/{style}]")

    def print_plan(self, plan):
        """打印项目计划表格"""
        if self._compact:
            console.print(f"  [cyan]📋 {plan.project_name}[/cyan] — {len(plan.tasks)} 个任务")
            for task in plan.tasks:
                files_hint = f" ({len(task.files)} 文件)" if task.files else ""
                console.print(f"    [dim]{task.id}[/dim] {task.title}{files_hint}")
            return

        table = Table(title=f"📋 项目计划: {plan.project_name}", expand=False)
        table.add_column("ID", style="cyan", width=10)
        table.add_column("任务", style="white", width=40)
        table.add_column("优先级", justify="center", width=8)
        table.add_column("验证", justify="center", width=6)
        table.add_column("文件", style="dim", width=30)

        priority_map = {0: "[red]高[/red]", 1: "[yellow]中[/yellow]", 2: "[green]低[/green]"}

        for task in plan.tasks:
            files_str = ", ".join(task.files[:3])
            if len(task.files) > 3:
                files_str += f" +{len(task.files) - 3}"
            verify_count = str(len(task.verification_steps)) if task.verification_steps else "-"
            table.add_row(
                task.id,
                task.title,
                priority_map.get(task.priority, "中"),
                verify_count,
                files_str,
            )

        console.print(table)

        if plan.tech_stack:
            console.print(f"\n  🛠️  技术栈: {', '.join(plan.tech_stack)}")
        if plan.architecture:
            console.print(f"  🏗️  架构: {plan.architecture[:200]}")
        if plan.user_stories:
            console.print(f"  📖 用户故事: {len(plan.user_stories)} 条")
            for story in plan.user_stories[:3]:
                console.print(f"      - {story[:80]}")
        if plan.data_models:
            console.print(f"  💾 数据模型: {plan.data_models[:100]}...")
        if plan.api_design:
            console.print(f"  🔌 API 设计: {plan.api_design[:100]}...")
        console.print()

    def print_summary(self, result: dict, elapsed: float):
        """打印执行总结"""
        success = result["success"]

        if self._compact:
            icon = "✅" if success else "❌"
            t_done = result["tasks_completed"]
            t_total = result["tasks_total"]
            console.print(
                f"\n  {icon} 完成 {t_done}/{t_total} 任务 | "
                f"测试 {result['tests_passed']}/{result['tests_total']} | "
                f"Bug {result['bugs_open']} | "
                f"{elapsed:.1f}s | Token {result['total_tokens']}"
            )
            return

        console.print()

        status = "[bold green]✅ 成功[/bold green]" if success else "[bold red]❌ 未完全成功[/bold red]"

        req_line = ""
        if result.get("requirements_total", 0) > 0:
            req_line = (
                f"📑 需求: {result['requirements_completed']}/{result['requirements_total']} 完成\n"
            )

        summary_text = (
            f"状态: {status}\n\n"
            f"{req_line}"
            f"📋 任务: {result['tasks_completed']}/{result['tasks_total']} 完成\n"
            f"✅ 验证: {result.get('tasks_verified', 0)}/{result['tasks_total']} passes\n"
            f"🚫 阻塞: {result.get('tasks_blocked', 0)} 个\n"
            f"🧪 测试: {result['tests_passed']}/{result['tests_total']} 通过\n"
            f"🐛 Bug: {result['bugs_open']} 待修复\n"
            f"📁 文件: {len(result['files'])} 个\n"
            f"📦 Git: {result.get('git_commits', 0)} 个提交\n"
            f"⏱️  耗时: {elapsed:.1f}s\n"
            f"🔢 Token: {result['total_tokens']}\n"
            f"💾 缓存命中: {result.get('cache_hits', 0)} 次"
        )

        if result["files"]:
            summary_text += "\n\n📂 生成的文件:\n"
            for f in result["files"]:
                summary_text += f"  - {f}\n"

        console.print(
            Panel(
                summary_text,
                title="📊 执行总结",
                border_style="bright_blue",
                expand=False,
            )
        )
        console.print()
