# AutoC — 全自动软件开发系统

> 基于多 Agent 协作的全自动软件开发系统。PlanningAgent（需求分析与任务规划）→ CodeActAgent（编码、测试、修复一体化 ReAct 循环）。设计参考 OpenHands / MetaGPT / ChatDev / SWE-agent / GPT-Engineer。

## 核心特性

| 特性 | 描述 |
|------|------|
| **PlanningAgent → CodeActAgent** | PlanningAgent 分析需求生成任务计划，CodeActAgent 在 ReAct 循环中完成编码+验证+修复 |
| **Docker 沙箱隔离** | 所有项目代码在 Docker 容器内执行，保护宿主机安全 |
| **并行任务执行** | 无依赖关系的任务自动并行执行，提升开发速度 |
| **多模型支持** | 支持 GLM / Kimi / OpenAI / DeepSeek / Qwen，Per-Agent 独立模型选择 |
| **Git 版本控制** | 每个阶段自动提交，支持 diff 查看和回滚 |
| **Web 可视化界面** | 实时监控执行进度、代码浏览、终端、费用统计 |
| **需求智能优化** | 提交前自动评估需求质量，AI 自动补全技术细节 |
| **CritiqueAgent（可选）** | 4 维代码质量评审（默认关闭，可在设置中启用） |

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

---

## 环境要求

| 依赖 | 最低版本 | 说明 |
|------|---------|------|
| **Python** | 3.12+ | 核心运行时 |
| **Node.js** | 18+ | Web 前端 + PM2 |
| **Docker** | 任意版本 | **强制依赖**，所有项目在沙箱内执行 |
| **npm** | 随 Node.js | 用于安装 PM2 和前端依赖 |

```bash
python3 --version    # 需要 3.12+
node --version       # 需要 v18+
docker info          # 确认 Docker 正在运行
```

---

## 快速开始

### 第一步：安装依赖

```bash
# 克隆/进入项目目录
cd autoc

# 创建 Python 虚拟环境并安装后端依赖
python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 安装前端依赖
cd web && npm install && cd ..

# 安装 PM2（全局进程管理）
npm install -g pm2
```

### 第二步：启动服务

开发环境统一使用 PM2 管理，**禁止手动启动后端/前端进程**：

```bash
./scripts/pm2-manage.sh dev          # 首次启动（后端 8080 + 前端 3000）
./scripts/pm2-manage.sh dev:restart  # 代码修改后重启
./scripts/pm2-manage.sh dev:stop     # 停止所有服务
./scripts/pm2-manage.sh dev:logs     # 查看运行日志
./scripts/pm2-manage.sh dev:status   # 查看服务状态
```

启动后访问：
- **前端 UI**: http://localhost:3000
- **后端 API**: http://localhost:8080

> **dev vs dev:restart 判断**：PM2 中无进程 → `dev`；已有进程需重启 → `dev:restart`；不确定 → 先 `dev:status`。

### 第三步：配置 API Key

1. 打开 http://localhost:3000
2. 点击右上角 **设置** 图标
3. 在「模型分配」区域选择 Provider，填入 API Key
4. 点击保存（配置持久化到 `config/models.json`，不入 Git）

支持的 LLM：

| Provider | 推荐模型 | 获取 API Key |
|----------|---------|-------------|
| **智谱 GLM**（推荐） | glm-5 | https://open.bigmodel.cn → API Keys |
| **Kimi Code** | kimi-for-coding | https://www.kimi.com/code → 控制台 |
| OpenAI | gpt-4o | https://platform.openai.com/api-keys |
| DeepSeek | deepseek-chat | https://platform.deepseek.com/api_keys |
| 阿里通义千问 | qwen3.5-plus | https://dashscope.console.aliyun.com |
| 本地（Ollama/vLLM） | — | 无需 Key |

### 第四步：开始使用

1. 点击「**新建项目**」，填写项目名称和技术栈
2. 在左侧输入框描述需求（越详细越好）
3. 点击「**运行**」
4. 实时查看执行进度、生成的代码、终端输出

---

## 中国区网络加速（可选）

设置环境变量 `AUTOC_USE_CN_MIRROR=1`，Agent 安装依赖时自动使用国内镜像：

- pip → 清华源
- npm → npmmirror
- Go → goproxy.cn

通过 PM2 配置设置（推荐，持久化）：

```bash
# 编辑 scripts/ecosystem.dev.config.js，在 env 中添加：
# AUTOC_USE_CN_MIRROR: '1'
```

---

## 项目结构

```
autoc/
├── README.md                       # 本文档
├── requirements.txt                # Python 依赖
├── pytest.ini                      # 测试配置
│
├── autoc/                          # Python 源码包
│   ├── config.py                   # 配置加载
│   ├── app.py                      # Application Factory
│   ├── server/                     # Web 服务 (FastAPI + SSE)
│   │   ├── routes_projects.py      #   项目管理 API
│   │   ├── routes_execution.py     #   执行控制 API
│   │   ├── routes_config.py        #   配置 API
│   │   ├── routes_preview.py       #   预览 API
│   │   └── routes_terminal.py      #   终端 WebSocket
│   ├── agents/                     # Agent 实现
│   │   ├── planner.py              #   PlanningAgent
│   │   ├── code_act_agent.py       #   CodeActAgent
│   │   └── critique.py             #   CritiqueAgent（可选）
│   ├── core/                       # 核心模块
│   │   ├── orchestrator/           #   编排器（调度/循环/门控）
│   │   ├── project/                #   项目管理（状态/进度/PRD导入）
│   │   ├── llm/                    #   LLM 客户端（路由/缓存/上下文）
│   │   ├── analysis/               #   分析系统（复杂度/退出检测）
│   │   ├── infra/                  #   基础设施（熔断器/数据库）
│   │   └── runtime/                #   运行时（Docker沙箱/预览/venv）
│   ├── tools/                      # 工具集（文件/Shell/Git/沙箱）
│   ├── stacks/                     # 技术栈适配器（11 种）
│   ├── prompts/                    # Prompt 模板（Jinja2）
│   ├── profiles/                   # 技术栈配置文件
│   └── skills/                     # 内置技能（编码规范等）
│
├── web/                            # Web 前端（React + Ant Design + Zustand）
│   ├── src/
│   │   ├── components/             #   UI 组件
│   │   ├── services/               #   API 客户端 + SSE
│   │   ├── stores/                 #   Zustand 状态管理
│   │   └── styles/                 #   主题与全局样式
│   ├── package.json
│   └── vite.config.js
│
├── scripts/                        # 运维脚本
│   ├── pm2-manage.sh               #   PM2 统一管理入口
│   ├── ecosystem.dev.config.js     #   PM2 开发环境配置
│   ├── test.sh                     #   测试脚本
│   └── benchmark.py                #   Benchmark 工具
│
├── config/                         # 配置文件
│   ├── config.yaml                 #   运行配置（详见下方说明）
│   ├── project.example.yaml        #   项目配置示例
│   └── models.json                 #   API Key 持久化（gitignored，运行时自动生成）
│
├── tests/                          # 测试套件（323 tests）
├── docs/
│   └── guides/
│       └── 使用手册.md              #   完整使用手册
│
└── workspace/                      # 生成的项目代码（gitignored）
```

---

## 配置说明

主配置文件 `config/config.yaml`，关键字段：

```yaml
# LLM 全局默认
llm:
  preset: "glm"          # glm / kimi / openai / qwen / deepseek / local
  temperature: 0.7
  max_tokens: 32768
  timeout: 120

# Agent 独立配置
agents:
  planner:
    preset: glm
    model: glm-5
  code_act:
    preset: glm
    model: glm-4.7
    max_iterations: 10

# 编排器
orchestrator:
  max_rounds: 3          # 最多跑几轮
  auto_fix: true         # 测试失败后自动修复
  parallel: true         # 并行执行无依赖任务

# Docker 沙箱
features:
  sandbox_image: "nikolaik/python-nodejs:python3.12-nodejs22"
  max_parallel_tasks: 3
```

完整字段说明见 `docs/guides/使用手册.md` §九。

---

## 运行测试

```bash
source .venv/bin/activate
./scripts/test.sh             # 全部测试（323 tests）
./scripts/test.sh -k state    # 特定模块
```

测试覆盖：PRDState / StateManager / CircuitBreaker / RateLimiter / ExitDetector / SessionRegistry / PRD Import / Config

---

## 开发规范

### 代码风格

- Python 3.12+，全量 type hints + Pydantic 强类型模型
- 命名：类 `PascalCase` / 函数 `snake_case` / 常量 `UPPER_SNAKE_CASE` / 私有方法前缀 `_`
- 格式化：black（Python）+ prettier（JS）；Lint：flake8 + eslint
- 每文件不超过 300 行（UI 组件除外）；避免循环依赖
- 关键逻辑用中文注释

```bash
# Python 格式化
black autoc/
flake8 autoc/

# JS 格式化
cd web && npx prettier --write src/
```

### 安全原则

- API Key 通过 Web UI 配置，持久化到 `config/models.json`（已在 `.gitignore`），**禁止硬编码**
- 文件操作限制在 workspace 目录内（路径越界自动拒绝）
- `autoc/tools/shell.py` 内置危险命令黑名单（`rm -rf /` 等自动拦截）
- 所有项目强制在 Docker 沙箱内执行
- 截图（playwright_screenshot）必须存到 `/tmp`，禁止存项目目录

### 添加新功能后

1. **修改 `autoc/` 核心代码** → 同步检查 `autoc/server/` 路由是否需要新增 API
2. **修改配置字段** → 更新 `config/config.yaml` 示例
3. **新增 Agent 工具** → 在 `autoc/tools/registry.py` 注册
4. **修改 Web 组件** → 遵循现有 Zustand Store 结构

---

## 常见问题

**Q: 报错 "Docker 沙箱初始化失败"**
确保 Docker Desktop 已启动（`docker info` 检查）。首次运行会拉取 `nikolaik/python-nodejs:python3.12-nodejs22` 镜像。

**Q: 报错 "未设置 API Key"**
打开 http://localhost:3000 右上角设置，配置对应 Provider 的 API Key。

**Q: 报错 "LLM 调用失败: 429"**
API 调用频率超限，等待几分钟后重试，或切换到另一个模型。

**Q: 生成的代码有问题**
在 Web 界面点击「重新运行」，或优化需求描述后重新提交。

更多问题见 `docs/guides/使用手册.md`。

---

## License

MIT
