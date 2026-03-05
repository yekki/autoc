---
name: benchmark
description: Benchmark 工作流 — 基线→优化→对照三步法 + 复盘报告规范。说"跑 benchmark"或"写复盘"时触发。
---

# Benchmark 工作流

通过口令触发 benchmark 相关工作流，覆盖从跑基线到写复盘的完整流程。

## 口令速查

| 口令 | 适用场景 | 跳转 |
|------|---------|------|
| **"跑 benchmark"** | 优化前后对比 | §三步法 |
| **"写复盘"** / **"benchmark 复盘"** | 分析结果、写报告 | §复盘规范 |

---

## §三步法

对 Agent 循环、工具系统、沙箱架构、Prompt 做**功能性或性能性优化**时必须遵守。
纯 bug 修复、注释调整、格式化等不触发。

### 1. 优化前：跑基线（如尚无可用基线）

```bash
python scripts/benchmark.py run --tag baseline_<feature> --description "优化前基线"
```

- 如果 `benchmarks/results/` 下已有近期可对比的结果，可跳过
- 运行完自动生成 `benchmarks/reports/baseline_<feature>.md`
- **同名 tag 已存在会报错**，需换名或加 `--force` 覆盖

### 2. 做优化

正常改代码。

### 3. 优化后：跑对照 + 看报告

```bash
python scripts/benchmark.py run --tag <feature> --description "简要说明改了什么"
```

- 自动生成标准报告，含瓶颈分析、Token 效率、异常值检测、与上次自动对比
- **对比逻辑只比两次都成功的共同用例**，避免统计谬误
- 如果关键指标明显恶化且无合理解释，不要提交，先排查

### 命令速查

| 命令 | 用途 |
|------|------|
| `python scripts/benchmark.py run --tag <tag>` | 运行 3 个核心用例（默认 repeat=3，关闭 Critique，超时 600s/用例） |
| `python scripts/benchmark.py run --tag <tag> --quick` | 快速模式（repeat=1，最快验证） |
| `python scripts/benchmark.py run --tag <tag> --cases hello` | 只跑冒烟测试 |
| `python scripts/benchmark.py run --tag <tag> --critique` | 开启 Critique 评审 |
| `python scripts/benchmark.py run --tag <tag> --timeout 300` | 自定义超时（秒） |
| `python scripts/benchmark.py run --tag <tag> --force` | 覆盖已有同名标签 |
| `python scripts/benchmark.py compare <a> <b> --export` | 深度对比两次结果 |
| `python scripts/benchmark.py history` | 查看所有历史结果 |
| `python scripts/benchmark.py cases` | 列出可用用例（含验证项数） |

### 报告产出

每次 `run` 自动产出：
- `benchmarks/results/{tag}.json` — 原始数据（含环境信息、Token 明细、质量验证、repeat 数据）
- `benchmarks/reports/{tag}.md` — 标准报告（含瓶颈分析 + 质量验证 + 多次运行统计 + 异常检测 + 自动对比）
- `benchmarks/logs/{case}_{ts}.json` — 失败用例事件日志（仅失败时）

### 关键指标速查

| 指标 | 意义 | 警戒线 |
|------|------|--------|
| P:C 比值 | prompt/completion，越高说明 system prompt 越重 | > 30:1 |
| 缓存命中率 | cached_tokens/prompt_tokens，越高越省钱 | < 30% |
| API 调用次数 | LLM 轮次，反映迭代效率 | > 30 |

### 异常值检测

报告末尾自动检测异常值，标红情况：
- `dev_iterations=0` / `exit_reason` 为空 / `tasks_total=0`
- 单 Agent Token 占比 > 95%
- simple 用例比 complex 慢
- P:C > 30:1 / 执行成功但质量验证未通过

### 瓶颈诊断速查

- dev_test 耗时占比 > 80% → 迭代过多
- coder Token 占比 > 70% → 全量覆盖烧 Token
- execute_command 错误率高 → Shell 超时/命令失败
- read_file 远多于 write_file → Agent 在反复探索
- P:C > 25:1 → system prompt / 工具 schema 占比过重

---

## §复盘规范

所有 benchmark 复盘集中在 `docs/benchmarks/` 目录，三类文件：

| 文件 | 命名 | 内容 |
|------|------|------|
| 复盘报告 | `R{NNN}-{tag}.md` | 数据分析 + 问题发现 |
| 落地方案 | `A{NNN}-{tag}.md` | 对应 R 的改进任务 + 进度追踪 |
| 待办汇总 | `backlog.md` | 全量未完成项，按优先级排序 |

编号一一对应：R001 ↔ A001。

### 跑完 benchmark 后的流程

1. **创建 R{NNN}**：分析 `benchmarks/results/{tag}.json` + 执行日志，写复盘报告
2. **创建 A{NNN}**：从 R 中提取可执行的改进任务，含工作量、验收标准、进度追踪
3. **更新 backlog.md**：新待办加入对应优先级区域，标注来源 `[A{NNN}]`
4. **更新 README.md**：在对照表中新增一行

### 复盘报告（R）必须包含

- 数据纵向对比（与历史 benchmark 对比，同用例）
- 问题发现（列表形式，标严重程度）
- 工具调用分析（edit_file/write_file/execute_command 比例）
- 质量验证审计（L1/L2/L3 哪些通过、哪些缺失）
- 与上一次复盘的改进项交叉验证

### 落地方案（A）必须包含

- P0/P1/P2 分级任务表（含工作量、改什么文件、验收标准）
- 执行顺序依赖图
- 进度追踪表（状态 + 完成日期）
