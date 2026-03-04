import { Tag, Button, Tooltip } from 'antd'
import {
  PauseCircleOutlined,
  ThunderboltOutlined,
  ClockCircleOutlined,
  SyncOutlined,
} from '@ant-design/icons'
import useStore from '../../stores/useStore'
import { formatTokens, formatElapsed } from '../shared/utils'

const PHASE_LABELS = {
  planning: '规划', dev: '开发', test: '测试', fix: '修复', plan: '规划',
}

function phaseLabel(raw) {
  if (!raw) return ''
  const lower = raw.toLowerCase()
  for (const [key, label] of Object.entries(PHASE_LABELS)) {
    if (lower.includes(key)) return label
  }
  return raw.slice(0, 8)
}

const PHASE_COLORS = {
  '规划': '#58a6ff', '开发': '#3fb950', '测试': '#d29922', '修复': '#f85149',
}

export default function SessionControl() {
  const theme = useStore((s) => s.theme)
  const isRunning = useStore((s) => s.isRunning)
  const sessionId = useStore((s) => s.sessionId)
  const stats = useStore((s) => s.executionStats)
  const currentPhase = useStore((s) => s.currentPhase)
  const currentIteration = useStore((s) => s.currentIteration)
  const stopExecution = useStore((s) => s.stopExecution)
  const isDark = theme === 'dark'

  if (!isRunning && !sessionId) return null

  const shortId = sessionId ? sessionId.slice(0, 8) : '---'
  const phase = phaseLabel(currentPhase)
  const phaseColor = PHASE_COLORS[phase] || '#8b949e'
  const elapsed = stats.elapsed || 0

  return (
    <div
      style={{
        padding: '10px 12px',
        borderBottom: `1px solid ${isDark ? '#21262d' : '#e8e8e8'}`,
        background: isDark ? '#0d1117' : '#f6f8fa',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{
            fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.5,
            color: isDark ? '#8b949e' : '#656d76',
          }}>
            会话
          </span>
          <span style={{ fontSize: 11, fontFamily: 'monospace', color: isDark ? '#58a6ff' : '#0969da' }}>
            #{shortId}
          </span>
        </div>
        {isRunning ? (
          <Tag color="processing" style={{ margin: 0, fontSize: 10, lineHeight: '16px', padding: '0 6px' }}>
            <SyncOutlined spin style={{ marginRight: 3 }} />运行中
          </Tag>
        ) : (
          <Tag color={stats.tasks?.verified >= stats.tasks?.total && stats.tasks?.total > 0 ? 'success' : 'default'}
            style={{ margin: 0, fontSize: 10, lineHeight: '16px', padding: '0 6px' }}>
            已结束
          </Tag>
        )}
      </div>

      <div style={{ display: 'flex', gap: 10, fontSize: 11, color: isDark ? '#8b949e' : '#656d76', marginBottom: 6, flexWrap: 'wrap' }}>
        <Tooltip title="消耗">
          <span style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
            <ThunderboltOutlined style={{ fontSize: 10 }} />
            {formatTokens(stats.tokens)}
          </span>
        </Tooltip>
        {elapsed > 0 && (
          <Tooltip title="耗时">
            <span style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
              <ClockCircleOutlined style={{ fontSize: 10 }} />
              {formatElapsed(elapsed)}
            </span>
          </Tooltip>
        )}
        {currentIteration.maxIterations > 0 && (
          <span>
            第 {currentIteration.iteration}/{currentIteration.maxIterations} 步
          </span>
        )}
        {phase && (
          <Tag color={phaseColor} style={{ margin: 0, fontSize: 10, lineHeight: '16px', padding: '0 5px', border: 'none' }}>
            {phase}
          </Tag>
        )}
      </div>

      {isRunning && (
        <Button
          size="small"
          danger
          icon={<PauseCircleOutlined />}
          onClick={stopExecution}
          block
          style={{ fontSize: 12 }}
        >
          停止会话
        </Button>
      )}
    </div>
  )
}
