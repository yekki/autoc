import { useEffect, useRef, useState, useMemo } from 'react'
import { Input, Empty, Switch, Tooltip, Tag } from 'antd'
import {
  SearchOutlined, VerticalAlignBottomOutlined,
  PauseCircleOutlined,
} from '@ant-design/icons'
import useStore from '../../stores/useStore'

const LEVEL_STYLES = {
  info:    { color: '#8b949e' },
  success: { color: '#3fb950' },
  warn:    { color: '#d29922' },
  error:   { color: '#f85149', fontWeight: 600 },
  phase:   { color: '#58a6ff' },
  task:    { color: '#bc8cff' },
}

function formatEvent(log) {
  const d = log.data || {}
  const agent = log.agent !== 'system' ? `[${log.agent}]` : ''
  const lines = []

  const push = (level, text) => lines.push({ level, text })

  switch (log.type) {
    case 'sandbox_preparing': {
      const detail = d.message || (d.step ? `(${d.step})` : '')
      const pct = d.progress != null ? ` ${d.progress}%` : ''
      push('info', `${agent} 沙箱准备中${detail ? ` ${detail}` : ''}${pct}`)
      break
    }
    case 'sandbox_ready':
      push('success', `${agent} 沙箱就绪${d.container_id ? ` container=${d.container_id.slice(0, 12)}` : ''}`)
      break
    case 'redefine_start':
      push('phase', `${agent} 新需求开始 ${d.old_version || '?'} → ${d.new_version || '?.0.0'}`)
      if (d.requirement) push('info', `  需求: ${truncate(d.requirement, 120)}`)
      break
    case 'add_feature_start':
      push('phase', `${agent} 新功能开始 ${d.old_version || '?'} → ${d.new_version || '?.?.0'}`)
      if (d.requirement) push('info', `  需求: ${truncate(d.requirement, 120)}`)
      break
    case 'phase_start':
      push('phase', `${agent} ──── ${d.phase || d.name || '阶段'} ────`)
      break
    case 'planning_analyzing':
      push('info', `${agent} 需求分析中...`)
      break
    case 'planning_progress': {
      const msg = d.message || d.step || ''
      push('info', `${agent} 规划进度: ${msg}`)
      break
    }
    case 'planning_review':
      push('info', `${agent} 规划评审${d.approved ? ' ✓ 通过' : ' ✗ 需修改'}`)
      if (d.feedback) push('info', `  反馈: ${truncate(d.feedback, 150)}`)
      break
    case 'planning_acceptance': {
      const accepted = d.accepted ?? d.approved
      push(accepted ? 'success' : 'warn', `${agent} 规划验收${accepted ? ' ✓ 通过' : ' ✗ 驳回'}`)
      if (d.reason) push('info', `  原因: ${truncate(d.reason, 150)}`)
      break
    }
    case 'planning_decision':
      push('info', `${agent} PM 决策: ${d.decision || d.action || ''}`)
      break
    case 'complexity_assessed':
      push('info', `${agent} 复杂度评估: ${d.level || d.complexity || ''}`)
      break
    case 'plan_ready': {
      const tasks = d.tasks || []
      push('success', `${agent} 规划完成: ${tasks.length} 个任务`)
      tasks.forEach((t, i) => push('info', `  ${i + 1}. [${t.id}] ${t.title}`))
      break
    }
    case 'task_start':
      push('task', `${agent} ▶ 任务开始 [${d.task_id || d.id || ''}] ${d.title || ''}`)
      break
    case 'task_complete': {
      const ok = d.passes ?? d.success
      const elapsed = d.elapsed_seconds ? ` ${fmtDuration(d.elapsed_seconds)}` : ''
      const tokens = d.tokens_used ? ` ${(d.tokens_used / 1000).toFixed(1)}K tokens` : ''
      push(ok ? 'success' : 'error',
        `${agent} ${ok ? '✓' : '✗'} 任务完成 [${d.task_id || d.id || ''}] ${d.title || ''}${elapsed}${tokens}`)
      if (!ok && d.error) push('error', `  错误: ${truncate(d.error, 200)}`)
      break
    }
    case 'task_verified': {
      const ok = d.passes
      push(ok ? 'success' : 'warn',
        `${agent} ${ok ? '✓' : '✗'} 任务验证 [${d.task_id || ''}]${d.notes ? ` ${truncate(d.notes, 100)}` : ''}`)
      break
    }
    case 'task_regression':
      push('warn', `${agent} ⟲ 回归检测 [${d.task_id || ''}] ${d.reason || ''}`)
      break
    case 'file_created':
      push('info', `${agent} 文件创建: ${d.path || d.file || ''}`)
      break
    case 'test_result': {
      const p = d.passed ?? '?'
      const t = d.total ?? '?'
      push(p === t ? 'success' : 'warn', `${agent} 测试结果: ${p}/${t} passed`)
      if (d.failures?.length) d.failures.forEach(f => push('error', `  ✗ ${f}`))
      break
    }
    case 'dev_self_test':
      push('info', `${agent} 自测${d.passed ? ' ✓' : ' ✗'}${d.message ? ` ${truncate(d.message, 100)}` : ''}`)
      break
    case 'smoke_check_failed':
      push('warn', `${agent} 冒烟检查失败${d.issues?.length ? `: ${d.issues.length} 个问题` : ''}`)
      if (d.issues?.length) d.issues.forEach(iss => push('warn', `  - ${truncate(typeof iss === 'string' ? iss : iss.message || JSON.stringify(iss), 120)}`))
      break
    case 'deploy_gate':
      push(d.passed ? 'success' : 'warn', `${agent} 部署门禁${d.passed ? ' ✓ 通过' : ' ✗ 未通过'}`)
      break
    case 'bug_fix_start':
      push('warn', `${agent} 开始修复 Bug${d.bug_id ? ` #${d.bug_id}` : ''}`)
      break
    case 'failure_analysis':
      push('error', `${agent} 失败分析: ${truncate(d.analysis || d.message || '', 200)}`)
      if (d.root_cause) push('error', `  根因: ${truncate(d.root_cause, 150)}`)
      break
    case 'reflection':
      push('info', `${agent} 复盘: ${truncate(d.content || d.message || '', 150)}`)
      break
    case 'preview_ready':
      push('success', `${agent} 预览就绪${d.url ? ` ${d.url}` : ''}`)
      break
    case 'execution_failed':
      push('error', `${agent} 执行失败: ${truncate(d.message || d.reason || '', 200)}`)
      break
    case 'error':
      push('error', `${agent} ❌ ${d.message || d.error || '未知错误'}`)
      if (d.traceback) push('error', `  ${truncate(d.traceback, 300)}`)
      break
    case 'token_session': {
      const total = d.total_tokens ? `${(d.total_tokens / 1000).toFixed(1)}K` : '?'
      push('info', `${agent} Token 统计: ${total} tokens`)
      break
    }
    case 'summary': {
      const s = d.success
      push(s ? 'success' : 'error', `${agent} 摘要: ${s ? '成功' : '失败'}${d.summary ? ` — ${truncate(typeof d.summary === 'string' ? d.summary : '', 150)}` : ''}`)
      break
    }
    case 'done': {
      const s = d.success
      const tasks = d.tasks_total != null ? ` ${d.tasks_verified ?? 0}/${d.tasks_total} 任务通过` : ''
      push(s ? 'success' : 'error', `${agent} ${s ? '✅ 执行成功' : '❌ 执行失败'}${tasks}`)
      if (!s && d.failure_reason) push('error', `  原因: ${truncate(d.failure_reason, 200)}`)
      break
    }
    default:
      push('info', `${agent} ${log.type}${Object.keys(d).length > 0 ? ` ${truncate(JSON.stringify(d), 120)}` : ''}`)
  }

  return lines
}

function truncate(s, max) {
  if (!s || s.length <= max) return s || ''
  return s.slice(0, max) + '…'
}

function fmtDuration(s) {
  if (s >= 60) return `${Math.floor(s / 60)}m${Math.round(s % 60)}s`
  return `${Math.round(s)}s`
}

const CATEGORY_FILTERS = {
  all: '全部',
  lifecycle: '生命周期',
  planning: '规划',
  task: '任务',
  error: '错误',
}

function getCategory(type) {
  if (['phase_start', 'done', 'sandbox_preparing', 'sandbox_ready', 'redefine_start', 'add_feature_start', 'token_session', 'summary', 'preview_ready'].includes(type)) return 'lifecycle'
  if (type.startsWith('planning') || type === 'plan_ready' || type === 'complexity_assessed') return 'planning'
  if (type.startsWith('task_') || type === 'file_created' || type === 'bug_fix_start' || type === 'test_result' || type === 'dev_self_test' || type === 'smoke_check_failed' || type === 'deploy_gate') return 'task'
  if (['error', 'execution_failed', 'failure_analysis'].includes(type)) return 'error'
  return 'lifecycle'
}

export default function LogTab() {
  const theme = useStore(s => s.theme)
  const isDark = theme === 'dark'
  const executionLogs = useStore(s => s.executionLogs)
  const isRunning = useStore(s => s.isRunning)

  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('all')
  const [autoScroll, setAutoScroll] = useState(true)

  const containerRef = useRef(null)
  const prevCountRef = useRef(0)

  const rendered = useMemo(() => {
    let logs = executionLogs
    if (category !== 'all') {
      logs = logs.filter(l => getCategory(l.type) === category)
    }
    // sandbox_preparing 只保留最后一条（progress 步骤事件合并为单行）
    const lastSandboxIdx = logs.reduce((last, l, i) => l.type === 'sandbox_preparing' ? i : last, -1)
    const result = []
    for (let i = 0; i < logs.length; i++) {
      const log = logs[i]
      if (log.type === 'sandbox_preparing' && i !== lastSandboxIdx) continue
      const lines = formatEvent(log)
      for (const line of lines) {
        result.push({ id: `${log.id}-${result.length}`, time: log.timestamp, ...line })
      }
    }
    if (search) {
      const q = search.toLowerCase()
      return result.filter(r => r.text.toLowerCase().includes(q))
    }
    return result
  }, [executionLogs, category, search])

  useEffect(() => {
    if (autoScroll && containerRef.current && rendered.length > prevCountRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight
    }
    prevCountRef.current = rendered.length
  }, [rendered.length, autoScroll])

  const dimColor = isDark ? '#6e7681' : '#8c959f'

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div style={{
        padding: '6px 12px',
        display: 'flex', alignItems: 'center', gap: 8,
        borderBottom: `1px solid ${isDark ? '#21262d' : '#eef1f4'}`,
      }}>
        <Input
          prefix={<SearchOutlined style={{ color: dimColor }} />}
          placeholder="搜索..."
          size="small"
          allowClear
          style={{ width: 160, fontSize: 12 }}
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
        <div style={{ display: 'flex', gap: 4 }}>
          {Object.entries(CATEGORY_FILTERS).map(([key, label]) => (
            <Tag
              key={key}
              style={{
                cursor: 'pointer', fontSize: 11, margin: 0,
                opacity: category === key ? 1 : 0.5,
                border: category === key ? undefined : '1px dashed',
              }}
              color={category === key ? 'processing' : 'default'}
              onClick={() => setCategory(key)}
            >
              {label}
            </Tag>
          ))}
        </div>
        <div style={{ flex: 1 }} />
        <span style={{ color: dimColor, fontSize: 11 }}>
          {rendered.length} 行
        </span>
        <Tooltip title={autoScroll ? '自动滚动：开' : '自动滚动：关'}>
          <Switch
            size="small"
            checked={autoScroll}
            onChange={setAutoScroll}
            checkedChildren={<VerticalAlignBottomOutlined />}
            unCheckedChildren={<PauseCircleOutlined />}
          />
        </Tooltip>
      </div>

      <div
        ref={containerRef}
        style={{
          flex: 1, overflow: 'auto',
          background: isDark ? '#0d1117' : '#fafbfc',
          fontFamily: 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace',
          fontSize: 12,
          lineHeight: 1.7,
          padding: '8px 0',
        }}
      >
        {rendered.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={executionLogs.length === 0
              ? (isRunning ? '等待事件...' : '暂无日志，执行任务后显示')
              : '没有匹配的内容'
            }
            style={{ marginTop: 60 }}
          />
        ) : (
          rendered.map(line => (
            <div
              key={line.id}
              style={{
                padding: '0 16px',
                display: 'flex',
                gap: 10,
                ...(line.level === 'error' ? { background: isDark ? 'rgba(248,81,73,0.08)' : 'rgba(248,81,73,0.06)' } : {}),
                ...(line.level === 'phase' ? { marginTop: 4, marginBottom: 2 } : {}),
              }}
            >
              <span style={{ color: dimColor, flexShrink: 0, userSelect: 'none' }}>{line.time}</span>
              <span style={{
                ...LEVEL_STYLES[line.level] || LEVEL_STYLES.info,
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
              }}>
                {line.text}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
