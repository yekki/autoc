"""JavaScript / Node.js 技术栈适配器"""

import json
import os
from autoc.stacks import StackAdapter, ProjectContext


class NodeAdapter(StackAdapter):

    @staticmethod
    def detect(workspace_dir: str) -> str | None:
        p = os.path.join(workspace_dir, "package.json")
        return p if os.path.isfile(p) else None

    @staticmethod
    def priority() -> int:
        return 50

    def parse(self, manifest_path: str, workspace_dir: str) -> ProjectContext:
        ctx = ProjectContext(language="JavaScript/Node.js", manifest_file="package.json",
                             install_command="npm install", test_command="npm test")
        if not manifest_path:
            manifest_path = os.path.join(workspace_dir, "package.json")
        try:
            with open(manifest_path, encoding="utf-8") as f:
                pkg = json.load(f)
            ctx.scripts = pkg.get("scripts", {})
            ctx.entry_point = pkg.get("main", "index.js")
            deps = pkg.get("dependencies", {})
            dev_deps = pkg.get("devDependencies", {})
            ctx.dependencies = list(deps.keys())
            ctx.dev_dependencies = list(dev_deps.keys())
            all_deps = {**deps, **dev_deps}
            for fw, name in [("next", "Next.js"), ("react", "React"), ("vue", "Vue"),
                             ("svelte", "Svelte"), ("express", "Express"), ("fastify", "Fastify")]:
                if fw in all_deps:
                    ctx.framework = name
                    break
            if "test" in ctx.scripts:
                ctx.test_command = "npm test"
            if "build" in ctx.scripts:
                ctx.build_command = "npm run build"
            if "dev" in ctx.scripts:
                ctx.start_command = "npm run dev"
                ctx.default_port = 5173
            elif "start" in ctx.scripts:
                ctx.start_command = "npm start"
                ctx.default_port = 3000
            # 检测项目类型
            if any(fw in all_deps for fw in ("express", "fastify", "koa", "@hapi/hapi")):
                ctx.project_type = "web_backend"
            elif any(fw in all_deps for fw in ("next", "nuxt", "@remix-run/dev")):
                ctx.project_type = "web_fullstack"
            elif any(fw in all_deps for fw in ("react", "vue", "svelte", "vite")):
                ctx.project_type = "web_frontend"
        except (json.JSONDecodeError, OSError):
            pass
        return ctx

    @staticmethod
    def hidden_dirs() -> set[str]:
        return {"node_modules", ".next", ".nuxt", ".output", "dist", "build", ".cache"}

    @staticmethod
    def noread_files() -> set[str]:
        return {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb"}

    @staticmethod
    def config_files() -> set[str]:
        return {"package.json", "tsconfig.json", "vite.config.js", "vite.config.ts",
                "webpack.config.js", "next.config.js", "next.config.mjs"}

    @staticmethod
    def coding_guidelines() -> str:
        from autoc.core.infra.cn_mirror import get_developer_mirror_guideline
        return (
            "## Node.js 编码规范\n"
            "- 使用 package.json 管理依赖，`npm install <pkg>` 添加新依赖\n"
            "- 优先使用 ES Modules（import/export），避免 CommonJS\n"
            "- 使用 const/let，禁止 var\n"
            "- 异步操作使用 async/await\n"
            + get_developer_mirror_guideline("node")
        )

    @staticmethod
    def testing_guidelines() -> str:
        return (
            "## Node.js 测试要求\n"
            "- 使用 `npm test` 运行测试\n"
            "- 如果 package.json 没有 test script，使用 `node --test` (Node 18+)\n"
            "- 测试文件命名: `*.test.js` 或 `*.spec.js`\n"
        )

    @staticmethod
    def complexity_indicators() -> dict[str, list[str]]:
        return {"complex": [], "medium": ["Express", "Fastify", "Koa", "Hapi"]}
