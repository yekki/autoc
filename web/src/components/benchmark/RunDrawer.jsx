import { useState, useEffect, useRef, useMemo } from 'react'
import { Drawer, Form, Input, Button, Switch, InputNumber, Checkbox, Collapse, message, Tag, Tooltip } from 'antd'
import {
  PlayCircleOutlined, LoadingOutlined, CheckCircleOutlined, CloseCircleOutlined,
  DownOutlined, RightOutlined, FileOutlined,
} from '@ant-design/icons'
import useStore from '../../stores/useStore'

const COLORS = {
  green: '#3fb950',
  red: '#f85149',
  yellow: '#d29922',
  dark: { dim: '#6e7681', blue: '#58a6ff', text: '#c9d1d9', muted: '#8b949e', border: '#30363d', bg: '#0d1117', bgCard: '#161b22', purple: '#bc8cff', dimBorder: '#484f58', activeBg: '#1f3248', trail: '#21262d' },
  light: { dim: '#8c959f', blue: '#0969da', text: '#1f2328', muted: '#656d76', border: '#d0d7de', bg: '#f6f8fa', bgCard: '#f6f8fa', purple: '#8250df', dimBorder: '#d0d7de', activeBg: '#dbeafe', trail: '#e1e4e8' },
}
function useColors(isDark) {
  const t = isDark ? COLORS.dark : COLORS.light
  return { ...t, green: COLORS.green, red: COLORS.red, yellow: COLORS.yellow }
}

// ─────────────────────────────────────────────────────────────
// 沙箱步骤中文映射
// ─────────────────────────────────────────────────────────────
const SANDBOX_STEP_LABELS = {
  init: '初始化',
  docker_check: '检查 Docker',
  docker_ok: 'Docker 就绪',
  image_check: '检查镜像',
  image_pull: '拉取镜像',
  image_ready: '镜像就绪',
  sandbox_ready: '就绪',
}

// ─────────────────────────────────────────────────────────────
// 工具调用中文标签
// ─────────────────────────────────────────────────────────────
const TOOL_LABELS = {
  read_file: '读文件',
  write_file: '写文件',
  edit_file: '编辑文件',
  create_directory: '创建目录',
  list_files: '列出文件',
  glob_files: 'glob搜索',
  search_in_files: '搜索代码',
  execute_command: '执行命令',
  send_input: '发送输入',
  git_diff: 'git diff',
  git_log: 'git log',
  git_status: 'git status',
  format_code: '格式化代码',
  lint_code: 'Lint检查',
  think: '思考',
  ask_helper: '请教助手',
  submit_test_report: '提交测试报告',
  submit_critique: '提交评审',
}

// ─────────────────────────────────────────────────────────────
// 格式化 case_event 为 { text, color, icon, indent }
// ─────────────────────────────────────────────────────────────
function formatCaseEvent(evt, isDark) {
  const { event_type, data = {} } = evt
  const t = isDark ? COLORS.dark : COLORS.light
  const dim = t.dim, green = COLORS.green, blue = t.blue
  const yellow = COLORS.yellow, red = COLORS.red, purple = t.purple

  switch (event_type) {
    case 'sandbox_preparing': {
      const msg = data.message || SANDBOX_STEP_LABELS[data.step] || '准备中...'
      return { text: `⏳ 沙箱: ${msg}`, color: dim, indent: 0, isSandbox: true }
    }
    case 'sandbox_ready':
      return { text: '✓ 沙箱就绪', color: green, indent: 0 }
    case 'planning_analyzing':
      return { text: '📋 分析需求...', color: dim, indent: 0 }
    case 'plan_ready':
      return { text: `✓ 计划就绪 (${data.plan_length || 0} 字)`, color: green, indent: 0 }
    case 'phase_start':
      return { text: `▸ ${data.phase || ''}: ${data.title || ''}`, color: blue, indent: 0, isPhase: true }
    case 'iteration_start':
      return { text: `  迭代 ${data.iteration ?? '?'} — ${data.phase || ''}`, color: dim, indent: 1 }
    case 'iteration_done': {
      const ok = data.success
      const secs = data.elapsed_seconds != null ? ` (${Number(data.elapsed_seconds).toFixed(1)}s)` : ''
      return { text: `  ${ok ? '✓' : '⚠'} ${data.phase || ''}${secs}`, color: ok ? green : yellow, indent: 1 }
    }
    case 'task_start':
      return { text: `  ⚙ ${data.task_title || data.task_id || '任务'}`, color: blue, indent: 1, isTask: true }
    case 'task_complete': {
      const ok = data.success !== false
      const tok = data.tokens_used ? ` · ${data.tokens_used.toLocaleString()} tok` : ''
      return {
        text: `  ${ok ? '✓' : '✗'} ${data.task_title || data.task_id || '任务'}${tok}`,
        color: ok ? green : red, indent: 1,
      }
    }
    case 'task_verified': {
      const ok = data.passes
      return { text: `  ${ok ? '✓ 验证通过' : '✗ 验证未通过'}: ${data.task_id || ''}`, color: ok ? green : yellow, indent: 1 }
    }
    case 'file_created': {
      const lang = data.language ? ` [${data.language}]` : ''
      return { text: `  📄 ${data.path || ''}${lang}`, color: purple, indent: 1, isFile: true }
    }
    case 'test_result': {
      const bugs = data.bug_count || 0
      const vt = data.verified_tasks || 0
      const tt = data.total_tasks || 0
      if (bugs > 0) return { text: `  🐛 测试: ${vt}/${tt} 通过，${bugs} 个问题`, color: yellow, indent: 1 }
      if (tt > 0) return { text: `  ✓ 测试: ${vt}/${tt} 全部通过`, color: green, indent: 1 }
      return { text: '  ✓ 测试通过', color: green, indent: 1 }
    }
    case 'tool_call': {
      const toolName = TOOL_LABELS[data.tool] || data.tool || '工具调用'
      const args = data.args ? ` ${data.args}` : ''
      return { text: `  🔧 ${toolName}${args}`, color: dim, indent: 1, isToolCall: true }
    }
    case 'execution_complete':
      return { text: '✅ 执行完成', color: green, indent: 0 }
    case 'execution_failed':
      return { text: `❌ 失败: ${data.failure_reason || ''}`, color: red, indent: 0 }
    case 'summary':
      return { text: '📊 生成总结...', color: dim, indent: 0 }
    case 'done':
      return data.success
        ? { text: '✅ 全流程完成', color: green, indent: 0 }
        : { text: '❌ 全流程结束', color: red, indent: 0 }
    default:
      return { text: event_type, color: dim, indent: 0 }
  }
}

// ─────────────────────────────────────────────────────────────
// 实时计时器
// ─────────────────────────────────────────────────────────────
function ElapsedTimer({ startMs, isActive, finalSeconds, isDark }) {
  const [elapsed, setElapsed] = useState(0)
  useEffect(() => {
    if (finalSeconds != null) { setElapsed(Math.round(finalSeconds)); return }
    if (!startMs) return
    setElapsed(Math.floor((Date.now() - startMs) / 1000))
    if (!isActive) return
    const t = setInterval(() => setElapsed(Math.floor((Date.now() - startMs) / 1000)), 1000)
    return () => clearInterval(t)
  }, [startMs, isActive, finalSeconds])
  const m = Math.floor(elapsed / 60)
  const s = elapsed % 60
  const text = m > 0 ? `${m}m ${String(s).padStart(2, '0')}s` : `${s}s`
  return <span style={{ fontSize: 12, color: isDark ? '#6e7681' : '#8c959f', fontVariantNumeric: 'tabular-nums' }}>⏱ {text}</span>
}

// ─────────────────────────────────────────────────────────────
// Phase 步骤指示器（当前用例）
// ─────────────────────────────────────────────────────────────
function computePhaseStates(caseEvents) {
  const evtTypes = new Set(caseEvents.map(e => e.event_type))
  const phaseData = caseEvents.filter(e => e.event_type === 'iteration_done').map(e => e.data?.phase)

  const phases = [
    {
      id: 'plan', label: '规划',
      active: evtTypes.has('planning_analyzing'),
      done: evtTypes.has('plan_ready'),
    },
    {
      id: 'sandbox', label: '沙箱',
      active: evtTypes.has('sandbox_preparing'),
      done: evtTypes.has('sandbox_ready'),
    },
    {
      id: 'dev', label: '开发',
      active: evtTypes.has('task_start') || (evtTypes.has('phase_start') && caseEvents.some(e => e.event_type === 'phase_start' && (e.data?.phase || '').includes('dev'))),
      done: phaseData.includes('dev') || evtTypes.has('execution_complete'),
    },
    {
      id: 'test', label: '测试',
      active: evtTypes.has('test_result') || phaseData.includes('test'),
      done: evtTypes.has('test_result') || (evtTypes.has('execution_complete') && phaseData.includes('test')),
    },
    {
      id: 'done', label: '总结',
      active: evtTypes.has('summary'),
      done: evtTypes.has('done'),
    },
  ]
  return phases
}

function PhaseStepBar({ caseEvents, isDark }) {
  const phases = useMemo(() => computePhaseStates(caseEvents), [caseEvents])
  const c = useColors(isDark)

  const active = phases.filter(p => p.active || p.done)
  if (active.length === 0) return null

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 0, fontSize: 11, flexWrap: 'wrap', rowGap: 2 }}>
      {phases.map((p, i) => {
        const status = p.done ? 'done' : p.active ? 'active' : 'pending'
        const color = status === 'done' ? c.green : status === 'active' ? c.blue : c.dim
        const bg = status === 'active' ? c.activeBg : 'transparent'
        const mark = status === 'done' ? '✓' : status === 'active' ? '▸' : '○'
        return (
          <span key={p.id} style={{ display: 'flex', alignItems: 'center', gap: 0 }}>
            {i > 0 && <span style={{ color: c.dimBorder, padding: '0 3px' }}>›</span>}
            <span style={{
              color, background: bg, borderRadius: 3, padding: '1px 5px',
              fontWeight: status === 'active' ? 700 : 400,
              transition: 'all 0.2s',
            }}>
              {mark} {p.label}
            </span>
          </span>
        )
      })}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────
// 按 repeat 轮次分组事件（仅 case_event 类型）
// ─────────────────────────────────────────────────────────────
function groupEventsByRound(caseEventList) {
  // 返回 [{num, total, events, isActive}]
  const rounds = []
  let cur = { num: 1, total: 1, events: [] }

  for (const evt of caseEventList) {
    if (evt.type === 'case_event' && evt.event_type === 'repeat_round') {
      if (rounds.length > 0 || cur.events.length > 0) {
        rounds.push({ ...cur, isActive: false })
      }
      cur = { num: evt.data?.run_index ?? rounds.length + 1, total: evt.data?.total_runs ?? 1, events: [] }
    } else {
      cur.events.push(evt)
    }
  }
  rounds.push({ ...cur, isActive: true })
  return rounds
}

// ─────────────────────────────────────────────────────────────
// 对 case_event 列表做前处理：sandbox_preparing 只保留最新步骤
// （tool_call 去重由 RoundEventList 渲染时用前瞻逻辑处理，避免索引突变导致乱序）
// ─────────────────────────────────────────────────────────────
function deduplicateSandboxEvents(events) {
  const result = []
  for (const evt of events) {
    if (evt.type === 'case_event' && evt.event_type === 'sandbox_preparing') {
      let lastIdx = -1
      for (let i = result.length - 1; i >= 0; i--) {
        if (result[i].type === 'case_event' && result[i].event_type === 'sandbox_preparing') {
          lastIdx = i; break
        }
      }
      if (lastIdx >= 0) result[lastIdx] = evt
      else result.push(evt)
    } else {
      result.push(evt)
    }
  }
  return result
}

// ─────────────────────────────────────────────────────────────
// 单轮次事件渲染
// ─────────────────────────────────────────────────────────────
function RoundEventList({ events, isDark }) {
  const clr = useColors(isDark)
  const rendered = []
  let fileGroup = []

  const flushFiles = () => {
    if (fileGroup.length === 0) return
    const files = fileGroup.map(e => e.data?.path || '').filter(Boolean)
    rendered.push(
      <div key={`files-${rendered.length}`} style={{ color: clr.purple, paddingLeft: 12, display: 'flex', flexWrap: 'wrap', gap: '2px 8px' }}>
        {files.map((f, i) => (
          <span key={i} style={{ display: 'inline-flex', alignItems: 'center', gap: 3 }}>
            <FileOutlined style={{ fontSize: 10 }} />{f}
          </span>
        ))}
      </div>
    )
    fileGroup = []
  }

  const deduped = deduplicateSandboxEvents(events.filter(e => e.type === 'case_event'))

  for (let i = 0; i < deduped.length; i++) {
    const evt = deduped[i]

    if (evt.event_type === 'file_created') {
      fileGroup.push(evt)
      const next = deduped[i + 1]
      if (!next || next.event_type !== 'file_created') flushFiles()
      continue
    }

    flushFiles()

    if (evt.event_type === 'execution_complete') continue

    // 连续 tool_call 只显示最后一条（前瞻：下一条仍是 tool_call 则跳过；下一条是 iteration_done 时保留）
    if (evt.event_type === 'tool_call') {
      const next = deduped[i + 1]
      if (next?.event_type === 'tool_call') continue
    }

    const { text, color, indent } = formatCaseEvent(evt, isDark)
    rendered.push(
      <div key={i} style={{
        color, paddingLeft: indent ? 12 : 0,
        ...(evt.event_type === 'tool_call' ? { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } : {}),
      }}>{text}</div>
    )
  }

  flushFiles()
  return <>{rendered}</>
}

// ─────────────────────────────────────────────────────────────
// 用例事件块（包含 repeat 轮次折叠）
// ─────────────────────────────────────────────────────────────
function CaseEventBlock({ caseIdx, caseStartEvt, caseEvents, caseDoneEvt, isDark, isRunning }) {
  const [collapsedRounds, setCollapsedRounds] = useState(new Set())
  const prevRoundCountRef = useRef(0)

  const toggleRound = (key) => {
    setCollapsedRounds(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const c = useColors(isDark)

  // 判断是否有 repeat_round 事件
  const hasRepeats = caseEvents.some(e => e.type === 'case_event' && e.event_type === 'repeat_round')
  const rounds = hasRepeats ? groupEventsByRound(caseEvents) : null
  const isCaseDone = !!caseDoneEvt

  // 新轮次出现时自动折叠已完成的轮次
  useEffect(() => {
    if (!rounds || rounds.length <= 1) return
    const doneCount = rounds.length - 1
    if (doneCount > prevRoundCountRef.current) {
      setCollapsedRounds(prev => {
        const next = new Set(prev)
        for (let i = 0; i < doneCount; i++) next.add(`${caseIdx}-${i}`)
        return next
      })
    }
    prevRoundCountRef.current = doneCount
  }, [rounds?.length, caseIdx]) // eslint-disable-line

  // Phase 指示器：非 repeat 模式取全部事件，repeat 模式取当前（最后）轮次的事件
  const phaseSourceEvents = useMemo(() => {
    if (!hasRepeats || !rounds || rounds.length === 0) {
      return caseEvents.filter(e => e.type === 'case_event')
    }
    const activeRound = rounds[rounds.length - 1]
    return (activeRound?.events || []).filter(e => e.type === 'case_event')
  }, [caseEvents, hasRepeats, rounds])

  return (
    <div style={{ marginBottom: 8 }}>
      {/* Case 标题行 */}
      <div style={{ color: c.blue, fontWeight: 600, paddingTop: caseIdx > 0 ? 6 : 0, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span>▸ {caseStartEvt.case}</span>
        {caseStartEvt.total > 1 && (
          <span style={{ fontSize: 11, fontWeight: 400, color: c.dim }}>{caseStartEvt.index + 1}/{caseStartEvt.total}</span>
        )}
      </div>

      {/* Phase 步骤指示器 */}
      {phaseSourceEvents.length > 0 && (
        <div style={{ paddingLeft: 0, marginTop: 3, marginBottom: 4 }}>
          <PhaseStepBar caseEvents={phaseSourceEvents} isDark={isDark} />
        </div>
      )}

      {/* 事件内容：有 repeat 分轮次，否则直接列 */}
      {hasRepeats && rounds ? (
        rounds.map((round, ri) => {
          const roundKey = `${caseIdx}-${ri}`
          const isCollapsed = collapsedRounds.has(roundKey)
          const isLastRound = ri === rounds.length - 1

          // 当前轮摘要（用 iteration_done 的耗时）
          const doneEvt = round.events.filter(e => e.type === 'case_event' && e.event_type === 'iteration_done').at(-1)
          const elapsed = doneEvt?.data?.elapsed_seconds ? `${Number(doneEvt.data.elapsed_seconds).toFixed(1)}s` : null
          const isRoundDone = !isLastRound || isCaseDone

          return (
            <div key={ri} style={{ marginLeft: 0 }}>
              {/* 轮次标题（可点击折叠） */}
              <div
                onClick={() => isRoundDone && toggleRound(roundKey)}
                style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  color: isRoundDone ? c.muted : c.blue,
                  marginTop: 4, cursor: isRoundDone ? 'pointer' : 'default',
                  userSelect: 'none',
                }}
              >
                <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  {isRoundDone
                    ? (isCollapsed ? <RightOutlined style={{ fontSize: 9 }} /> : <DownOutlined style={{ fontSize: 9 }} />)
                    : <LoadingOutlined style={{ fontSize: 9 }} />
                  }
                  {` 第 ${round.num}/${round.total} 次运行`}
                </span>
                {elapsed && isRoundDone && (
                  <span style={{ fontSize: 11, color: c.dim }}>{elapsed}</span>
                )}
              </div>

              {/* 轮次内容 */}
              {!isCollapsed && (
                <div style={{ paddingLeft: 12 }}>
                  <RoundEventList events={round.events} isDark={isDark} />
                  {!isRoundDone && isRunning && (
                    <div style={{ color: c.dim, paddingLeft: 0 }}>⟳ 进行中...</div>
                  )}
                </div>
              )}
            </div>
          )
        })
      ) : (
        <div style={{ paddingLeft: 0 }}>
          <RoundEventList events={caseEvents} isDark={isDark} />
          {!isCaseDone && isRunning && (
            <div style={{ color: c.dim, paddingLeft: 0 }}>⟳ 进行中...</div>
          )}
        </div>
      )}

      {/* Case 完成行 */}
      {caseDoneEvt && (
        <div style={{ color: caseDoneEvt.success ? c.green : c.red, fontWeight: 500, marginTop: 2 }}>
          {caseDoneEvt.success ? '✓' : '✗'} {caseDoneEvt.case}
          {caseDoneEvt.tokens != null && ` — ${caseDoneEvt.tokens.toLocaleString()} tok`}
          {caseDoneEvt.elapsed != null && ` · ${Number(caseDoneEvt.elapsed).toFixed(1)}s`}
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────
// 主组件
// ─────────────────────────────────────────────────────────────
export default function RunDrawer({ open, onClose }) {
  const theme = useStore((s) => s.theme)
  const running = useStore((s) => s.benchmarkRunning)
  const progress = useStore((s) => s.benchmarkRunProgress)
  const startRun = useStore((s) => s.startBenchmarkRun)
  const fetchCases = useStore((s) => s.fetchBenchmarkCases)
  const cases = useStore((s) => s.benchmarkCases)
  const fetchDetail = useStore((s) => s.fetchBenchmarkDetail)
  const setBenchmarkProgress = useStore((s) => s.setBenchmarkProgress)
  const isDark = theme === 'dark'

  const [form] = Form.useForm()
  const [casesReady, setCasesReady] = useState(false)
  const [etaTick, setEtaTick] = useState(0)  // 每秒 +1，驱动 ETA 重新计算
  const logRef = useRef(null)
  const runTagRef = useRef(null)
  const prevIsCompleteRef = useRef(false)
  const prevIsErrorRef = useRef(false)
  // 记录运行开始时间（用于实时计时）
  const runStartMsRef = useRef(null)

  const c = useColors(isDark)

  useEffect(() => {
    if (!open) return
    const lastType = progress?.lastEvent?.type
    if (lastType === 'run_complete' || lastType === 'run_error') {
      setBenchmarkProgress(null)
      form.resetFields()
      setCasesReady(false)
      runStartMsRef.current = null
    }
    if (!cases.length) {
      fetchCases().then(() => setCasesReady(true))
    } else {
      setCasesReady(true)
    }
  }, [open]) // eslint-disable-line

  // 记录运行开始时间（首个 run_start 事件到达时标记）
  useEffect(() => {
    if (running && !runStartMsRef.current) {
      runStartMsRef.current = Date.now()
    }
  }, [running])

  // 运行中每秒更新 etaTick，驱动 ETA 重新计算
  useEffect(() => {
    if (!running) return
    const id = setInterval(() => setEtaTick((t) => t + 1), 1000)
    return () => clearInterval(id)
  }, [running])

  const coreCases = cases.filter((x) => x.is_core).map((x) => x.name)
  const allCaseNames = cases.map((x) => x.name)

  useEffect(() => {
    if (casesReady && coreCases.length > 0) {
      const current = form.getFieldValue('cases')
      if (!current || current.length === 0) form.setFieldValue('cases', coreCases)
    }
  }, [casesReady, coreCases.join(',')]) // eslint-disable-line

  const handleSubmit = async () => {
    let values
    try { values = await form.validateFields() } catch { return }
    const config = {
      tag: values.tag,
      description: values.description || '',
      cases: (values.cases || []).join(','),
      critique: values.critique || false,
      timeout: values.timeout || 600,
      repeat: values.repeat || 1,
      force: values.force || false,
      workers: values.workers || 1,
    }
    runTagRef.current = values.tag
    prevIsCompleteRef.current = false
    runStartMsRef.current = null
    startRun(config).catch((e) => {
      if (e.message) message.error(e.message)
      runTagRef.current = null
    })
  }

  const events = progress?.events || []
  const lastEvent = progress?.lastEvent
  const isComplete = lastEvent?.type === 'run_complete'
  const isError = lastEvent?.type === 'run_error'
  const isDisconnected = progress?.status === 'disconnected'
  const progressTag = progress?.tag || events.find((e) => e.tag)?.tag

  useEffect(() => {
    if (isComplete && !prevIsCompleteRef.current && runTagRef.current) {
      message.success('Benchmark 运行完成')
      fetchDetail(runTagRef.current)
      runTagRef.current = null
    }
    prevIsCompleteRef.current = isComplete
  }, [isComplete]) // eslint-disable-line

  useEffect(() => {
    if (isError && !prevIsErrorRef.current && runTagRef.current) {
      fetchDetail(runTagRef.current).catch(() => {})
      runTagRef.current = null
    }
    prevIsErrorRef.current = isError
  }, [isError]) // eslint-disable-line

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [events.length])

  // ── 进度计算 ──
  const startEvt = events.find((e) => e.type === 'run_start')
  const doneEvts = events.filter((e) => e.type === 'case_done')
  const total = startEvt?.total_cases || 0
  const completed = doneEvts.length
  const pct = total > 0 ? Math.round((completed / total) * 100) : 0
  const lastCaseStart = events.filter((e) => e.type === 'case_start').at(-1)

  // ── ETA 预估（根据已完成用例均值推算；etaTick 驱动每秒刷新）──
  const etaText = useMemo(() => {
    if (!running || completed === 0 || !runStartMsRef.current) return null
    const elapsedSec = (Date.now() - runStartMsRef.current) / 1000
    const avgPerCase = elapsedSec / completed
    const remaining = (total - completed) * avgPerCase
    if (remaining <= 0) return null
    const m = Math.floor(remaining / 60)
    const s = Math.round(remaining % 60)
    return m > 0 ? `≈${m}m${s}s` : `≈${s}s`
  }, [running, completed, total, etaTick])

  // ── 用例分组：支持串行与并行模式（并行时按 evt.case 归属）──
  const caseBlocks = useMemo(() => {
    const byCase = new Map()
    const startOrder = []

    for (const evt of events) {
      if (evt.type === 'case_start') {
        const name = evt.case
        if (!byCase.has(name)) {
          byCase.set(name, { startEvt: evt, events: [], doneEvt: null })
          startOrder.push(name)
        }
      } else if (evt.type === 'case_done') {
        const block = byCase.get(evt.case)
        if (block) block.doneEvt = evt
      } else if (evt.type === 'case_event') {
        const block = byCase.get(evt.case)
        if (block) block.events.push(evt)
      }
    }
    return startOrder.map((name) => byCase.get(name)).filter(Boolean)
  }, [events])

  // ── 实时统计：从事件流中聚合 Token / 文件 / 测试 ──
  const liveStats = useMemo(() => {
    let completedTokens = 0
    const runningCases = new Set()
    const caseRunningTokens = new Map()
    let files = 0
    let testPassed = 0
    let testTotal = 0

    for (const evt of events) {
      if (evt.type === 'case_start') {
        runningCases.add(evt.case)
        caseRunningTokens.set(evt.case, 0)
      } else if (evt.type === 'case_done') {
        runningCases.delete(evt.case)
        caseRunningTokens.delete(evt.case)
        completedTokens += evt.tokens || 0
      } else if (evt.type === 'case_event') {
        if (evt.event_type === 'task_complete' && runningCases.has(evt.case) && evt.data?.tokens_used) {
          caseRunningTokens.set(evt.case, (caseRunningTokens.get(evt.case) || 0) + evt.data.tokens_used)
        }
        if (evt.event_type === 'file_created') files++
        if (evt.event_type === 'test_result') {
          testPassed = evt.data?.verified_tasks || 0
          testTotal = evt.data?.total_tasks || 0
        }
      }
    }
    let runningTokens = 0
    for (const v of caseRunningTokens.values()) runningTokens += v
    return { tokens: completedTokens + runningTokens, files, testPassed, testTotal }
  }, [events])

  // ── 是否处于进度模式 ──
  const isProgressMode = running || isComplete || isError || isDisconnected

  return (
    <Drawer
      title={
        progressTag && isProgressMode
          ? `Benchmark 实时进度 — ${progressTag}`
          : '发起 Benchmark 测试'
      }
      open={open}
      onClose={running ? undefined : onClose}
      width={480}
      maskClosable={!running}
      styles={{ body: { display: 'flex', flexDirection: 'column', overflow: 'hidden', padding: '12px 16px' } }}
      extra={!running && isComplete && (
        <Button type="link" size="small" onClick={onClose}>关闭</Button>
      )}
    >
      {/* ═══════════════════════════════ 表单模式 ═══════════════════════════════ */}
      {!isProgressMode ? (
        <div style={{ flex: 1, overflow: 'auto', minHeight: 0 }}>
          <Form
            form={form}
            layout="vertical"
            initialValues={{ cases: coreCases, timeout: 600, repeat: 1, critique: false, force: false, workers: 1 }}
          >
            <Form.Item
              name="tag" label="标签名称"
              rules={[{ required: true, message: '请输入标签' }, { pattern: /^[\w.-]+$/, message: '仅允许字母数字和 .-_' }]}
            >
              <Input placeholder="例如: v1.2-baseline" />
            </Form.Item>

            <Form.Item name="description" label="描述（可选）">
              <Input.TextArea rows={2} placeholder="本次测试的目的或变更说明" />
            </Form.Item>

            <Form.Item name="cases" label="选择用例">
              <Checkbox.Group style={{ width: '100%' }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {allCaseNames.map((name) => (
                    <Checkbox key={name} value={name}>
                      <span style={{ fontSize: 13 }}>{name}</span>
                      {coreCases.includes(name) && <Tag color="blue" style={{ margin: '0 0 0 6px', fontSize: 10 }}>核心</Tag>}
                    </Checkbox>
                  ))}
                </div>
              </Checkbox.Group>
            </Form.Item>

            <Collapse
              ghost size="small"
              items={[{
                key: 'advanced',
                label: <span style={{ fontSize: 12, color: c.dim }}>高级选项</span>,
                children: (
                  <>
                    <Form.Item name="critique" label="Critique 评审" valuePropName="checked" style={{ marginBottom: 12 }}>
                      <Switch size="small" />
                    </Form.Item>
                    <Form.Item name="timeout" label="超时（秒）" style={{ marginBottom: 12 }}>
                      <InputNumber min={60} max={3600} style={{ width: '100%' }} />
                    </Form.Item>
                    <Form.Item name="repeat" label="重复次数" style={{ marginBottom: 12 }}>
                      <InputNumber min={1} max={10} style={{ width: '100%' }} />
                    </Form.Item>
                    <Form.Item
                      name="workers"
                      label={<span>并行 Workers <span style={{ fontSize: 11, color: c.dim, fontWeight: 400 }}>（同时执行多个用例）</span></span>}
                      style={{ marginBottom: 12 }}
                    >
                      <InputNumber min={1} max={8} style={{ width: '100%' }} />
                    </Form.Item>
                    <Form.Item name="force" valuePropName="checked" style={{ marginBottom: 0 }}>
                      <Checkbox><span style={{ fontSize: 12 }}>强制覆盖同名标签</span></Checkbox>
                    </Form.Item>
                  </>
                ),
              }]}
            />

            <div style={{ marginTop: 20 }}>
              <Button type="primary" block icon={<PlayCircleOutlined />} loading={running} onClick={handleSubmit} size="large">
                开始运行
              </Button>
            </div>
          </Form>
        </div>
      ) : (
        /* ═══════════════════════════════ 进度模式 ═══════════════════════════════ */
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, flex: 1, minHeight: 0 }}>

          {/* ── 紧凑状态条 ── */}
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '8px 10px', borderRadius: 6, flexShrink: 0,
            background: c.bgCard,
            border: `1px solid ${c.border}`,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              {running && <LoadingOutlined style={{ fontSize: 14, color: c.blue }} />}
              {isComplete && <CheckCircleOutlined style={{ fontSize: 14, color: c.green }} />}
              {isError && <CloseCircleOutlined style={{ fontSize: 14, color: c.red }} />}
              {isDisconnected && <CloseCircleOutlined style={{ fontSize: 14, color: c.yellow }} />}
              <span style={{ fontSize: 13, fontWeight: 600, color: c.text }}>
                {running ? '运行中' : isComplete ? '运行完成' : isDisconnected ? '连接中断' : '运行失败'}
              </span>
              {isComplete && lastEvent && (
                <span style={{ fontSize: 12, color: c.dim }}>
                  完成率 {((lastEvent.completion_rate || 0) * 100).toFixed(0)}% · {lastEvent.case_count} 用例
                </span>
              )}
              {isError && lastEvent?.error && (
                <Tooltip title={lastEvent.error}>
                  <span style={{ fontSize: 12, color: c.red, maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {lastEvent.error}
                  </span>
                </Tooltip>
              )}
              {isDisconnected && (
                <span style={{ fontSize: 12, color: c.yellow }}>连接已断开</span>
              )}
            </div>
            <ElapsedTimer
              startMs={runStartMsRef.current}
              isActive={running}
              finalSeconds={isComplete ? lastEvent?.total_elapsed : null}
              isDark={isDark}
            />
          </div>

          {/* ── 用例进度条 ── */}
          {total > 0 && (
            <div style={{ flexShrink: 0 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 5, color: c.dim }}>
                <span>
                  {running && lastCaseStart && !doneEvts.find(e => e.case === lastCaseStart.case)
                    ? `▸ ${lastCaseStart.case}`
                    : `已完成 ${completed}/${total} 用例`}
                </span>
                <span style={{ display: 'flex', gap: 8, fontVariantNumeric: 'tabular-nums' }}>
                  {etaText && <span style={{ color: c.muted }}>{etaText}</span>}
                  <span>{pct}%</span>
                </span>
              </div>
              <div style={{ height: 8, background: c.trail, borderRadius: 4, overflow: 'hidden' }}>
                <div style={{
                  width: `${pct}%`, height: '100%',
                  background: isComplete ? c.green : isError ? c.red : c.blue,
                  borderRadius: 4, transition: 'width 0.4s ease',
                }} />
              </div>
            </div>
          )}

          {/* ── 实时统计行 ── */}
          {events.length > 0 && (liveStats.tokens > 0 || liveStats.files > 0 || liveStats.testTotal > 0) && (
            <div style={{
              display: 'flex', gap: 12, fontSize: 11,
              color: c.muted, flexShrink: 0,
              fontVariantNumeric: 'tabular-nums',
            }}>
              {liveStats.tokens > 0 && (
                <span>🔢 {liveStats.tokens.toLocaleString()} tok</span>
              )}
              {liveStats.files > 0 && (
                <span>📁 {liveStats.files} 文件</span>
              )}
              {liveStats.testTotal > 0 && (
                <span style={{ color: liveStats.testPassed === liveStats.testTotal ? COLORS.green : COLORS.yellow }}>
                  {liveStats.testPassed === liveStats.testTotal ? '✓' : '⚠'} 测试 {liveStats.testPassed}/{liveStats.testTotal}
                </span>
              )}
            </div>
          )}

          {/* ── 事件日志区 ── */}
          {events.length > 0 && (
            <div
              ref={logRef}
              style={{
                flex: 1, minHeight: 0, overflow: 'auto',
                fontSize: 12, fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
                background: c.bg, borderRadius: 6, padding: '10px 12px',
                lineHeight: 1.75, border: `1px solid ${c.border}`,
              }}
            >
              {caseBlocks.map((block, bi) => (
                <CaseEventBlock
                  key={bi}
                  caseIdx={bi}
                  caseStartEvt={block.startEvt}
                  caseEvents={block.events}
                  caseDoneEvt={block.doneEvt}
                  isDark={isDark}
                  isRunning={running}
                />
              ))}

              {/* run_error 单独显示 */}
              {events.filter(e => e.type === 'run_error').map((evt, i) => (
                <div key={i} style={{ color: c.red, marginTop: 4 }}>✗ 错误: {evt.error}</div>
              ))}
            </div>
          )}

          {/* ── 底部操作按钮 ── */}
          {!running && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, flexShrink: 0 }}>
              {isDisconnected && (
                <Button type="primary" block onClick={async () => {
                  const tag = progress?.tag || events.find((e) => e.type === 'run_start')?.tag
                  if (tag) await fetchDetail(tag)
                  setBenchmarkProgress(null)
                  onClose()
                }}>
                  检查最新结果
                </Button>
              )}
              <Button block onClick={() => { onClose(); form.resetFields() }}>关闭</Button>
            </div>
          )}
        </div>
      )}
    </Drawer>
  )
}
