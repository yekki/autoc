"""C/C++ 技术栈适配器"""
import os
import re

from autoc.stacks import ProjectContext, StackAdapter


class CppAdapter(StackAdapter):
    @staticmethod
    def detect(workspace_dir: str) -> str | None:
        for name in ("CMakeLists.txt", "Makefile"):
            p = os.path.join(workspace_dir, name)
            if os.path.isfile(p):
                return p
        return None

    @staticmethod
    def priority() -> int:
        return 90

    def parse(self, manifest_path: str, workspace_dir: str) -> ProjectContext:
        basename = os.path.basename(manifest_path) if manifest_path else ""
        ctx = ProjectContext(
            language="C/C++",
            manifest_file=basename,
            test_command="ctest --test-dir build",
        )
        if basename == "CMakeLists.txt":
            ctx.build_command = "cmake -B build && cmake --build build"
            ctx.install_command = "cmake -B build && cmake --build build"
            try:
                with open(manifest_path, encoding="utf-8") as f:
                    content = f.read()
                m = re.search(r"project\s*\(\s*(\w+)", content)
                if m:
                    ctx.entry_point = m.group(1)
            except OSError:
                pass
        else:
            ctx.build_command = "make"
            ctx.install_command = "make"
            try:
                with open(manifest_path, encoding="utf-8") as f:
                    targets = re.findall(r"^(\w+)\s*:", f.read(), re.MULTILINE)
                    ctx.scripts = {t: f"make {t}" for t in targets[:10]}
            except OSError:
                pass
        return ctx

    @staticmethod
    def hidden_dirs() -> set[str]:
        return {"build", "cmake-build-debug", "cmake-build-release"}

    @staticmethod
    def noread_files() -> set[str]:
        return set()

    @staticmethod
    def noread_extensions() -> set[str]:
        return {".o", ".so", ".a", ".dylib"}

    @staticmethod
    def config_files() -> set[str]:
        return {"CMakeLists.txt"}

    @staticmethod
    def coding_guidelines() -> str:
        return "## C/C++ 编码规范\n- 使用 CMake 或 Makefile 构建\n- 使用 clang-format 格式化\n"

    @staticmethod
    def testing_guidelines() -> str:
        return "## C/C++ 测试要求\n- 使用 `ctest` 运行测试\n- 推荐 Google Test 或 Catch2\n"

    @staticmethod
    def complexity_indicators() -> dict[str, list[str]]:
        return {"complex": [], "medium": []}
