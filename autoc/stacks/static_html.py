"""纯静态 HTML 技术栈适配器"""
import os

from autoc.stacks import ProjectContext, StackAdapter


class StaticHtmlAdapter(StackAdapter):
    @staticmethod
    def detect(workspace_dir: str) -> str | None:
        p = os.path.join(workspace_dir, "index.html")
        return p if os.path.isfile(p) else None

    @staticmethod
    def priority() -> int:
        return 200

    def parse(self, manifest_path: str, workspace_dir: str) -> ProjectContext:
        return ProjectContext(
            language="HTML/CSS/JS",
            manifest_file="index.html",
            project_type="web_frontend",
            entry_point="index.html",
            start_command="python -m http.server 8000",
            default_port=8000,
        )

    @staticmethod
    def hidden_dirs() -> set[str]:
        return set()

    @staticmethod
    def noread_files() -> set[str]:
        return set()

    @staticmethod
    def config_files() -> set[str]:
        return set()

    @staticmethod
    def coding_guidelines() -> str:
        return "## HTML/CSS/JS 编码规范\n- 语义化 HTML 标签\n- CSS 类名使用 kebab-case\n"

    @staticmethod
    def testing_guidelines() -> str:
        return "## 静态项目测试\n- 在浏览器中打开 index.html 验证\n- 检查 console 无报错\n"
