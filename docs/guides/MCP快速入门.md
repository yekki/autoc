# MCP 快速入门

> 版本: 1.1 | 最后更新: 2026-02-24
> 关联设计文档: TOOL_SYSTEM

本指南帮助你快速开始使用 AutoC 的 MCP (Model Context Protocol) 工具集成功能。

---

## 第一步：安装依赖

```bash
pip install -r requirements.txt
node --version  # 需要 v18+
```

## 第二步：启用 MCP

编辑 `config.yaml`，确保 MCP 已启用：

```yaml
mcp:
  enabled: true
  servers:
    - name: filesystem
      command: npx
      args: ["-y", "@modelcontextprotocol/server-filesystem", "{workspace}"]
    - name: browser
      command: npx
      args: ["-y", "@playwright/mcp@latest"]
  strategy:
    builtin_first: true    # 内置工具优先
    show_in_prompt: true
```

## 第三步：运行示例

### 示例 1：基础 Web 应用开发

在 Web 界面创建项目，输入需求 "创建一个简单的 Flask Todo 应用"，点击运行。

AutoC 会自动加载 MCP 工具，Agent 可使用 `filesystem/*`、`browser/*` 等扩展工具。

### 示例 2：启用数据库工具

```yaml
mcp:
  servers:
    - name: sqlite
      command: npx
      args: ["-y", "@modelcontextprotocol/server-sqlite", "--db-path", "{workspace}/app.db"]
```

在 Web 界面创建项目，输入需求 "创建一个用户管理系统，使用 SQLite"。

## 查看 MCP 工具

启用 DEBUG 日志查看加载了哪些 MCP 工具：

```yaml
logging:
  level: "DEBUG"
```

输出示例：

```
[autoc.mcp] MCP 服务器 'filesystem' 已连接 - 6 个工具, 0 个资源
[autoc.mcp] MCP 已启用 - 2 个服务器, 28 个工具
```

## 配置说明

| 配置项 | 说明 |
|--------|------|
| `mcp.enabled` | 是否启用 MCP（默认 true） |
| `mcp.servers` | 服务器列表，每个包含 name/command/args |
| `mcp.strategy.builtin_first` | true=内置工具优先，false=MCP 优先 |
| `{workspace}` 占位符 | 运行时自动替换为项目工作目录 |

## 自定义 MCP 服务器

```yaml
mcp:
  servers:
    - name: my-server
      command: python
      args: ["/path/to/my_server.py"]
      env:
        MY_VAR: "value"
```

## 常见问题

### Q: MCP 服务器连接失败？

检查 Node.js 版本（`node --version`，需要 v18+）和网络连接（首次 `npx` 会下载包）。

### Q: 如何禁用 MCP？

```yaml
mcp:
  enabled: false
```

---

## 下一步

- 阅读 [工具系统设计文档](../design/TOOL_SYSTEM.md) 了解架构细节
- 探索 [MCP 官方文档](https://modelcontextprotocol.io/) 了解更多服务器
- 查看 [浏览器自动化指南](浏览器自动化指南.md) 了解 Playwright MCP 用法

---

> 返回 [使用手册](使用手册.md) · 更多文档见 [文档中心](../README.md)
