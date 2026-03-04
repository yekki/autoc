"""Python 技术栈适配器"""

import os
import re
from autoc.stacks import StackAdapter, ProjectContext


class PythonAdapter(StackAdapter):

    @staticmethod
    def detect(workspace_dir: str) -> str | None:
        for name in ("requirements.txt", "pyproject.toml", "setup.py"):
            p = os.path.join(workspace_dir, name)
            if os.path.isfile(p):
                return p
        return None

    @staticmethod
    def priority() -> int:
        return 60

    def parse(self, manifest_path: str, workspace_dir: str) -> ProjectContext:
        ctx = ProjectContext(language="Python", install_command="pip install -r requirements.txt",
                             test_command="python -m pytest")
        if not manifest_path:
            manifest_path = os.path.join(workspace_dir, "requirements.txt")
        ctx.manifest_file = os.path.basename(manifest_path)
        if manifest_path.endswith("requirements.txt"):
            self._parse_requirements(manifest_path, ctx)
        elif manifest_path.endswith("pyproject.toml"):
            self._parse_pyproject(manifest_path, ctx)
            ctx.install_command = "pip install -e ."
        # 检测框架
        for fw, name, ptype, port, cmd in [
            ("django", "Django", "web_fullstack", 8000, "python manage.py runserver"),
            ("flask", "Flask", "web_backend", 5000, "python app.py"),
            ("fastapi", "FastAPI", "web_backend", 8000, "uvicorn main:app --reload"),
            ("streamlit", "Streamlit", "web_frontend", 8501, "streamlit run app.py"),
        ]:
            if any(fw in d.lower() for d in ctx.dependencies):
                ctx.framework = name
                ctx.project_type = ptype
                ctx.default_port = port
                ctx.start_command = cmd
                break
        return ctx

    @staticmethod
    def _parse_requirements(path: str, ctx: ProjectContext):
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and not line.startswith("-"):
                        pkg = re.split(r"[=><~!;\[]", line)[0].strip()
                        if pkg:
                            ctx.dependencies.append(pkg)
        except OSError:
            pass

    @staticmethod
    def _parse_pyproject(path: str, ctx: ProjectContext):
        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()
            in_deps = False
            for line in content.splitlines():
                if "dependencies" in line and "=" in line:
                    in_deps = True
                    continue
                if in_deps and line.strip().startswith('"'):
                    pkg = re.split(r"[=><~!]", line.strip().strip('",'))[0].strip()
                    if pkg:
                        ctx.dependencies.append(pkg)
                elif in_deps and line.strip().startswith("[") and "dependencies" not in line:
                    in_deps = False
        except OSError:
            pass

    @staticmethod
    def hidden_dirs() -> set[str]:
        return {"__pycache__", ".venv", "venv", ".mypy_cache", ".pytest_cache",
                ".tox", "site-packages", ".eggs"}

    @staticmethod
    def noread_files() -> set[str]:
        return {"Pipfile.lock", "poetry.lock"}

    @staticmethod
    def noread_extensions() -> set[str]:
        return {".pyc", ".pyo"}

    @staticmethod
    def config_files() -> set[str]:
        return {"requirements.txt", "pyproject.toml", "setup.py", "setup.cfg", "Pipfile"}

    @staticmethod
    def coding_guidelines() -> str:
        from autoc.core.infra.cn_mirror import get_developer_mirror_guideline
        return (
            "## Python 编码规范\n"
            "- 使用 requirements.txt 或 pyproject.toml 管理依赖\n"
            "- 遵循 PEP 8 编码风格，使用 type hints\n"
            "- 环境已隔离: 直接使用 python/pip 命令，不要创建 venv\n"
            + get_developer_mirror_guideline("python")
        )

    @staticmethod
    def testing_guidelines() -> str:
        return (
            "## Python 测试要求\n"
            "- 使用 `python -m pytest` 运行测试\n"
            "- 测试文件命名: `test_*.py`，放在项目根目录或 tests/ 目录\n"
            "- 文件头固定: `import sys, os; sys.path.insert(0, ...)`\n"
        )

    @staticmethod
    def complexity_indicators() -> dict[str, list[str]]:
        return {"complex": [], "medium": ["Flask", "FastAPI", "Django", "Streamlit"]}
