import { Tooltip } from 'antd'
import { DollarOutlined } from '@ant-design/icons'
import useStore from '../../stores/useStore'
import { formatTokens } from '../shared/utils'
import { computeRunCost } from '../../constants/modelPricing'

export default function TokenPanel() {
  const theme = useStore((s) => s.theme)
  const stats = useStore((s) => s.executionStats)
  const tokenRuns = useStore((s) => s.executionTokenRuns)
  const sessionId = useStore((s) => s.sessionId)
  const isRunning = useStore((s) => s.isRunning)
  const modelConfig = useStore((s) => s.modelConfig)
  const setActiveTab = useStore((s) => s.setActiveTab)
  const isDark = theme === 'dark'

  const runsTotal = tokenRuns.reduce((sum, r) => sum + (r.total_tokens || 0), 0)
  const currentInRuns = sessionId && tokenRuns.some(r => r.session_id === sessionId)
  const liveExtra = (isRunning && !currentInRuns && (stats.tokens || 0)) || 0
  const cumulativeTokens = runsTotal + liveExtra

  const currentTokens = isRunning && !currentInRuns
    ? (stats.tokens || 0)
    : (tokenRuns[0]?.total_tokens || 0)

  const cumulativeCost = tokenRuns.reduce((sum, run) => sum + computeRunCost(run, modelConfig), 0)
    + (liveExtra > 0 ? computeRunCost({ total_tokens: liveExtra }, modelConfig) : 0)

  return (
    <Tooltip title="点击查看消耗分析" placement="right">
      <div
        onClick={() => setActiveTab('cost')}
        style={{
          padding: '10px 12px',
          cursor: 'pointer',
          transition: 'background 0.15s',
        }}
        onMouseEnter={(e) => e.currentTarget.style.background = isDark ? '#161b22' : '#f0f0f0'}
        onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
          <DollarOutlined style={{ fontSize: 12, color: isDark ? '#8b949e' : '#656d76' }} />
          <span style={{ fontSize: 11, fontWeight: 600, color: isDark ? '#8b949e' : '#656d76', textTransform: 'uppercase', letterSpacing: 0.5 }}>
            消耗
          </span>
        </div>

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
          <span style={{ fontSize: 16, fontWeight: 700, color: isDark ? '#c9d1d9' : '#1f2328', fontVariantNumeric: 'tabular-nums' }}>
            {formatTokens(cumulativeTokens)}
          </span>
          {currentTokens > 0 && cumulativeTokens !== currentTokens && (
            <span style={{ fontSize: 11, color: '#d29922', fontVariantNumeric: 'tabular-nums' }}>
              +{formatTokens(currentTokens)}
            </span>
          )}
        </div>

        {cumulativeCost > 0 && (
          <div style={{ fontSize: 10, color: isDark ? '#484f58' : '#aaa', marginTop: 2, fontVariantNumeric: 'tabular-nums' }}>
            ~${cumulativeCost.toFixed(3)}
          </div>
        )}
      </div>
    </Tooltip>
  )
}
