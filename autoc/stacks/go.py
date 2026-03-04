"""Go 技术栈适配器"""
import os, re
from autoc.stacks import StackAdapter, ProjectContext

class GoAdapter(StackAdapter):
    @staticmethod
    def detect(workspace_dir: str) -> str | None:
        p = os.path.join(workspace_dir, "go.mod")
        return p if os.path.isfile(p) else None

    @staticmethod
    def priority() -> int:
        return 60

    def parse(self, manifest_path: str, workspace_dir: str) -> ProjectContext:
        ctx = ProjectContext(language="Go", manifest_file="go.mod",
                             install_command="go mod download", build_command="go build ./...",
                             test_command="go test ./...")
        if not manifest_path:
            manifest_path = os.path.join(workspace_dir, "go.mod")
        try:
            with open(manifest_path, encoding="utf-8") as f:
                content = f.read()
            m = re.search(r"^module\s+(.+)$", content, re.MULTILINE)
            if m:
                ctx.entry_point = m.group(1).strip()
            in_req = False
            for line in content.splitlines():
                if line.strip() == "require (":
                    in_req = True; continue
                if in_req:
                    if line.strip() == ")": break
                    parts = line.strip().split()
                    if parts: ctx.dependencies.append(parts[0])
            for fw, name in [("gin-gonic/gin", "Gin"), ("labstack/echo", "Echo"),
                             ("gofiber/fiber", "Fiber")]:
                if any(fw in d for d in ctx.dependencies):
                    ctx.framework = name
                    ctx.project_type = "web_backend"
                    ctx.default_port = 8080
                    ctx.start_command = "go run ."
                    break
            if not ctx.framework:
                for fw in ("spf13/cobra", "urfave/cli", "alecthomas/kingpin"):
                    if any(fw in d for d in ctx.dependencies):
                        ctx.project_type = "cli_tool"
                        ctx.start_command = "go run . --help"
                        break
                if ctx.project_type == "unknown":
                    main_go = os.path.join(workspace_dir, "main.go")
                    cmd_dir = os.path.join(workspace_dir, "cmd")
                    if os.path.isfile(main_go) or os.path.isdir(cmd_dir):
                        ctx.project_type = "cli_tool"
                        ctx.start_command = "go run ."
        except OSError:
            pass
        return ctx

    @staticmethod
    def hidden_dirs() -> set[str]:
        return {"vendor"}

    @staticmethod
    def noread_files() -> set[str]:
        return {"go.sum"}

    @staticmethod
    def config_files() -> set[str]:
        return {"go.mod"}

    @staticmethod
    def coding_guidelines() -> str:
        return ("## Go 编码规范\n"
                "- 使用 go.mod 管理依赖，go get 添加新依赖\n"
                "- 遵循标准项目布局（cmd/ pkg/ internal/）\n"
                "- 使用 go fmt 格式化，错误处理用 if err != nil\n")

    @staticmethod
    def testing_guidelines() -> str:
        return ("## Go 测试要求\n"
                "- 使用 `go test ./...` 运行测试\n"
                "- 测试文件: `*_test.go`，函数: `func TestXxx(t *testing.T)`\n"
                "- 表驱动测试优先\n")

    @staticmethod
    def complexity_indicators() -> dict[str, list[str]]:
        return {"complex": ["gRPC"], "medium": ["Gin", "Echo", "Fiber", "GORM"]}
