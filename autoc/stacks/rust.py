"""Rust 技术栈适配器"""
import os, re
from autoc.stacks import StackAdapter, ProjectContext

class RustAdapter(StackAdapter):
    @staticmethod
    def detect(workspace_dir: str) -> str | None:
        p = os.path.join(workspace_dir, "Cargo.toml")
        return p if os.path.isfile(p) else None

    @staticmethod
    def priority() -> int:
        return 60

    def parse(self, manifest_path: str, workspace_dir: str) -> ProjectContext:
        ctx = ProjectContext(language="Rust", manifest_file="Cargo.toml",
                             install_command="cargo build", build_command="cargo build --release",
                             test_command="cargo test")
        if not manifest_path:
            manifest_path = os.path.join(workspace_dir, "Cargo.toml")
        try:
            with open(manifest_path, encoding="utf-8") as f:
                content = f.read()
            m = re.search(r'name\s*=\s*"(.+?)"', content)
            if m: ctx.entry_point = m.group(1)
            in_deps = False
            for line in content.splitlines():
                if line.strip() == "[dependencies]":
                    in_deps = True; continue
                if in_deps:
                    if line.strip().startswith("["): break
                    parts = line.split("=")
                    if len(parts) >= 2: ctx.dependencies.append(parts[0].strip())
            for fw, name in [("actix-web", "Actix"), ("rocket", "Rocket"), ("axum", "Axum")]:
                if fw in ctx.dependencies:
                    ctx.framework = name
                    ctx.project_type = "web_backend"
                    ctx.default_port = 8080
                    ctx.start_command = "cargo run"
                    break
        except OSError:
            pass
        return ctx

    @staticmethod
    def hidden_dirs() -> set[str]:
        return {"target", ".cargo"}

    @staticmethod
    def noread_files() -> set[str]:
        return {"Cargo.lock"}

    @staticmethod
    def config_files() -> set[str]:
        return {"Cargo.toml"}

    @staticmethod
    def coding_guidelines() -> str:
        return ("## Rust 编码规范\n"
                "- 使用 Cargo.toml 管理依赖，cargo add 添加\n"
                "- 使用 cargo fmt 格式化，cargo clippy 检查\n")

    @staticmethod
    def testing_guidelines() -> str:
        return ("## Rust 测试要求\n"
                "- 使用 `cargo test` 运行测试\n"
                "- 模块内使用 #[cfg(test)] 和 #[test] 宏\n")

    @staticmethod
    def complexity_indicators() -> dict[str, list[str]]:
        return {"complex": [], "medium": ["Actix", "Rocket", "Axum", "Warp"]}
