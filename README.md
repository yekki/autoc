# AutoC — 全自动软件开发系统

基于多 Agent 协作的全自动软件开发系统。吸收 MetaGPT / ChatDev / OpenHands / SWE-agent / GPT-Engineer / Anthropic / SamuelQZQ 最佳设计。

PlanningAgent（需求分析与任务规划）→ CodeActAgent（编码、测试、修复一体化 ReAct 循环）。可选启用 CritiqueAgent 做代码级评审（默认关闭）。运作模式与 OpenHands 一致。

## 核心特性

| 特性 | 描述 |
|------|------|
| **PlanningAgent → CodeActAgent** | PlanningAgent 分析需求生成任务计划，CodeActAgent 在 ReAct 循环中完成编码+验证+修复 |
| **Docker 沙箱隔离** | 命令在 Docker 容器内执行，保护宿主机安全 |
| **编码验证一体化** | CodeActAgent 在同一 ReAct 循环中完成编码、测试、修复 |
| **并行任务执行** | 无依赖关系的任务自动并行执行，提升开发速度 |
| **Git 版本控制** | 每个阶段自动提交，支持 diff 查看和 rollback |
| **增量开发** | 支持在已有项目上添加功能，不必从零开始 |
| **经验学习** | 记录成功项目经验，注入后续项目作为 few-shot 参考 |
| **Playwright MCP 浏览器测试** | 通过 MCP 标准集成 Playwright，支持真实浏览器自动化测试 |

## 系统架构

```
用户需求
   │
   ▼
┌──────────────────┐    任务计划     ┌──────────────────┐
│ PlanningAgent    │ ────────────▶ │  CodeActAgent    │
│ 需求分析 + 规划   │  (用户故事/    │  ReAct 循环：     │
│                  │   数据模型/    │  编码 → 验证 →   │
│                  │   API 设计)   │  修复 ⚡ 并行执行  │
└──────────────────┘               └────────┬─────────┘
                                            │
                                   代码实现 + 测试验证
                                   + Git 提交 + 质量检查
                                            │
                               ┌────────────┴────────────┐
                               ▼                         ▼
                         验证未通过                    ✅ 完成
                         (迭代修复)                  (Git tag)
```

## 前置条件

- Python 3.12+
- Node.js 18+
- Docker（所有项目强制在 Docker 沙箱内执行）
- npm + pm2（`npm install -g pm2`）
- 至少一个 LLM API Key（GLM / Kimi / OpenAI / DeepSeek / Qwen 等）

**中国区用户**：设置环境变量 `AUTOC_USE_CN_MIRROR=1`，Agent 安装依赖时自动使用国内镜像（pip 清华源 / npm npmmirror / Go goproxy.cn）

## 安装

```bash
# 克隆项目后进入目录
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cd web && npm install && cd ..
npm install -g pm2
```

## 部署 & 启动

**开发环境统一使用 PM2 管理，禁止手动启动后端/前端进程：**

```bash
./scripts/pm2-manage.sh dev          # 首次启动（后端 8080 + 前端 3000）
./scripts/pm2-manage.sh dev:restart  # 重启（代码修改后）
./scripts/pm2-manage.sh dev:stop     # 停止
./scripts/pm2-manage.sh dev:logs     # 查看日志
./scripts/pm2-manage.sh dev:status   # 查看状态
```

> ⚠️ `python -m autoc.server` 和 `cd web && npm run dev` 仅用于调试单个服务，日常开发必须用 PM2。

**dev vs dev:restart 判断**：PM2 中无进程 → `dev`；已有进程需重启 → `dev:restart`；不确定 → 先 `dev:status`。

访问 http://localhost:3000 打开 Web 界面。

## 使用

1. 打开 http://localhost:3000
2. 点击右上角设置，配置 API Key
3. 创建项目 → 输入需求 → 点击「运行」
4. 实时查看执行进度、代码、预览、终端

## 支持的 LLM

| 预设 | 模型 | 环境变量 |
|------|------|----------|
| `glm` | glm-5 | `GLM_API_KEY` |
| `kimi` | kimi-for-coding | `KIMI_API_KEY` |
| `openai` | gpt-4o | `OPENAI_API_KEY` |
| `qwen` | qwen3.5-plus | `DASHSCOPE_API_KEY` |
| `deepseek` | deepseek-chat | `DEEPSEEK_API_KEY` |
| `local` | default | — （Ollama/vLLM） |

API Key 通过 Web 界面右上角设置配置，支持 Per-Agent 独立模型选择。

## 项目结构

```
autoc/
├── autoc/                  # Python 包
│   ├── server/             #   Web 服务 (FastAPI + SSE)
│   ├── agents/             #   Agent 实现 (PlanningAgent/CodeActAgent/CritiqueAgent)
│   ├── core/               #   核心模块 (LLM/Orchestrator/Project/Analysis/Runtime)
│   ├── tools/              #   工具集 (文件/Shell/Git/沙箱)
│   └── stacks/             #   技术栈适配器 (11 种)
├── web/                    # Web 前端 (React + Ant Design + Zustand)
├── scripts/                # 运维脚本 (PM2 管理 / 测试)
├── config.yaml             # 运行配置
└── requirements.txt        # Python 依赖
```

## 测试

```bash
./scripts/test.sh           # 全部测试（323 tests，100% pass）
./scripts/test.sh -k state  # 特定模块
```

覆盖：PRDState / StateManager / CircuitBreaker / RateLimiter / ExitDetector / SessionRegistry / PRD Import / Config

## 开发规范

- Python 3.12+，全量 type hints + Pydantic 强类型模型
- 命名：类 `PascalCase` / 函数 `snake_case` / 常量 `UPPER_SNAKE_CASE` / 私有方法前缀 `_`
- 格式化：black（Python）+ prettier（JS）；Lint：flake8 + eslint
- 每文件不超过 300 行（UI 组件除外）；避免循环依赖
- 关键逻辑用中文注释

## 安全说明

- API Key 通过 Web UI 配置，持久化到 `config/models.json`（已在 `.gitignore`）；禁止硬编码
- 文件操作限制在 workspace 目录内（路径越界自动拒绝）
- `autoc/tools/shell.py` 有危险命令黑名单
- 所有项目强制在 Docker 沙箱内执行，不支持非沙箱模式
- 截图（`playwright_screenshot`）必须存到 `/tmp`，禁止存项目目录

## Q&A

**Q: 启动后访问 localhost:3000 没有响应？**
A: 运行 `./scripts/pm2-manage.sh dev:status` 检查进程状态，再用 `dev:logs` 查看错误日志。

**Q: Agent 安装依赖很慢？**
A: 中国区用户设置 `AUTOC_USE_CN_MIRROR=1` 环境变量，自动切换国内镜像。

**Q: 如何切换 LLM 模型？**
A: 在 Web 界面右上角设置中配置 API Key 并选择模型，支持 PlanningAgent 和 CodeActAgent 使用不同模型。

**Q: 项目代码生成在哪里？**
A: 生成的项目保存在 `workspace/` 目录下（已在 `.gitignore`，不会提交到 git）。

**Q: 如何重启服务（修改代码后）？**
A: `./scripts/pm2-manage.sh dev:restart`

**Q: Docker 未安装会怎样？**
A: 所有项目强制在 Docker 沙箱内运行，Docker 未安装时任务会报错退出。请先安装 Docker 并确保 daemon 已启动。

## License

MIT
