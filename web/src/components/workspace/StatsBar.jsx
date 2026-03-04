import { Progress, Tooltip } from 'antd'
import {
  CheckCircleOutlined,
  ExperimentOutlined,
  BugOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons'
import useStore from '../../stores/useStore'
import { formatElapsed } from '../shared/utils'

const CARD_HEIGHT = 88

function StatCard({ icon, label, value, sub, color, percent, isDark }) {
  return (
    <div
      style={{
        padding: '12px 16px',
        borderRadius: 8,
        background: isDark ? '#161b22' : '#ffffff',
        border: `1px solid ${isDark ? '#21262d' : '#e8e8e8'}`,
        minWidth: 0,
        height: CARD_HEIGHT,
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{ color, fontSize: 18 }}>{icon}</span>
        <span style={{ fontSize: 14, color: isDark ? '#8b949e' : '#656d76', fontWeight: 500 }}>{label}</span>
      </div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
        <span style={{ fontSize: 28, fontWeight: 700, color: isDark ? '#f0f6fc' : '#1f2328', fontVariantNumeric: 'tabular-nums', lineHeight: 1 }}>
          {value}
        </span>
        {sub && (
          <span style={{ fontSize: 13, color: isDark ? '#8b949e' : '#656d76' }}>{sub}</span>
        )}
      </div>
      {percent !== undefined ? (
        <Progress
          percent={percent}
          size="small"
          showInfo={false}
          strokeColor={color}
          trailColor={isDark ? '#21262d' : '#f0f0f0'}
          style={{ marginBottom: 0 }}
        />
      ) : (
        <div style={{ height: 6 }} />
      )}
    </div>
  )
}

export default function StatsBar() {
  const theme = useStore((s) => s.theme)
  const stats = useStore((s) => s.executionStats)
  const isDark = theme === 'dark'

  const { tasks, tests, bugs, elapsed } = stats

  const taskPercent = tasks.total > 0 ? Math.round((tasks.verified / tasks.total) * 100) : 0
  const testPercent = tests.total > 0 ? Math.round((tests.passed / tests.total) * 100) : 0

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(4, 1fr)',
        gap: 10,
        padding: '12px 16px',
        flexShrink: 0,
      }}
    >
      <StatCard
        icon={<CheckCircleOutlined />}
        label="任务完成"
        value={`${tasks.verified}/${tasks.total}`}
        percent={taskPercent}
        color="#3fb950"
        isDark={isDark}
      />
      <StatCard
        icon={<ExperimentOutlined />}
        label="测试通过"
        value={tests.total > 0 ? `${tests.passed}/${tests.total}` : '-'}
        percent={tests.total > 0 ? testPercent : undefined}
        color="#58a6ff"
        isDark={isDark}
      />
      <Tooltip title={bugs > 0 ? '点击查看 Bug 详情' : ''}>
        <div>
          <StatCard
            icon={<BugOutlined />}
            label="Bug"
            value={bugs || 0}
            sub={bugs > 0 ? 'open' : ''}
            color={bugs > 0 ? '#f85149' : '#3fb950'}
            isDark={isDark}
          />
        </div>
      </Tooltip>
      <StatCard
        icon={<ClockCircleOutlined />}
        label="耗时"
        value={formatElapsed(elapsed)}
        color="#d29922"
        isDark={isDark}
      />
    </div>
  )
}
