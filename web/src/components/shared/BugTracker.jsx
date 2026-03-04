import { Button, Tag, Space, Empty, message, Alert, Spin, Tooltip } from 'antd'
import {
  BugOutlined, ToolOutlined, CheckCircleOutlined,
  CloseCircleOutlined, LoadingOutlined, ExclamationCircleOutlined,
} from '@ant-design/icons'
import useStore from '../../stores/useStore'

const SEVERITY_CONFIG = {
  critical: { color: '#f85149', bg: '#f851491a', label: 'CRITICAL' },
  high: { color: '#d29922', bg: '#d299221a', label: 'HIGH' },
  medium: { color: '#e3b341', bg: '#e3b3411a', label: 'MEDIUM' },
  low: { color: '#58a6ff', bg: '#58a6ff1a', label: 'LOW' },
}

const FIX_STATUS_ICON = {
  pending: null,
  fixing: <LoadingOutlined spin style={{ color: '#1677ff', fontSize: 14 }} />,
  fixed: <CheckCircleOutlined style={{ color: '#52c41a', fontSize: 14 }} />,
  failed: <CloseCircleOutlined style={{ color: '#f85149', fontSize: 14 }} />,
  unfixed: <ExclamationCircleOutlined style={{ color: '#d29922', fontSize: 14 }} />,
}

const FIX_STATUS_TEXT = {
  fixing: '修复中...',
  fixed: '已修复',
  failed: '修复失败',
  unfixed: '验证未通过',
}

function formatTokens(n) {
  if (!n) return '0'
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`
  return String(n)
}

/**
 * 修复结果摘要（修复完成后显示）
 */
function FixResultBanner({ fixProgress, isDark }) {
  if (fixProgress.status !== 'done') return null

  const { fixedCount, results, elapsedSeconds, verified } = fixProgress
  const total = results.length
  const failedCount = results.filter((r) => r.status === 'failed' || r.status === 'unfixed').length
  const allFixed = fixedCount === total && fixedCount > 0

  let alertType = 'success'
  let msg = `修复完成：${fixedCount}/${total} 个问题已修复`
  if (fixedCount === 0) {
    alertType = 'error'
    msg = `修复失败：${total} 个问题均未能修复`
  } else if (failedCount > 0) {
    alertType = 'warning'
    msg = `部分修复：${fixedCount}/${total} 个已修复，${failedCount} 个需人工介入`
  }
  if (elapsedSeconds > 0) msg += `，耗时 ${elapsedSeconds.toFixed(1)}s`
  if (verified === false) msg += '（测试验证未通过）'

  return (
    <Alert
      type={alertType}
      message={msg}
      showIcon
      closable
      banner
      style={{ marginBottom: 8, borderRadius: 6 }}
    />
  )
}

/**
 * 修复进度条（修复中显示）
 */
function FixProgressBar({ fixProgress, isDark }) {
  if (fixProgress.status !== 'fixing') return null

  const { currentBug, current, total } = fixProgress
  const label = currentBug?.title
    ? `正在修复: ${currentBug.title}`
    : '准备修复...'

  return (
    <div style={{
      padding: '8px 12px', marginBottom: 8, borderRadius: 6,
      background: isDark ? '#161b2280' : '#f0f5ff',
      border: `1px solid ${isDark ? '#1668dc40' : '#91caff'}`,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <Spin size="small" />
        <span style={{ fontSize: 12, color: isDark ? '#8b949e' : '#656d76', flex: 1 }}>
          {label} ({current}/{total})
        </span>
      </div>
      <div style={{
        marginTop: 6, height: 3, borderRadius: 2,
        background: isDark ? '#21262d' : '#e8e8e8',
        overflow: 'hidden',
      }}>
        <div style={{
          height: '100%', borderRadius: 2,
          background: '#1677ff',
          width: total > 0 ? `${(current / total) * 100}%` : '0%',
          transition: 'width 0.3s ease',
        }} />
      </div>
    </div>
  )
}

export default function BugTracker({ bugs = [], isDark, compact = false }) {
  const selectedProjectName = useStore((s) => s.selectedProjectName)
  const quickFixBugs = useStore((s) => s.quickFixBugs)
  const isRunning = useStore((s) => s.isRunning)
  const fixProgress = useStore((s) => s.fixProgress)
  const executionTokenRuns = useStore((s) => s.executionTokenRuns)

  const isFixing = fixProgress.status === 'fixing'
  const isDone = fixProgress.status === 'done'

  if (!bugs || bugs.length === 0) {
    if (compact) return null
    return (
      <Empty
        description="暂无 Bug"
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        style={{ padding: '16px 0' }}
      />
    )
  }

  const handleFixAll = async () => {
    try {
      await quickFixBugs(selectedProjectName)
    } catch (e) {
      message.error(e.message || '修复失败')
    }
  }

  const handleFixSingle = async (bug) => {
    try {
      await quickFixBugs(selectedProjectName, { bugTitles: [bug.title] })
    } catch (e) {
      message.error(e.message || '修复失败')
    }
  }

  // 从 fixProgress.results 中查找 Bug 修复状态
  const getBugFixStatus = (bug) => {
    if (!isFixing && !isDone) return null
    const r = fixProgress.results.find((r) => r.id === bug.id || r.title === bug.title)
    return r?.status || null
  }

  // 最近一次 token 消耗（修复完成后显示）
  const lastTokenRun = isDone && executionTokenRuns.length > 0 ? executionTokenRuns[0] : null

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <Space size={6}>
          <BugOutlined style={{ color: '#f85149' }} />
          <span style={{ fontWeight: 600, fontSize: 13, color: isDark ? '#f0f6fc' : '#1f2328' }}>
            缺陷（{bugs.length}）
          </span>
        </Space>
        <Space size={8}>
          {isDone && lastTokenRun && (
            <Tag color="blue" style={{ margin: 0, fontSize: 11 }}>
              消耗 {formatTokens(lastTokenRun.total_tokens)} tokens
            </Tag>
          )}
          {bugs.length > 0 && (
            <Button
              size="small"
              type="primary"
              icon={isFixing ? <LoadingOutlined spin /> : <ToolOutlined />}
              disabled={isRunning}
              loading={isFixing}
              onClick={handleFixAll}
            >
              {isFixing ? '修复中...' : '全部修复'}
            </Button>
          )}
        </Space>
      </div>

      <FixResultBanner fixProgress={fixProgress} isDark={isDark} />
      <FixProgressBar fixProgress={fixProgress} isDark={isDark} />

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {bugs.map((bug, idx) => {
          const sev = SEVERITY_CONFIG[bug.severity] || SEVERITY_CONFIG.medium
          const bugFixStatus = getBugFixStatus(bug)
          const statusIcon = bugFixStatus ? FIX_STATUS_ICON[bugFixStatus] : null
          const statusText = bugFixStatus ? FIX_STATUS_TEXT[bugFixStatus] : null

          return (
            <div
              key={bug.id || idx}
              style={{
                padding: '10px 12px',
                borderRadius: 6,
                border: `1px solid ${isDark ? '#21262d' : '#e8e8e8'}`,
                background: isDark ? '#161b22' : '#ffffff',
                borderLeft: `3px solid ${sev.color}`,
                opacity: bugFixStatus === 'fixed' ? 0.6 : 1,
                transition: 'opacity 0.3s',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 4 }}>
                <div style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 6 }}>
                  <Tag
                    color={sev.color}
                    style={{ fontSize: 10, lineHeight: '16px', padding: '0 4px', margin: 0 }}
                  >
                    {sev.label}
                  </Tag>
                  <span style={{
                    fontWeight: 600, fontSize: 13,
                    color: isDark ? '#f0f6fc' : '#1f2328',
                    textDecoration: bugFixStatus === 'fixed' ? 'line-through' : 'none',
                  }}>
                    {bug.title || bug.id}
                  </span>
                  {statusIcon && (
                    <Tooltip title={statusText}>
                      {statusIcon}
                    </Tooltip>
                  )}
                </div>
                {bugFixStatus !== 'fixing' && (
                  <Button
                    size="small"
                    icon={<ToolOutlined />}
                    disabled={isRunning}
                    onClick={() => handleFixSingle(bug)}
                    style={{ flexShrink: 0 }}
                  >
                    修复
                  </Button>
                )}
                {bugFixStatus === 'fixing' && (
                  <Spin size="small" style={{ flexShrink: 0, marginTop: 2 }} />
                )}
              </div>
              {bug.description && (
                <div style={{ fontSize: 12, color: isDark ? '#8b949e' : '#656d76', marginBottom: 4, lineHeight: '18px' }}>
                  {bug.description}
                </div>
              )}
              {bug.affected_files && bug.affected_files.length > 0 && (
                <div style={{ fontSize: 11, color: isDark ? '#484f58' : '#aaa' }}>
                  文件: {bug.affected_files.join(', ')}
                </div>
              )}
              {bug.fix_suggestion && (
                <div style={{ fontSize: 11, color: isDark ? '#8b949e' : '#656d76', marginTop: 4, fontStyle: 'italic' }}>
                  建议: {bug.fix_suggestion}
                </div>
              )}
              {(bugFixStatus === 'failed' || bugFixStatus === 'unfixed') && (
                <div style={{
                  fontSize: 11, marginTop: 4, padding: '2px 6px', borderRadius: 3,
                  background: isDark ? '#f8514920' : '#fff2f0',
                  color: isDark ? '#f85149' : '#cf1322',
                  display: 'inline-block',
                }}>
                  {bugFixStatus === 'failed' ? '修复执行失败，可重试或人工介入' : '已修改但测试验证未通过'}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
