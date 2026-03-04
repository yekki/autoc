# PM2 部署指南

> 版本: 2.0 | 最后更新: 2026-02-24
> 关联设计文档: RUNTIME_SANDBOX / WEB_FRONTEND

本指南介绍如何使用 PM2 进程管理器部署和管理 AutoC 服务。

---

## 一、速查命令

### 开发环境（推荐日常使用）

```bash
./scripts/pm2-manage.sh dev            # 启动（后端 8080 + 前端 3000）
./scripts/pm2-manage.sh dev:restart    # 重启
./scripts/pm2-manage.sh dev:stop       # 停止
./scripts/pm2-manage.sh dev:logs       # 查看日志
./scripts/pm2-manage.sh dev:status     # 查看状态
./scripts/pm2-manage.sh dev:delete     # 删除进程
```

启动后访问：
- **后端 API**: http://localhost:8080
- **前端 UI**: http://localhost:3000

### 生产环境（仅后端）

```bash
./scripts/pm2-manage.sh start          # 启动（仅后端 8080）
./scripts/pm2-manage.sh restart        # 重启
./scripts/pm2-manage.sh stop           # 停止
./scripts/pm2-manage.sh reload         # 零停机重载
```

启动后访问：http://localhost:8080（生产模式前端由后端静态文件服务提供）

---

## 二、开发环境 vs 生产环境

| 维度 | 开发环境 (`dev`) | 生产环境 (`start`) |
|------|-----------------|-------------------|
| 进程 | `autoc-backend` + `autoc-frontend` | `autoc-web` |
| 端口 | 8080 (API) + 3000 (Vite dev) | 8080 (含静态前端) |
| 热更新 | 后端代码变更自动重启 | 需手动 restart/reload |
| 前端 | Vite 开发服务器（HMR） | 预编译静态文件 |
| 适用场景 | 日常开发 | 正式部署 |

### 判断用 `dev` 还是 `dev:restart`

| 场景 | 命令 |
|------|------|
| PM2 中没有 `autoc-backend`/`autoc-frontend` 进程 | `dev`（首次启动） |
| 进程已存在但需重启 | `dev:restart` |
| 不确定 | 先 `dev:status` 看状态再决定 |

---

## 三、快速开始

### 1. 安装 PM2

```bash
npm install -g pm2
```

### 2. 启动开发环境

```bash
./scripts/pm2-manage.sh dev
```

输出：

```
✓ 开发环境已启动
  后端 API : http://localhost:8080
  前端 UI  : http://localhost:3000
  查看日志 : ./pm2-manage.sh dev:logs
```

### 3. 查看状态

```bash
./scripts/pm2-manage.sh dev:status
```

---

## 四、开发环境配置

配置文件：`scripts/ecosystem.dev.config.js`

开发环境管理两个进程：

| 进程名 | 说明 | 端口 |
|--------|------|------|
| `autoc-backend` | Python FastAPI 后端 | 8080 |
| `autoc-frontend` | Vite React 开发服务器 | 3000 |

后端支持**文件监听**：`autoc/` 目录下代码变更自动重启（2 秒延迟去抖）。

日志文件：

| 类型 | 路径 |
|------|------|
| 后端输出 | `logs/dev-backend-out.log` |
| 后端错误 | `logs/dev-backend-error.log` |
| 前端输出 | `logs/dev-frontend-out.log` |
| 前端错误 | `logs/dev-frontend-error.log` |

---

## 五、生产环境配置

配置文件：`scripts/ecosystem.config.js`

生产环境只有一个进程 `autoc-web`，前端通过预编译的静态文件由后端提供服务。

### 部署步骤

```bash
# 1. 构建前端
cd web && npm run build && cd ..

# 2. 启动生产服务
./scripts/pm2-manage.sh start

# 3. 访问 http://localhost:8080
```

---

## 六、通用管理命令

```bash
./scripts/pm2-manage.sh status      # 查看所有进程状态
./scripts/pm2-manage.sh logs        # 查看实时日志
./scripts/pm2-manage.sh logs:err    # 只看错误日志
./scripts/pm2-manage.sh logs:out    # 只看输出日志
./scripts/pm2-manage.sh monit       # 打开监控面板
./scripts/pm2-manage.sh flush       # 清空日志文件
./scripts/pm2-manage.sh info        # 详细信息
```

---

## 七、开机自启

```bash
pm2 save           # 保存当前进程列表
pm2 startup        # 生成开机启动脚本（按提示执行命令）
pm2 unstartup      # 取消开机自启
```

---

## 八、故障排查

### 服务无法启动

```bash
# 1. 检查虚拟环境
ls .venv/bin/python3

# 2. 查看错误日志
./scripts/pm2-manage.sh dev:logs

# 3. 手动测试后端
source .venv/bin/activate && python -m autoc.server
```

### 端口占用

```bash
lsof -i :8080
lsof -i :3000
```

### PM2 进程残留

```bash
./scripts/pm2-manage.sh dev:delete   # 删除开发环境进程
./scripts/pm2-manage.sh delete       # 删除生产环境进程
```

---

## 九、禁止事项

- **禁止** `python -m autoc.server` 直接运行后端（绕过 PM2，导致端口冲突）
- **禁止** `cd web && npm run dev` 直接运行前端（同上）
- **禁止** 手动 `kill` PM2 管理的进程（用 `dev:stop` 或 `dev:delete`）

---

> 返回 [使用手册](使用手册.md) · 更多文档见 [文档中心](../README.md)
