import { useEffect, useRef, useState } from 'react'
import { Input, Tag, Empty, Button, Tooltip } from 'antd'
import {
  SearchOutlined,
  DownOutlined,
  VerticalAlignBottomOutlined,
} from '@ant-design/icons'
import useStore from '../../stores/useStore'
import PhaseProgress from '../shared/PhaseProgress'

const AGENT_COLORS = {
  'PM Agent': '#58a6ff',
  'Developer Agent': '#3fb950',
  'Tester Agent': '#d29922',
  'system': '#8b949e',
  'loop': '#bc8cff',
  'refiner': '#f778ba',
}

const EVENT_LABELS = {
  phase_start: '阶段',
  plan_ready: '计划就绪',
  task_start: '任务开始',
  task_complete: '任务完成',
  task_verified: '任务验证',
  test_result: '测试结果',
  file_created: '文件创建',
  tool_call: '工具调用',
  tool_result: '工具结果',
  agent_log: '日志',
  bug_fix_start: '修复开始',
  bug_fix_done: '修复完成',
  reflection: '反思',
  failure_analysis: '失败分析',
  iteration_done: '迭代完成',
  loop_start: '循环开始',
  loop_done: '循环结束',
  summary: '总结',
  done: '完成',
  error: '错误',
  quick_fix_start: '快速修复',
  quick_fix_done: '修复完成',
  resume_start: '恢复执行',
  retest_start: '重新测试',
  revise_start: '调整需求',
  preview_ready: '预览就绪',
  execution_start: '执行开始',
  execution_complete: '执行完成',
  token_session: 'Token',
  complexity_assessed: '复杂度',
}

function getAgentColor(agent) {
  return AGENT_COLORS[agent] || '#8b949e'
}

function formatLogMessage(log) {
  const { type, data, agent } = log
  switch (type) {
    case 'agent_log':
      return data.message || ''
    case 'phase_start':
      return `${data.title || data.phase || ''}${data.color ? '' : ''}`
    case 'plan_ready':
      return `项目计划就绪 — ${data.tasks?.length || 0} 个任务`
    case 'task_start':
      return `开始: ${data.title || data.task_id}`
    case 'task_complete':
      return `完成: ${data.title || data.task_id} ${data.success === false ? '(失败)' : ''}`
    case 'task_verified':
      return `验证: ${data.task_id} — ${data.passes ? 'PASS' : 'FAIL'}`
    case 'test_result':
      return `测试 ${data.passed ? '通过' : '未通过'} — ${data.verified_tasks || data.tests_passed || 0}/${data.total_tasks || data.tests_total || 0}, Bug: ${data.bug_count || 0}`
    case 'file_created':
      return `创建文件: ${data.path || data.file}`
    case 'tool_call':
      return `调用: ${data.tool}${data.args ? ` ${data.args.slice(0, 100)}` : ''}`
    case 'tool_result':
      return `结果: ${data.tool} — ${(data.result || '').slice(0, 120)}`
    case 'done':
      return `执行${data.success ? '成功' : '结束'}${data.summary ? ` — ${data.summary}` : ''}`
    case 'error':
      return data.message || '未知错误'
    case 'summary':
      return `总结: 任务 ${data.tasks_completed}/${data.tasks_total}, Token: ${data.total_tokens || 0}`
    case 'token_session':
      return `Token 记录: ${data.total_tokens || 0} tokens, ${(data.elapsed_seconds || 0).toFixed(1)}s`
    case 'bug_fix_start':
      return `开始修复 ${data.count || 0} 个 Bug`
    case 'bug_fix_done':
      return `修复完成: ${data.fixed}/${data.total}`
    case 'reflection':
      return `反思: ${(data.content || '').slice(0, 150)}`
    case 'failure_analysis':
      return `失败分析: ${(data.patterns || []).join(', ')}`
    case 'execution_start':
      return `开始执行 ${data.task_count || 0} 个任务`
    case 'complexity_assessed':
      return `复杂度评估: ${data.complexity}`
    case 'preview_ready':
      return `预览${data.available ? '就绪' : '不可用'}${data.url ? `: ${data.url}` : ''}`
    default:
      return data.message || type
  }
}

function getTypeTag(type, isDark) {
  const label = EVENT_LABELS[type] || type
  let color = 'default'
  if (type === 'error') color = 'error'
  else if (type === 'done' || type === 'summary') color = 'success'
  else if (type === 'test_result') color = 'warning'
  else if (type === 'phase_start') color = 'processing'
  else if (type === 'file_created') color = 'cyan'
  else if (type.includes('task')) color = 'blue'
  return <Tag color={color} style={{ margin: 0, fontSize: 10, lineHeight: '16px', padding: '0 4px' }}>{label}</Tag>
}

export default function MonitorTab() {
  const theme = useStore((s) => s.theme)
  const logs = useStore((s) => s.executionLogs)
  const isRunning = useStore((s) => s.isRunning)
  const isDark = theme === 'dark'

  const logsEndRef = useRef(null)
  const containerRef = useRef(null)
  const [autoScroll, setAutoScroll] = useState(true)
  const [search, setSearch] = useState('')
  const [expandedTools, setExpandedTools] = useState(new Set())

  useEffect(() => {
    if (autoScroll && logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [logs.length, autoScroll])

  const handleScroll = () => {
    if (!containerRef.current) return
    const { scrollTop, scrollHeight, clientHeight } = containerRef.current
    setAutoScroll(scrollHeight - scrollTop - clientHeight < 80)
  }

  const toggleTool = (id) => {
    setExpandedTools((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  const filteredLogs = search
    ? logs.filter((l) => {
        const msg = formatLogMessage(l).toLowerCase()
        const agent = (l.agent || '').toLowerCase()
        const q = search.toLowerCase()
        return msg.includes(q) || agent.includes(q) || l.type.includes(q)
      })
    : logs

  // 隐藏高频低价值事件
  const visibleLogs = filteredLogs.filter(
    (l) => !['heartbeat', 'thinking', 'auto_lint_fix_start', 'auto_lint_fix_done', 'token_budget_exceeded'].includes(l.type)
  )

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <PhaseProgress />

      {/* 搜索栏 */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 8, alignItems: 'center' }}>
        <Input
          prefix={<SearchOutlined style={{ color: isDark ? '#484f58' : '#bbb' }} />}
          placeholder="搜索日志..."
          size="small"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          allowClear
          style={{ flex: 1 }}
        />
        {!autoScroll && (
          <Tooltip title="滚动到底部">
            <Button
              size="small"
              icon={<VerticalAlignBottomOutlined />}
              onClick={() => {
                setAutoScroll(true)
                logsEndRef.current?.scrollIntoView({ behavior: 'smooth' })
              }}
            />
          </Tooltip>
        )}
      </div>

      {/* 日志列表 */}
      <div
        ref={containerRef}
        onScroll={handleScroll}
        style={{
          flex: 1,
          overflow: 'auto',
          borderRadius: 6,
          border: `1px solid ${isDark ? '#21262d' : '#e8e8e8'}`,
          background: isDark ? '#010409' : '#fafafa',
          fontFamily: 'Menlo, Monaco, Consolas, monospace',
          fontSize: 12,
          lineHeight: '20px',
        }}
      >
        {visibleLogs.length === 0 ? (
          <div style={{ padding: 32 }}>
            <Empty
              description={isRunning ? '等待执行事件...' : '暂无执行日志'}
              image={Empty.PRESENTED_IMAGE_SIMPLE}
            />
          </div>
        ) : (
          <div style={{ padding: '4px 0' }}>
            {visibleLogs.map((log) => {
              const agentColor = getAgentColor(log.agent)
              const isToolEvent = log.type === 'tool_call' || log.type === 'tool_result'
              const isExpanded = expandedTools.has(log.id)

              return (
                <div
                  key={log.id}
                  style={{
                    display: 'flex',
                    alignItems: 'flex-start',
                    padding: '2px 8px',
                    gap: 6,
                    borderBottom: log.type === 'phase_start' ? `1px solid ${isDark ? '#21262d' : '#e8e8e8'}` : 'none',
                    background: log.type === 'phase_start' ? (isDark ? '#0d111799' : '#f0f0f0') : 'transparent',
                  }}
                >
                  <span style={{ color: isDark ? '#484f58' : '#bbb', fontSize: 10, flexShrink: 0, width: 56, textAlign: 'right', lineHeight: '20px', fontVariantNumeric: 'tabular-nums' }}>
                    {log.timestamp}
                  </span>
                  <span style={{ flexShrink: 0 }}>{getTypeTag(log.type, isDark)}</span>
                  <span style={{ color: agentColor, fontWeight: 600, flexShrink: 0, fontSize: 11, lineHeight: '20px', minWidth: 24 }}>
                    {log.agent === 'system' ? 'SYS' : log.agent?.replace(' Agent', '').slice(0, 6)}
                  </span>
                  <span
                    style={{
                      flex: 1,
                      color: log.type === 'error' ? '#f85149' : (isDark ? '#c9d1d9' : '#1f2328'),
                      wordBreak: 'break-word',
                      cursor: isToolEvent ? 'pointer' : 'default',
                      lineHeight: '20px',
                    }}
                    onClick={isToolEvent ? () => toggleTool(log.id) : undefined}
                  >
                    {formatLogMessage(log)}
                    {isToolEvent && !isExpanded && (
                      <DownOutlined style={{ fontSize: 8, marginLeft: 4, opacity: 0.5 }} />
                    )}
                    {isToolEvent && isExpanded && log.data?.result && (
                      <pre style={{
                        margin: '4px 0 0',
                        padding: 8,
                        borderRadius: 4,
                        background: isDark ? '#0d1117' : '#f6f8fa',
                        fontSize: 11,
                        maxHeight: 200,
                        overflow: 'auto',
                        whiteSpace: 'pre-wrap',
                        wordBreak: 'break-all',
                        border: `1px solid ${isDark ? '#21262d' : '#e8e8e8'}`,
                      }}>
                        {log.data.result}
                      </pre>
                    )}
                  </span>
                </div>
              )
            })}
            <div ref={logsEndRef} />
          </div>
        )}

        {/* 运行中光标 */}
        {isRunning && (
          <div style={{ padding: '4px 8px', display: 'flex', alignItems: 'center', gap: 4 }}>
            <span
              style={{
                display: 'inline-block',
                width: 6,
                height: 14,
                background: '#58a6ff',
                animation: 'blink 1s step-end infinite',
              }}
            />
          </div>
        )}
      </div>

      <style>{`
        @keyframes blink {
          0%, 100% { opacity: 1; }
          50% { opacity: 0; }
        }
      `}</style>
    </div>
  )
}
