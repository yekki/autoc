"""C# / .NET 技术栈适配器"""
import glob
import os
import re

from autoc.stacks import ProjectContext, StackAdapter


class DotnetAdapter(StackAdapter):
    @staticmethod
    def detect(workspace_dir: str) -> str | None:
        matches = glob.glob(os.path.join(workspace_dir, "*.csproj"))
        return matches[0] if matches else None

    @staticmethod
    def priority() -> int:
        return 70

    def parse(self, manifest_path: str, workspace_dir: str) -> ProjectContext:
        ctx = ProjectContext(
            language="C#",
            manifest_file=os.path.basename(manifest_path) if manifest_path else "",
            install_command="dotnet restore",
            build_command="dotnet build",
            test_command="dotnet test",
        )
        if not manifest_path:
            return ctx
        try:
            with open(manifest_path, encoding="utf-8") as f:
                content = f.read()
            refs = re.findall(r'Include="(.+?)"', content)
            ctx.dependencies = [r.split(",")[0] for r in refs[:20]]
            if any("Microsoft.AspNetCore" in r for r in refs):
                ctx.framework = "ASP.NET Core"
                ctx.project_type = "web_backend"
                ctx.default_port = 5000
                ctx.start_command = "dotnet run"
        except OSError:
            pass
        return ctx

    @staticmethod
    def hidden_dirs() -> set[str]:
        return {"bin", "obj", ".vs", "packages"}

    @staticmethod
    def noread_files() -> set[str]:
        return {"packages.lock.json"}

    @staticmethod
    def config_files() -> set[str]:
        return set()

    @staticmethod
    def coding_guidelines() -> str:
        return (
            "## C#/.NET 编码规范\n"
            "- 使用 NuGet 管理依赖，dotnet add package 添加\n"
            "- 遵循 C# 命名规范（PascalCase 方法名）\n"
        )

    @staticmethod
    def testing_guidelines() -> str:
        return (
            "## C#/.NET 测试要求\n"
            "- 使用 `dotnet test` 运行测试\n"
            "- 使用 xUnit 或 NUnit 框架\n"
        )

    @staticmethod
    def complexity_indicators() -> dict[str, list[str]]:
        return {"complex": [], "medium": ["ASP.NET", "Blazor"]}
