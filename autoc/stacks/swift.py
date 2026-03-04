"""Swift 技术栈适配器"""
import os
import re

from autoc.stacks import ProjectContext, StackAdapter


class SwiftAdapter(StackAdapter):
    @staticmethod
    def detect(workspace_dir: str) -> str | None:
        p = os.path.join(workspace_dir, "Package.swift")
        return p if os.path.isfile(p) else None

    @staticmethod
    def priority() -> int:
        return 80

    def parse(self, manifest_path: str, workspace_dir: str) -> ProjectContext:
        ctx = ProjectContext(
            language="Swift",
            manifest_file="Package.swift",
            install_command="swift build",
            build_command="swift build",
            test_command="swift test",
        )
        if not manifest_path:
            manifest_path = os.path.join(workspace_dir, "Package.swift")
        try:
            with open(manifest_path, encoding="utf-8") as f:
                content = f.read()
            deps = re.findall(r'\.package\s*\(\s*url:\s*"(.+?)"', content)
            ctx.dependencies = [d.split("/")[-1].replace(".git", "") for d in deps]
            if any("Vapor" in d for d in ctx.dependencies):
                ctx.framework = "Vapor"
                ctx.project_type = "web_backend"
                ctx.default_port = 8080
                ctx.start_command = "swift run"
        except OSError:
            pass
        return ctx

    @staticmethod
    def hidden_dirs() -> set[str]:
        return {".build", ".swiftpm"}

    @staticmethod
    def noread_files() -> set[str]:
        return {"Package.resolved"}

    @staticmethod
    def config_files() -> set[str]:
        return {"Package.swift"}

    @staticmethod
    def coding_guidelines() -> str:
        return "## Swift 编码规范\n- 使用 Swift Package Manager 管理依赖\n- 遵循 Swift API Design Guidelines\n"

    @staticmethod
    def testing_guidelines() -> str:
        return "## Swift 测试要求\n- 使用 `swift test` 运行测试\n- 使用 XCTest 框架\n"

    @staticmethod
    def complexity_indicators() -> dict[str, list[str]]:
        return {"complex": [], "medium": ["Vapor"]}
