"""PHP 技术栈适配器"""
import json
import os

from autoc.stacks import ProjectContext, StackAdapter


class PhpAdapter(StackAdapter):
    @staticmethod
    def detect(workspace_dir: str) -> str | None:
        p = os.path.join(workspace_dir, "composer.json")
        return p if os.path.isfile(p) else None

    @staticmethod
    def priority() -> int:
        return 80

    def parse(self, manifest_path: str, workspace_dir: str) -> ProjectContext:
        ctx = ProjectContext(
            language="PHP",
            manifest_file="composer.json",
            install_command="composer install",
            test_command="vendor/bin/phpunit",
        )
        if not manifest_path:
            manifest_path = os.path.join(workspace_dir, "composer.json")
        try:
            with open(manifest_path, encoding="utf-8") as f:
                pkg = json.load(f)
            deps = pkg.get("require", {})
            ctx.dependencies = [k for k in deps if k != "php"]
            if "laravel/framework" in deps:
                ctx.framework = "Laravel"
                ctx.project_type = "web_fullstack"
                ctx.default_port = 8000
                ctx.start_command = "php artisan serve"
            elif "symfony/framework-bundle" in deps:
                ctx.framework = "Symfony"
                ctx.project_type = "web_backend"
                ctx.default_port = 8000
        except (json.JSONDecodeError, OSError):
            pass
        return ctx

    @staticmethod
    def hidden_dirs() -> set[str]:
        return {"vendor", ".composer"}

    @staticmethod
    def noread_files() -> set[str]:
        return {"composer.lock"}

    @staticmethod
    def config_files() -> set[str]:
        return {"composer.json"}

    @staticmethod
    def coding_guidelines() -> str:
        return "## PHP 编码规范\n- 使用 Composer 管理依赖\n- 遵循 PSR-12 编码标准\n"

    @staticmethod
    def testing_guidelines() -> str:
        return "## PHP 测试要求\n- 使用 `vendor/bin/phpunit` 运行测试\n- 测试放在 tests/ 目录\n"

    @staticmethod
    def complexity_indicators() -> dict[str, list[str]]:
        return {"complex": [], "medium": ["Laravel", "Symfony"]}
