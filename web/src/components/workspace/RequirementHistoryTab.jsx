import { useState, useMemo, useRef, useEffect } from 'react'
import { Tag, Button, Popconfirm, Empty, Collapse } from 'antd'
import {
  CheckCircleFilled, CloseCircleFilled, MinusCircleOutlined,
  ThunderboltOutlined, ClockCircleOutlined,
  DeleteOutlined, DashboardOutlined,
  CaretRightOutlined, BugOutlined, SyncOutlined,
  EditOutlined, PlusCircleOutlined, RocketOutlined,
} from '@ant-design/icons'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import useStore from '../../stores/useStore'
import * as api from '../../services/api'
import { formatTokenCount } from './helpers'

const AGENT_COLORS = {
  refiner: '#8b949e', helper: '#58a6ff', coder: '#3fb950', dev: '#3fb950',
  developer: '#3fb950', critique: '#d29922', test: '#d29922', tester: '#d29922', system: '#8b949e',
}
const AGENT_LABEL = { refiner: '优化', helper: '辅助 AI', planner: '规划', coder: 'Coder AI', dev: 'Coder AI', critique: 'Critique AI', test: 'Critique AI', developer: 'Coder AI', tester: 'Critique AI' }

const OP_CONFIG = {
  'resume':      { label: '恢复执行', color: '#58a6ff', icon: <SyncOutlined style={{ fontSize: 10 }} /> },
  'quick-fix':   { label: 'Bug 修复', color: '#f85149', icon: <BugOutlined style={{ fontSize: 10 }} /> },
  'retest':      { label: '重新测试', color: '#d29922', icon: <SyncOutlined style={{ fontSize: 10 }} /> },
  'revise':      { label: '需求调整', color: '#58a6ff', icon: <EditOutlined style={{ fontSize: 10 }} /> },
  'fix':         { label: '定向修复', color: '#f85149', icon: <BugOutlined style={{ fontSize: 10 }} /> },
  'add-feature': { label: '新增功能', color: '#3fb950', icon: <PlusCircleOutlined style={{ fontSize: 10 }} /> },
}
const INITIAL_OP = { label: '完整执行', color: '#3fb950', icon: <RocketOutlined style={{ fontSize: 10 }} /> }

const OP_PREFIX_RE = /^\[(resume|retest|quick-fix|revise|fix|add-feature)\]\s*/i
const BARE_OPS = new Set(['resume', 'retest', 'quick-fix', 'revise', 'fix', 'add-feature'])

function parseReq(req) {
  if (!req) return { opType: null, text: '' }
  const match = req.match(OP_PREFIX_RE)
  if (match) return { opType: match[1].toLowerCase(), text: req.slice(match[0].length).trim() }
  const bare = req.trim().toLowerCase()
  if (BARE_OPS.has(bare)) return { opType: bare, text: '' }
  return { opType: null, text: req.trim() }
}

/**
 * 按需求文本分组，[resume]/[retest] 等无文本的操作归入最近的需求组。
 * 确保一级永远展示需求内容，二级展示该需求下的所有执行会话。
 */
function buildGroups(sessions, fallbackRequirement) {
  const sorted = [...sessions].sort((a, b) => (a.started_at || 0) - (b.started_at || 0))
  const groups = []
  let currentGroup = null

  for (const s of sorted) {
    const { opType, text } = parseReq(s.requirement)
    const enriched = { ...s, _opType: opType }

    if (text) {
      const existing = groups.find(g => g.requirement === text)
      if (existing) {
        existing.sessions.push(enriched)
        if (s.started_at > existing.latestTime) existing.latestTime = s.started_at
        currentGroup = existing
      } else {
        currentGroup = {
          requirement: text,
          tech_stack: s.tech_stack || [],
          sessions: [enriched],
          firstTime: s.started_at || 0,
          latestTime: s.started_at || 0,
        }
        groups.push(currentGroup)
      }
    } else {
      if (!currentGroup) {
        currentGroup = {
          requirement: fallbackRequirement || '项目需求',
          tech_stack: s.tech_stack || [],
          sessions: [],
          firstTime: s.started_at || 0,
          latestTime: s.started_at || 0,
        }
        groups.push(currentGroup)
      }
      currentGroup.sessions.push(enriched)
      if (s.started_at > currentGroup.latestTime) currentGroup.latestTime = s.started_at
      if (!currentGroup.tech_stack?.length && s.tech_stack?.length) {
        currentGroup.tech_stack = s.tech_stack
      }
    }
  }

  groups.reverse()
  for (const g of groups) g.sessions.reverse()
  return groups
}

const REQ_COLLAPSED_HEIGHT = 60

function RequirementText({ text, isDark, defaultExpanded, sectionKey }) {
  const contentRef = useRef(null)
  const [overflows, setOverflows] = useState(false)
  const storedExpanded = useStore(s => s.collapsedSections[sectionKey])
  const setSectionCollapsed = useStore(s => s.setSectionCollapsed)
  const expanded = storedExpanded === undefined ? false : !storedExpanded

  useEffect(() => {
    if (defaultExpanded || !contentRef.current) return
    setOverflows(contentRef.current.scrollHeight > REQ_COLLAPSED_HEIGHT + 4)
  }, [text, defaultExpanded])

  const isOpen = defaultExpanded || expanded
  const collapsed = !isOpen && overflows

  return (
    <div style={{ position: 'relative', marginBottom: 8 }}>
      <div
        ref={contentRef}
        className="requirement-markdown"
        style={{
          fontSize: 13, lineHeight: 1.7,
          color: isDark ? '#e6edf3' : '#1f2328',
          padding: '8px 12px',
          background: isDark ? '#161b22' : '#f6f8fa',
          borderRadius: 8,
          border: `1px solid ${isDark ? '#21262d' : '#e1e4e8'}`,
          wordBreak: 'break-word',
          maxHeight: isOpen ? 'none' : REQ_COLLAPSED_HEIGHT,
          overflow: isOpen ? 'visible' : 'hidden',
        }}
      >
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
      </div>
      {collapsed && (
        <div style={{
          position: 'absolute', bottom: 0, left: 0, right: 0, height: 28,
          background: `linear-gradient(transparent, ${isDark ? '#161b22' : '#f6f8fa'})`,
          borderRadius: '0 0 8px 8px',
          display: 'flex', alignItems: 'flex-end', justifyContent: 'center', paddingBottom: 2,
        }}>
          <Button type="link" size="small" onClick={() => setSectionCollapsed(sectionKey, false)}
            style={{ fontSize: 11, padding: 0, height: 'auto', color: isDark ? '#58a6ff' : '#0969da' }}>
            展开全部
          </Button>
        </div>
      )}
      {!defaultExpanded && expanded && overflows && (
        <div style={{ textAlign: 'center', marginTop: 2 }}>
          <Button type="link" size="small" onClick={() => setSectionCollapsed(sectionKey, true)}
            style={{ fontSize: 11, padding: 0, height: 'auto', color: isDark ? '#58a6ff' : '#0969da' }}>
            收起
          </Button>
        </div>
      )}
    </div>
  )
}

function SessionCard({ session, isDark, onDelete }) {
  const isFailed = session.success === false || session.status === 'failed'
  const isSuccess = session.success === true || session.status === 'completed'
  const opCfg = session._opType ? OP_CONFIG[session._opType] : INITIAL_OP
  const ts = session.timestamp
    ? new Date(session.timestamp).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
    : ''

  return (
    <div style={{
      padding: '8px 12px', fontSize: 12, marginBottom: 4, borderRadius: 6,
      background: isDark ? '#0d1117' : '#fff',
      border: `1px solid ${isDark ? '#21262d' : '#e1e4e8'}`,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        {isSuccess
          ? <CheckCircleFilled style={{ color: '#3fb950', fontSize: 13 }} />
          : isFailed
            ? <CloseCircleFilled style={{ color: '#f85149', fontSize: 13 }} />
            : <MinusCircleOutlined style={{ color: '#d29922', fontSize: 13 }} />}
        <Tag icon={opCfg.icon} style={{
          margin: 0, fontSize: 10, lineHeight: '18px',
          color: opCfg.color, background: `${opCfg.color}18`, borderColor: `${opCfg.color}40`,
        }}>{opCfg.label}</Tag>
        <span style={{ color: isDark ? '#6e7681' : '#8c959f', fontSize: 11 }}>{ts}</span>
        {session.tasks_total > 0 && (
          <span style={{
            fontSize: 11, fontWeight: 500,
            color: isSuccess ? '#3fb950' : isDark ? '#c9d1d9' : '#1f2328',
          }}>
            {session.tasks_completed}/{session.tasks_total} 任务
          </span>
        )}
        {session.elapsed_seconds > 0 && (
          <span style={{ fontSize: 11, color: isDark ? '#6e7681' : '#8c959f' }}>
            <ClockCircleOutlined style={{ marginRight: 3, fontSize: 10 }} />
            {session.elapsed_seconds >= 60
              ? `${Math.floor(session.elapsed_seconds / 60)}m${Math.round(session.elapsed_seconds % 60)}s`
              : `${session.elapsed_seconds.toFixed(1)}s`}
          </span>
        )}
        <span style={{
          display: 'flex', alignItems: 'center', gap: 3, fontSize: 11,
          color: session.total_tokens > 0 ? (isDark ? '#8b949e' : '#656d76') : (isDark ? '#30363d' : '#c9d1d9'),
        }}>
          <ThunderboltOutlined style={{ fontSize: 10 }} />
          {formatTokenCount(session.total_tokens || 0)}
        </span>
        <Popconfirm title="删除此会话？" onConfirm={() => onDelete(session)} okText="删除" cancelText="取消">
          <Button type="text" size="small" danger
            icon={<DeleteOutlined style={{ fontSize: 10 }} />}
            onClick={(e) => e.stopPropagation()}
            style={{ marginLeft: 'auto', padding: '0 4px' }} />
        </Popconfirm>
      </div>
      {isFailed && session.failure_reason && (
        <div style={{
          fontSize: 11, padding: '4px 8px', borderRadius: 4, marginTop: 6,
          background: isDark ? 'rgba(248,81,73,0.1)' : 'rgba(248,81,73,0.06)',
          color: isDark ? '#f85149' : '#cf222e',
        }}>{session.failure_reason}</div>
      )}
      {session.agent_tokens && Object.keys(session.agent_tokens).length > 0 && (
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', fontSize: 11, marginTop: 4 }}>
          {Object.entries(session.agent_tokens)
            .filter(([k, v]) => !k.startsWith('_') && v > 0)
            .map(([agent, tokens]) => (
              <span key={agent} style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
                <span style={{ width: 6, height: 6, borderRadius: '50%', background: AGENT_COLORS[agent] || '#8b949e', display: 'inline-block' }} />
                <span style={{ color: isDark ? '#8b949e' : '#656d76' }}>{AGENT_LABEL[agent] || agent}</span>
                <span style={{ fontVariantNumeric: 'tabular-nums' }}>{formatTokenCount(tokens)}</span>
              </span>
            ))}
        </div>
      )}
    </div>
  )
}

function RequirementGroup({ group, gIdx, isCurrent, isDark, onDelete }) {
  const successCount = group.sessions.filter(s => s.success === true || s.status === 'completed').length
  const failCount = group.sessions.filter(s => s.success === false || s.status === 'failed').length
  const total = group.sessions.length
  const totalTokens = group.sessions.reduce((sum, s) => sum + (s.total_tokens || 0), 0)

  const collapseKey = `history-sessions-${gIdx}`
  const storedCollapsed = useStore(s => s.collapsedSections[collapseKey])
  const setSectionCollapsed = useStore(s => s.setSectionCollapsed)
  const sessionsOpen = storedCollapsed === undefined ? isCurrent : !storedCollapsed

  const dateRange = (() => {
    if (!group.firstTime) return ''
    const fmt = (t) => new Date(t * 1000).toLocaleString('zh-CN', {
      month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
    })
    const first = fmt(group.firstTime)
    const last = fmt(group.latestTime)
    return first === last ? first : `${first} ~ ${last}`
  })()

  return (
    <div style={{
      marginBottom: 16,
      background: isDark ? '#0d1117' : '#fff',
      border: `1px solid ${isCurrent ? (isDark ? '#1f6feb' : '#0969da') : (isDark ? '#21262d' : '#e1e4e8')}`,
      borderRadius: 10, overflow: 'hidden',
    }}>
      <div style={{ padding: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
          <Tag color={isCurrent ? 'blue' : 'default'} style={{ margin: 0, fontSize: 10 }}>
            {isCurrent ? '当前需求' : '历史需求'}
          </Tag>
          <span style={{ fontSize: 11, color: isDark ? '#6e7681' : '#8c959f' }}>{dateRange}</span>
          <span style={{ fontSize: 11, color: isDark ? '#8b949e' : '#656d76' }}>
            {total} 次执行
            {successCount > 0 && <span style={{ color: '#3fb950', marginLeft: 4 }}>{successCount} 成功</span>}
            {failCount > 0 && <span style={{ color: '#f85149', marginLeft: 4 }}>{failCount} 失败</span>}
          </span>
          {totalTokens > 0 && (
            <span style={{ fontSize: 11, color: isDark ? '#8b949e' : '#656d76', marginLeft: 'auto' }}>
              <ThunderboltOutlined style={{ fontSize: 10, marginRight: 3 }} />
              累计 {formatTokenCount(totalTokens)}
            </span>
          )}
        </div>

        <RequirementText
          text={group.requirement} isDark={isDark} defaultExpanded={isCurrent}
          sectionKey={`history-req-text-${gIdx}`}
        />

        {group.tech_stack?.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 4 }}>
            {group.tech_stack.map((t) => (
              <Tag key={t} style={{
                margin: 0, fontSize: 10, lineHeight: '18px',
                background: isDark ? '#1c2128' : '#eef1f5',
                borderColor: isDark ? '#30363d' : '#d0d7de',
                color: isDark ? '#8b949e' : '#656d76',
              }}>{t}</Tag>
            ))}
          </div>
        )}
      </div>

      <Collapse
        ghost size="small"
        activeKey={sessionsOpen ? ['sessions'] : []}
        onChange={(keys) => setSectionCollapsed(collapseKey, !keys.includes('sessions'))}
        expandIcon={({ isActive }) => <CaretRightOutlined rotate={isActive ? 90 : 0} style={{ fontSize: 10 }} />}
        style={{ borderTop: `1px solid ${isDark ? '#21262d' : '#e1e4e8'}` }}
        items={[{
          key: 'sessions',
          label: (
            <span style={{ fontSize: 11, color: isDark ? '#8b949e' : '#656d76' }}>
              执行记录（{total}）
              {successCount > 0 && failCount > 0 && (
                <span style={{ marginLeft: 8 }}>
                  成功率 {Math.round(successCount / total * 100)}%
                </span>
              )}
            </span>
          ),
          children: (
            <div style={{ padding: '0 4px' }}>
              {group.sessions.map((session) => (
                <SessionCard
                  key={session.session_id}
                  session={session}
                  isDark={isDark}
                  onDelete={onDelete}
                />
              ))}
            </div>
          ),
        }]}
      />
    </div>
  )
}

export default function RequirementHistoryTab() {
  const theme = useStore(s => s.theme)
  const isDark = theme === 'dark'
  const tokenRuns = useStore(s => s.executionTokenRuns)
  const isRunning = useStore(s => s.isRunning)
  const sessionId = useStore(s => s.sessionId)
  const setActiveTab = useStore(s => s.setActiveTab)
  const projects = useStore(s => s.projects)
  const selectedProjectName = useStore(s => s.selectedProjectName)
  const executionRequirement = useStore(s => s.executionRequirement)

  const [deletedSessions, setDeletedSessions] = useState(new Set())

  const pastSessions = tokenRuns.filter(r => r.session_id && !(isRunning && r.session_id === sessionId))
  const visibleSessions = pastSessions.filter(s => !deletedSessions.has(s.session_id))

  const fallbackReq = useMemo(() => {
    const proj = projects.find(p => p.folder === selectedProjectName)
    return proj?.description || executionRequirement || ''
  }, [projects, selectedProjectName, executionRequirement])

  const groups = useMemo(() => buildGroups(visibleSessions, fallbackReq), [visibleSessions, fallbackReq])

  const handleDeleteSession = async (session) => {
    try {
      if (session.session_id) await api.deleteSession(session.session_id)
      setDeletedSessions(prev => new Set([...prev, session.session_id]))
    } catch { /* ignore */ }
  }

  const handleClearFinished = async () => {
    try {
      await api.clearSessions(true)
      setDeletedSessions(new Set(pastSessions.map(s => s.session_id)))
    } catch { /* ignore */ }
  }

  if (visibleSessions.length === 0) {
    return (
      <div style={{ height: '100%', overflow: 'auto', padding: 16 }}>
        <Empty
          description={isRunning ? (
            <span>暂无需求历史，当前执行请查看
              <Button type="link" size="small" icon={<DashboardOutlined />}
                onClick={() => setActiveTab('overview')} style={{ padding: '0 4px' }}>概览</Button>
            </span>
          ) : '暂无需求历史'}
          style={{ padding: '48px 0' }}
        />
      </div>
    )
  }

  return (
    <div style={{ height: '100%', overflow: 'auto', padding: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 12 }}>
        <Popconfirm title="确认清理所有已结束的会话？" onConfirm={handleClearFinished} okText="确认" cancelText="取消">
          <Button size="small" icon={<DeleteOutlined />} danger>清理全部</Button>
        </Popconfirm>
      </div>

      {groups.map((group, gIdx) => (
        <RequirementGroup
          key={gIdx}
          group={group}
          gIdx={gIdx}
          isCurrent={gIdx === 0}
          isDark={isDark}
          onDelete={handleDeleteSession}
        />
      ))}
    </div>
  )
}
