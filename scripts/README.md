# 脚本目录

> 版本: 1.1 | 最后更新: 2026-02-22

此目录包含 AutoC 的启动、管理、测试和迁移脚本。所有启停操作均通过此目录下的脚本执行。

## Shell 脚本（启动 / 管理）

### `run.sh` — CLI 便捷启动

```bash
./scripts/run.sh "你的需求"              # 使用默认预设
./scripts/run.sh -p kimi "你的需求"      # 使用 Kimi
./scripts/run.sh -p glm "你的需求"       # 使用 GLM
./scripts/run.sh -i                      # 交互式模式
```

### `run-loop.sh` — 自动循环执行

参考 Anthropic 长时运行 Agent 最佳实践，循环执行多个任务直到全部通过。

```bash
./scripts/run-loop.sh "需求描述"          # 默认循环 20 次
./scripts/run-loop.sh "需求描述" 10       # 最多循环 10 次
./scripts/run-loop.sh "需求描述" 50             # Docker 沙箱始终开启
```

日志保存到 `logs/runs/` 目录。

### `start-backend.sh` — 启动后端服务

```bash
./scripts/start-backend.sh              # 启动 FastAPI 后端（端口 8080）
```

自动激活 `.venv` 并以 `python -m autoc.server` 启动。

### `test.sh` — 运行测试套件

```bash
./scripts/test.sh                       # 运行全部测试（67 tests）
./scripts/test.sh -k state              # 只跑 state 相关测试
./scripts/test.sh --cov                 # 含覆盖率报告
```

### `pm2-manage.sh` — PM2 进程管理

```bash
./scripts/pm2-manage.sh start           # 启动所有服务
./scripts/pm2-manage.sh stop            # 停止所有服务
./scripts/pm2-manage.sh restart         # 重启所有服务
./scripts/pm2-manage.sh logs            # 查看日志
./scripts/pm2-manage.sh status          # 查看状态
```

详细说明见 [docs/guides/PM2_DEPLOYMENT.md](../docs/guides/PM2_DEPLOYMENT.md)。

### `tmux-monitor.sh` — tmux 多窗口监控

```bash
./scripts/tmux-monitor.sh              # 启动 tmux 会话，分屏监控后端/前端/日志
```

## Python 脚本（数据库迁移）

> ⚠️ 迁移脚本为一次性操作，执行前请备份数据。

### `migrate_to_sqlite.py` — 迁移到 SQLite

从旧版 JSON 文件格式迁移到 SQLite 数据库。

```bash
python scripts/migrate_to_sqlite.py
```

### `migrate_to_db.py` — 数据库结构升级

SQLite 数据库结构版本升级脚本。

```bash
python scripts/migrate_to_db.py
```

### `migrate_drop_requirements.py` — 清理旧 requirements 表

删除旧版 requirements 表，迁移到新的三层架构。

```bash
python scripts/migrate_drop_requirements.py
```

## PM2 配置文件

| 文件 | 用途 |
|------|------|
| `ecosystem.config.js` | PM2 生产环境配置（后端 + 前端） |
| `ecosystem.dev.config.js` | PM2 开发环境配置 |

## 注意事项

- 所有 `.sh` 脚本必须在项目根目录下执行，脚本会自动切换到正确的工作目录
- 确保脚本具有可执行权限：`chmod +x scripts/*.sh`
- Python 迁移脚本需先激活虚拟环境：`source .venv/bin/activate`
