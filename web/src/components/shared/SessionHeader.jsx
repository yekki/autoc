import { Tag, Row, Col, Statistic, Tooltip } from 'antd'
import {
  SyncOutlined, CheckCircleFilled,
  CloseCircleFilled, ThunderboltOutlined, ClockCircleOutlined,
  MinusCircleOutlined, WarningOutlined,
} from '@ant-design/icons'
import useStore from '../../stores/useStore'
import { formatTokens, formatElapsed } from './utils'

/**
 * 项目持久状态 → 标签配置
 * 与 WelcomePage.jsx 的 STATUS_MAP 保持一致
 */
const PROJECT_STATUS_MAP = {
  idle:       { label: '未开始',  color: 'default',    icon: null },
  planning:   { label: '规划中',  color: 'processing', icon: <SyncOutlined spin /> },
  developing: { label: '开发中',  color: 'processing', icon: <SyncOutlined spin /> },
  testing:    { label: '测试中',  color: 'warning',    icon: <SyncOutlined spin /> },
  incomplete: { label: '未完成',  color: 'warning',    icon: <MinusCircleOutlined /> },
  completed:  { label: '已完成',  color: 'success',    icon: <CheckCircleFilled /> },
  aborted:    { label: '异常终止', color: 'error',     icon: <WarningOutlined /> },
}

/**
 * 从执行状态推导当前会话状态（正式定义）
 *
 * 会话状态（Session Status）描述"这次执行"的结果，与项目持久状态独立：
 *   running  — Agent 正在执行
 *   success  — 本次执行：全部任务验证通过
 *   partial  — 本次执行：部分任务通过
 *   failed   — 本次执行：任务均未通过或发生错误
 *   idle     — 无活跃会话（未运行或会话数据未加载）
 */
function deriveSessionStatus(isRunning, summary) {
  if (isRunning) return 'running'
  if (!summary) return 'idle'
  if (summary.success) return 'success'
  if (summary.partial_success) return 'partial'
  return 'failed'
}

const SESSION_STATUS_MAP = {
  running: { label: '运行中',   color: 'processing', icon: <SyncOutlined spin />, prefix: '' },
  success: { label: '全部通过', color: 'success',    icon: <CheckCircleFilled />, prefix: '本次执行：' },
  partial: { label: '部分通过', color: 'warning',    icon: null,                 prefix: '本次执行：' },
  failed:  { label: '未通过',   color: 'error',      icon: <CloseCircleFilled />, prefix: '本次执行：' },
  idle:    null,
}

function deriveProjectStatus(isRunning, currentPhase, dbStatus) {
  if (isRunning) {
    if (currentPhase) {
      const p = currentPhase.toLowerCase()
      if (p.includes('测试') || p.includes('test')) return 'testing'
      if (p.includes('开发') || p.includes('dev') || p.includes('代码')) return 'developing'
      return 'planning'
    }
    return dbStatus || 'planning'
  }
  return dbStatus || 'idle'
}

export default function SessionHeader({ actions }) {
  const theme = useStore((s) => s.theme)
  const isRunning = useStore((s) => s.isRunning)
  const sessionId = useStore((s) => s.sessionId)
  const stats = useStore((s) => s.executionStats)
  const summary = useStore((s) => s.executionSummary)
  const currentPhase = useStore((s) => s.currentPhase)
  const getSelectedProject = useStore((s) => s.getSelectedProject)
  const isDark = theme === 'dark'
  const project = getSelectedProject()

  const shortId = sessionId ? sessionId.slice(0, 8) : null
  const elapsed = stats.elapsed || summary?.elapsed_seconds || 0

  const sessionStatus = deriveSessionStatus(isRunning, summary)
  const sessionCfg = SESSION_STATUS_MAP[sessionStatus]

  const effectiveStatus = deriveProjectStatus(isRunning, currentPhase, project?.status)
  const projectStatusCfg = PROJECT_STATUS_MAP[effectiveStatus] || null

  return (
    <div style={{ marginBottom: 16 }}>
      <div
        style={{
          background: isDark ? '#161b22' : '#fff',
          border: `1px solid ${isDark ? '#30363d' : '#d0d7de'}`,
          borderRadius: 8,
          padding: '12px 16px',
        }}
      >
        {/* 第一行：项目名 + 状态标签 | 操作按钮 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1, minWidth: 0, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 15, fontWeight: 600, color: isDark ? '#c9d1d9' : '#1f2328' }}>
              {project?.name || '项目'}
            </span>

            {projectStatusCfg && (
              <Tooltip title="项目当前状态">
                <Tag
                  color={projectStatusCfg.color}
                  style={{ margin: 0, fontSize: 11, cursor: 'default' }}
                  icon={projectStatusCfg.icon}
                >
                  {projectStatusCfg.label}
                </Tag>
              </Tooltip>
            )}

            {sessionCfg && projectStatusCfg && (
              <span style={{ color: isDark ? '#30363d' : '#d0d7de', fontSize: 12 }}>·</span>
            )}

            {sessionCfg && (
              <Tooltip title="本次执行结果">
                <Tag
                  color={sessionCfg.color}
                  icon={sessionCfg.icon}
                  style={{ margin: 0, fontSize: 11 }}
                >
                  {sessionCfg.prefix}{sessionCfg.label}
                </Tag>
              </Tooltip>
            )}

            {shortId && (
              <span style={{ fontSize: 10, fontFamily: 'monospace', color: isDark ? '#484f58' : '#afb8c1' }}>
                #{shortId}
              </span>
            )}
          </div>

          {actions && (
            <div style={{ display: 'flex', gap: 8, flexShrink: 0 }}>
              {actions}
            </div>
          )}
        </div>

        {/* 第二行：耗时 / Token */}
        {(stats.tokens > 0 || elapsed > 0) && (
          <div style={{ display: 'flex', gap: 12, fontSize: 11, color: isDark ? '#6e7681' : '#8c959f', marginBottom: 10 }}>
            {stats.tokens > 0 && (
              <span style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
                <ThunderboltOutlined style={{ fontSize: 10 }} />
                {formatTokens(stats.tokens)}
              </span>
            )}
            {elapsed > 0 && (
              <span style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
                <ClockCircleOutlined style={{ fontSize: 10 }} />
                {formatElapsed(elapsed)}
              </span>
            )}
          </div>
        )}

        {/* 第四行：统计卡片 */}
        <Row gutter={[8, 8]}>
          {[
            { title: '任务', value: stats.tasks.verified || stats.tasks.completed, suffix: `/ ${stats.tasks.total}`,
              color: stats.tasks.verified >= stats.tasks.total && stats.tasks.total > 0 ? '#3fb950' : undefined,
              tip: stats.tasks.total > 0 ? `已完成 ${stats.tasks.completed}，已验证 ${stats.tasks.verified}` : null },
            { title: '测试', value: stats.tests.passed, suffix: `/ ${stats.tests.total}`,
              color: stats.tests.passed === stats.tests.total && stats.tests.total > 0 ? '#3fb950' : undefined,
              tip: stats.tests.total > 0 ? `通过 ${stats.tests.passed} / ${stats.tests.total}` : null },
            { title: '缺陷', value: stats.bugs,
              color: stats.bugs > 0 ? (summary?.success ? '#d29922' : '#f85149') : undefined,
              tip: stats.bugs > 0 ? `${stats.bugs} 个未解决缺陷` : null },
            { title: '消耗', value: formatTokens(stats.tokens) },
          ].map((s) => (
            <Col span={6} key={s.title}>
              <Tooltip title={s.tip}>
                <Statistic
                  title={<span style={{ fontSize: 11 }}>{s.title}</span>}
                  value={s.value}
                  suffix={s.suffix}
                  styles={{ content: { fontSize: 18, color: s.color } }}
                />
              </Tooltip>
            </Col>
          ))}
        </Row>
      </div>
    </div>
  )
}
