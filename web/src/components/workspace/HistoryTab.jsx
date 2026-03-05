import { useState } from 'react'
import { Collapse, Tag, Button, Popconfirm, Empty, Typography } from 'antd'
import {
  CheckCircleFilled, CloseCircleFilled,
  CaretRightOutlined, ThunderboltOutlined, ClockCircleOutlined,
  DeleteOutlined, DashboardOutlined,
} from '@ant-design/icons'
import useStore from '../../stores/useStore'
import * as api from '../../services/api'
import { formatTokenCount } from './helpers'

const { Text } = Typography

const AGENT_COLORS = {
  refiner: '#8b949e', helper: '#58a6ff', coder: '#3fb950', dev: '#3fb950',
  developer: '#3fb950', implementer: '#3fb950', critique: '#d29922', test: '#d29922', tester: '#d29922', system: '#8b949e',
}
const AGENT_LABEL = { refiner: '优化', helper: '辅助 AI', planner: '规划', coder: 'Coder AI', dev: 'Coder AI', implementer: '实现', critique: 'Critique AI', test: 'Critique AI', developer: 'Coder AI', tester: 'Critique AI' }

function HistorySessionItem({ session, realIdx, isDark, onDelete }) {
  const sectionKey = `history-session-${session.session_id || realIdx}`
  const storedCollapsed = useStore(s => s.collapsedSections[sectionKey])
  const setSectionCollapsed = useStore(s => s.setSectionCollapsed)
  const isOpen = storedCollapsed === undefined ? false : !storedCollapsed

  const ts = session.timestamp
    ? new Date(session.timestamp).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
    : ''
  const isFailed = session.success === false || session.status === 'failed'
  const isSuccess = session.success === true || session.status === 'completed'

  return (
    <Collapse size="small" style={{ marginBottom: 8 }}
      activeKey={isOpen ? ['0'] : []}
      onChange={(keys) => setSectionCollapsed(sectionKey, !keys.includes('0'))}
      expandIcon={({ isActive }) => <CaretRightOutlined rotate={isActive ? 90 : 0} />}
      items={[{
        key: '0',
        label: (
          <span style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
            <span style={{ fontWeight: 600 }}>会话</span>
            {session.session_id && (
              <span style={{ fontSize: 11, fontFamily: 'monospace', color: isDark ? '#58a6ff' : '#0969da' }}>
                #{session.session_id.slice(0, 8)}
              </span>
            )}
            <Text type="secondary" style={{ fontSize: 11 }}>{ts}</Text>
            {isSuccess
              ? <Tag icon={<CheckCircleFilled />} color="success" style={{ margin: 0 }}>成功</Tag>
              : isFailed
                ? <Tag icon={<CloseCircleFilled />} color="error" style={{ margin: 0 }}>失败</Tag>
                : null
            }
            <span style={{ display: 'flex', alignItems: 'center', gap: 3, fontSize: 11, color: isDark ? '#8b949e' : '#656d76' }}>
              <ThunderboltOutlined style={{ fontSize: 10 }} />
              {formatTokenCount(session.total_tokens || 0)}
            </span>
            <Popconfirm title="删除此会话记录？"
              onConfirm={(e) => { e?.stopPropagation(); onDelete(session, realIdx) }}
              onCancel={(e) => e?.stopPropagation()}
              okText="删除" cancelText="取消"
            >
              <Button type="text" size="small" danger
                icon={<DeleteOutlined style={{ fontSize: 11 }} />}
                onClick={(e) => e.stopPropagation()}
                style={{ marginLeft: 'auto', padding: '0 4px' }}
              />
            </Popconfirm>
          </span>
        ),
        children: (
          <div style={{ padding: '8px 12px' }}>
            {(session.requirement || session.description) && (
              <div style={{ fontSize: 12, color: isDark ? '#8b949e' : '#656d76', marginBottom: 8 }}>
                需求：{session.requirement || session.description}
              </div>
            )}
            {isFailed && session.failure_reason && (
              <div style={{
                fontSize: 12, marginBottom: 8, padding: '6px 10px', borderRadius: 4,
                background: isDark ? 'rgba(248,81,73,0.1)' : 'rgba(248,81,73,0.06)',
                color: isDark ? '#f85149' : '#cf222e',
              }}>
                失败原因：{session.failure_reason}
              </div>
            )}
            {session.agent_tokens && Object.keys(session.agent_tokens).length > 0 && (
              <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', fontSize: 12, marginBottom: 4 }}>
                {Object.entries(session.agent_tokens)
                  .filter(([k, v]) => !k.startsWith('_') && v > 0)
                  .map(([agent, tokens]) => (
                    <span key={agent} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                      <span style={{ width: 6, height: 6, borderRadius: '50%', background: AGENT_COLORS[agent] || '#8b949e', display: 'inline-block' }} />
                      <span style={{ color: isDark ? '#8b949e' : '#656d76' }}>{AGENT_LABEL[agent] || agent}</span>
                      <span style={{ fontVariantNumeric: 'tabular-nums' }}>{formatTokenCount(tokens)}</span>
                    </span>
                  ))
                }
              </div>
            )}
            <div style={{ display: 'flex', gap: 12, fontSize: 11, color: isDark ? '#6e7681' : '#8c959f' }}>
              {session.elapsed_seconds > 0 && (
                <span>
                  <ClockCircleOutlined style={{ marginRight: 4 }} />
                  耗时 {session.elapsed_seconds.toFixed(1)}s
                </span>
              )}
              {session.source && (
                <span>来源：{session.source === 'web' ? '网页' : session.source === 'cli' ? '命令行' : session.source}</span>
              )}
              {session.event_count > 0 && <span>{session.event_count} 个事件</span>}
            </div>
          </div>
        ),
      }]}
    />
  )
}

export default function HistoryTab() {
  const theme = useStore(s => s.theme)
  const isDark = theme === 'dark'
  const tokenRuns = useStore(s => s.executionTokenRuns)
  const isRunning = useStore(s => s.isRunning)
  const sessionId = useStore(s => s.sessionId)
  const setActiveTab = useStore(s => s.setActiveTab)

  const [deletedSessions, setDeletedSessions] = useState(new Set())

  const pastSessions = tokenRuns.filter(r => r.session_id && !(isRunning && r.session_id === sessionId))
  const visiblePastSessions = pastSessions.filter((_, idx) => !deletedSessions.has(idx))

  const handleClearFinished = async () => {
    try {
      await api.clearSessions(true)
      setDeletedSessions(new Set(pastSessions.map((_, idx) => idx)))
    } catch { /* ignore */ }
  }

  const handleDeleteSession = async (session, idx) => {
    try {
      if (session.session_id) await api.deleteSession(session.session_id)
      setDeletedSessions(prev => new Set([...prev, idx]))
    } catch { /* ignore */ }
  }

  return (
    <div style={{ height: '100%', overflow: 'auto', padding: 16 }}>
      {visiblePastSessions.length > 0 && (
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 8 }}>
          <Popconfirm title="确认清理所有已结束的会话？" onConfirm={handleClearFinished} okText="确认" cancelText="取消">
            <Button size="small" icon={<DeleteOutlined />} danger>清理已结束</Button>
          </Popconfirm>
        </div>
      )}

      {visiblePastSessions.map((session, visualIdx) => {
        const realIdx = pastSessions.indexOf(session)
        return (
          <HistorySessionItem
            key={realIdx}
            session={session}
            realIdx={realIdx}
            isDark={isDark}
            onDelete={handleDeleteSession}
          />
        )
      })}

      {visiblePastSessions.length === 0 && (
        <Empty
          description={
            isRunning ? (
              <span>
                暂无历史记录，当前执行的实时进度请查看
                <Button type="link" size="small" icon={<DashboardOutlined />}
                  onClick={() => setActiveTab('overview')}
                  style={{ padding: '0 4px' }}
                >
                  概览
                </Button>
              </span>
            ) : '暂无执行历史'
          }
          style={{ padding: '48px 0' }}
        />
      )}
    </div>
  )
}
