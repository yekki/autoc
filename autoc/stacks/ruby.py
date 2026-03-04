"""Ruby 技术栈适配器"""
import os
import re

from autoc.stacks import ProjectContext, StackAdapter


class RubyAdapter(StackAdapter):
    @staticmethod
    def detect(workspace_dir: str) -> str | None:
        p = os.path.join(workspace_dir, "Gemfile")
        return p if os.path.isfile(p) else None

    @staticmethod
    def priority() -> int:
        return 80

    def parse(self, manifest_path: str, workspace_dir: str) -> ProjectContext:
        ctx = ProjectContext(
            language="Ruby",
            manifest_file="Gemfile",
            install_command="bundle install",
            test_command="bundle exec rspec",
        )
        if not manifest_path:
            manifest_path = os.path.join(workspace_dir, "Gemfile")
        try:
            with open(manifest_path, encoding="utf-8") as f:
                for line in f:
                    m = re.match(r"gem\s+['\"](.+?)['\"]", line.strip())
                    if m:
                        ctx.dependencies.append(m.group(1))
            if "rails" in ctx.dependencies:
                ctx.framework = "Rails"
                ctx.project_type = "web_fullstack"
                ctx.default_port = 3000
                ctx.start_command = "bundle exec rails server"
            elif "sinatra" in ctx.dependencies:
                ctx.framework = "Sinatra"
                ctx.project_type = "web_backend"
                ctx.default_port = 4567
        except OSError:
            pass
        return ctx

    @staticmethod
    def hidden_dirs() -> set[str]:
        return {"vendor", ".bundle"}

    @staticmethod
    def noread_files() -> set[str]:
        return {"Gemfile.lock"}

    @staticmethod
    def config_files() -> set[str]:
        return {"Gemfile"}

    @staticmethod
    def coding_guidelines() -> str:
        return "## Ruby 编码规范\n- 使用 Bundler 管理依赖\n- 遵循 Ruby Style Guide\n"

    @staticmethod
    def testing_guidelines() -> str:
        return "## Ruby 测试要求\n- 使用 `bundle exec rspec` 运行测试\n- 测试放在 spec/ 目录\n"

    @staticmethod
    def complexity_indicators() -> dict[str, list[str]]:
        return {"complex": [], "medium": ["Rails", "Sinatra"]}
