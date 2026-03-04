import { Card, Tag, Tooltip, Alert, Button } from 'antd'
import {
  CheckCircleFilled, CloseCircleFilled, SyncOutlined,
  ThunderboltOutlined, ClockCircleOutlined, FileOutlined,
  BugOutlined, UserOutlined, ToolOutlined, CaretRightOutlined,
  MessageOutlined, FileTextOutlined, ReloadOutlined,
  SettingOutlined, BulbOutlined,
} from '@ant-design/icons'
import useStore from '../../stores/useStore'
import { formatTokens, formatElapsed } from './utils'

const PHASE_CONFIG = {
  refine: { label: '优化', color: '#bc8cff', agent: '需求优化' },
  planning: { label: '规划', color: '#58a6ff', agent: '规划分析' },
  plan: { label: '规划', color: '#58a6ff', agent: '规划分析' },
  dev: { label: '开发', color: '#3fb950', agent: 'Coder AI' },
  test: { label: '测试', color: '#d29922', agent: 'Critique AI' },
  fix: { label: '修复', color: '#f85149', agent: 'Coder AI' },
}

const SEVERITY_COLORS = { high: '#f85149', critical: '#f85149', medium: '#d29922', low: '#8b949e' }

function AgentActivitySection({ iter, isDark, sectionKey }) {
  const storedCollapsed = useStore(s => s.collapsedSections[sectionKey])
  const toggleCollapsed = useStore(s => s.toggleSectionCollapsed)
  const expanded = storedCollapsed === undefined ? false : !storedCollapsed
  const agentLogs = iter.agentLogs || []
  const activities = iter.activities || []
  const files = Array.isArray(iter.filesChanged) ? iter.filesChanged : []
  const testResult = iter.testResult
  const taskVerified = iter.taskVerified
  const taskRegressions = iter.taskRegressions || []

  const keyLogs = agentLogs.filter(l => l.message && !l.message.startsWith('开始执行任务'))
  const toolCalls = activities.filter(a => a.type === 'tool_call' && a.tool)

  const hasContent = keyLogs.length > 0 || toolCalls.length > 0 || files.length > 0
    || testResult || taskVerified || taskRegressions.length > 0

  if (!hasContent) return null

  const dimColor = isDark ? '#8b949e' : '#656d76'
  const textColor = isDark ? '#c9d1d9' : '#1f2328'
  const borderColor = isDark ? '#21262d' : '#e8e8e8'

  return (
    <div style={{ marginTop: 8 }}>
      <div
        onClick={() => toggleCollapsed(sectionKey)}
        style={{
          display: 'flex', alignItems: 'center', gap: 6,
          cursor: 'pointer', fontSize: 12, color: dimColor, marginBottom: 6,
        }}
      >
        <ToolOutlined style={{ fontSize: 11 }} />
        <span>智能体活动详情</span>
        <span style={{ fontSize: 10, color: isDark ? '#484f58' : '#afb8c1' }}>
          ({toolCalls.length} 次工具调用{files.length > 0 ? `，${files.length} 个文件` : ''})
        </span>
        <CaretRightOutlined style={{
          fontSize: 9, transform: expanded ? 'rotate(90deg)' : 'none',
          transition: 'transform 0.2s',
        }} />
      </div>

      {expanded && (
        <div style={{
          padding: '8px 10px', borderRadius: 6,
          background: isDark ? 'rgba(13,17,23,0.6)' : '#f6f8fa',
          border: `1px solid ${borderColor}`,
          display: 'flex', flexDirection: 'column', gap: 8,
        }}>
          {keyLogs.map((log, i) => (
            <div key={i} style={{ display: 'flex', gap: 8, fontSize: 11, lineHeight: 1.5 }}>
              <MessageOutlined style={{ fontSize: 10, color: dimColor, marginTop: 3, flexShrink: 0 }} />
              <div>
                <span style={{ color: isDark ? '#58a6ff' : '#0969da', fontWeight: 500, marginRight: 6 }}>
                  {log.agent}
                </span>
                <span style={{ color: textColor, whiteSpace: 'pre-wrap' }}>
                  {log.message.replace(/^[\s\n]+/, '')}
                </span>
              </div>
            </div>
          ))}

          {toolCalls.length > 0 && (
            <div>
              <div style={{ fontSize: 11, color: dimColor, marginBottom: 4, display: 'flex', alignItems: 'center', gap: 4 }}>
                <ToolOutlined style={{ fontSize: 10 }} /> 工具调用
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                {(() => {
                  const toolCounts = {}
                  toolCalls.forEach(tc => {
                    toolCounts[tc.tool] = (toolCounts[tc.tool] || 0) + 1
                  })
                  return Object.entries(toolCounts).map(([tool, count]) => (
                    <Tag key={tool} style={{ fontSize: 10, margin: 0, fontFamily: 'monospace' }}>
                      {tool}{count > 1 ? ` ×${count}` : ''}
                    </Tag>
                  ))
                })()}
              </div>
            </div>
          )}

          {files.length > 0 && (
            <div>
              <div style={{ fontSize: 11, color: dimColor, marginBottom: 4, display: 'flex', alignItems: 'center', gap: 4 }}>
                <FileTextOutlined style={{ fontSize: 10 }} /> 创建/修改的文件
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                {files.map((f) => (
                  <Tag key={f} icon={<FileOutlined />} color="green" style={{ fontSize: 10, margin: 0 }}>{f}</Tag>
                ))}
              </div>
            </div>
          )}

          {testResult && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11 }}>
              {testResult.passed
                ? <CheckCircleFilled style={{ color: '#3fb950' }} />
                : <CloseCircleFilled style={{ color: '#f85149' }} />
              }
              <span style={{ color: textColor }}>
                测试结果: {testResult.passed ? '通过' : '未通过'}
                {testResult.total != null && ` (${testResult.total} 项)`}
              </span>
            </div>
          )}

          {taskRegressions.length > 0 && taskRegressions.map((reg, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11 }}>
              <ReloadOutlined style={{ color: '#d29922' }} />
              <span style={{ color: '#d29922' }}>
                {reg.taskId} 需重新验证 — {reg.reason || '共享文件被修改'}
              </span>
            </div>
          ))}

          {taskVerified && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11 }}>
              {taskVerified.passes
                ? <CheckCircleFilled style={{ color: '#3fb950' }} />
                : <CloseCircleFilled style={{ color: '#f85149' }} />
              }
              <span style={{ color: textColor }}>
                任务 {taskVerified.taskId} {taskVerified.passes ? '验证通过' : '验证未通过'}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

const FAILURE_MODE_LABEL = {
  dev_no_output: '开发无产出', test_regression: '测试回归',
  persistent_failure: '持续失败',
}
const STRATEGY_LABEL = {
  retry: '重试', rollback: '回滚', simplify: '简化', skip: '跳过',
}

function FailureAndReflectionSection({ isDark }) {
  const lastFailureAnalysis = useStore(s => s.lastFailureAnalysis)
  const lastReflection = useStore(s => s.lastReflection)

  if (!lastFailureAnalysis && !lastReflection) return null

  const dimColor = isDark ? '#8b949e' : '#656d76'
  const borderColor = isDark ? '#21262d' : '#e8e8e8'

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {lastFailureAnalysis && lastFailureAnalysis.mode && (
        <div style={{
          padding: '8px 10px', borderRadius: 6, fontSize: 11,
          background: isDark ? '#1a0f0f' : '#fff5f5',
          border: `1px solid ${isDark ? '#f8514922' : '#f8514933'}`,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
            <BulbOutlined style={{ fontSize: 11, color: '#d29922' }} />
            <span style={{ fontWeight: 500 }}>失败分析</span>
          </div>
          <div style={{ color: isDark ? '#c9d1d9' : '#1f2328' }}>
            模式: {FAILURE_MODE_LABEL[lastFailureAnalysis.mode] || lastFailureAnalysis.mode}
            {' · '}策略: {STRATEGY_LABEL[lastFailureAnalysis.strategy] || lastFailureAnalysis.strategy}
            {lastFailureAnalysis.shouldRollback && ' · 建议回滚'}
          </div>
        </div>
      )}
      {lastReflection && lastReflection.content && (
        <div style={{
          padding: '8px 10px', borderRadius: 6, fontSize: 11,
          background: isDark ? 'rgba(13,17,23,0.6)' : '#f6f8fa',
          border: `1px solid ${borderColor}`,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
            <BulbOutlined style={{ fontSize: 11, color: dimColor }} />
            <span style={{ fontWeight: 500, color: dimColor }}>根因分析（第 {lastReflection.round} 轮）</span>
          </div>
          <div style={{
            color: isDark ? '#c9d1d9' : '#1f2328',
            whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.5,
          }}>
            {lastReflection.content.slice(0, 500)}
            {lastReflection.content.length > 500 && '...'}
          </div>
        </div>
      )}
    </div>
  )
}

export default function IterationDetail() {
  const theme = useStore((s) => s.theme)
  const iterations = useStore((s) => s.iterationHistory)
  const selectedIteration = useStore((s) => s.selectedIteration)
  const isRunning = useStore((s) => s.isRunning)
  const selectedProjectName = useStore((s) => s.selectedProjectName)
  const resumeProject = useStore((s) => s.resumeProject)
  const quickFixBugs = useStore((s) => s.quickFixBugs)
  const setSettingsOpen = useStore((s) => s.setSettingsOpen)
  const isDark = theme === 'dark'

  const iter = iterations.find((i) => i.iteration === selectedIteration)
  if (!iter) return null

  const cfg = PHASE_CONFIG[iter.phase] || PHASE_CONFIG.dev
  const isLast = iterations[iterations.length - 1]?.iteration === iter.iteration
  const files = Array.isArray(iter.filesChanged) ? iter.filesChanged : []

  let statusEl
  if (isLast && isRunning) {
    statusEl = <Tag color="processing"><SyncOutlined spin style={{ marginRight: 3 }} />执行中</Tag>
  } else if (iter.success === true) {
    statusEl = <Tag icon={<CheckCircleFilled />} color="success">成功</Tag>
  } else if (iter.success === false) {
    statusEl = <Tag icon={<CloseCircleFilled />} color="error">失败</Tag>
  } else {
    statusEl = <Tag>未知</Tag>
  }

  const isFailed = iter.success === false && !(isLast && isRunning)
  const failedDevPhase = isFailed && (iter.phase === 'dev' || iter.phase === 'fix')
  const failedTestPhase = isFailed && iter.phase === 'test'

  return (
    <Card
      size="small"
      title={
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
          <span>迭代 #{iter.iteration}</span>
          <Tag color={cfg.color} style={{ margin: 0, border: 'none' }}>{cfg.label}</Tag>
          {statusEl}
          {iter.tokensUsed > 0 && (
            <span style={{ marginLeft: 'auto', fontSize: 11, color: isDark ? '#8b949e' : '#656d76', display: 'flex', alignItems: 'center', gap: 3 }}>
              <ThunderboltOutlined style={{ fontSize: 10 }} />
              {formatTokens(iter.tokensUsed)}
            </span>
          )}
        </div>
      }
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: 12 }}>
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', color: isDark ? '#8b949e' : '#656d76' }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <UserOutlined style={{ fontSize: 11 }} /> {cfg.agent}
          </span>
          {iter.elapsedSeconds > 0 && (
            <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <ClockCircleOutlined style={{ fontSize: 11 }} /> {formatElapsed(iter.elapsedSeconds)}
            </span>
          )}
        </div>

        {iter.error && (
          <Alert
            type="error"
            showIcon={false}
            message={
              <div style={{ fontSize: 12 }}>
                <div style={{ fontWeight: 500, marginBottom: 4 }}>失败原因</div>
                <div style={{ color: isDark ? '#c9d1d9' : '#1f2328', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                  {iter.error}
                </div>
              </div>
            }
            style={{ padding: '8px 12px' }}
          />
        )}

        {isFailed && !iter.error && (() => {
          const hasFiles = files.length > 0
          const hasBugs = iter.bugs?.length > 0
          const hasLogs = (iter.agentLogs || []).length > 0
          const lastLog = hasLogs ? iter.agentLogs[iter.agentLogs.length - 1] : null

          let hint
          if (failedDevPhase && !hasFiles) {
            hint = '智能体未生成任何文件即终止，通常是 LLM 返回异常（超时/超长/拒绝）'
          } else if (failedDevPhase && hasFiles) {
            hint = '已生成部分文件但未能完成全部编码，可能超出单次迭代的上下文容量'
          } else if (failedTestPhase && hasBugs) {
            hint = `测试发现 ${iter.bugs.length} 个缺陷未修复`
          } else if (failedTestPhase) {
            hint = '测试阶段异常退出'
          } else {
            hint = '该迭代未能成功完成'
          }

          return (
            <Alert
              type="warning"
              showIcon={false}
              message={
                <div style={{ fontSize: 12 }}>
                  <div>{hint}</div>
                  {lastLog && (
                    <div style={{ marginTop: 4, color: isDark ? '#8b949e' : '#656d76', fontSize: 11 }}>
                      最后日志: {lastLog.message?.slice(0, 120)}{lastLog.message?.length > 120 ? '...' : ''}
                    </div>
                  )}
                  {!hasLogs && (
                    <div style={{ marginTop: 4, color: isDark ? '#8b949e' : '#656d76', fontSize: 11 }}>
                      该 session 未记录详细错误（后续运行将自动记录）
                    </div>
                  )}
                </div>
              }
              style={{ padding: '8px 12px' }}
            />
          )
        })()}

        {iter.storyTitle && (
          <div>
            <span style={{ color: isDark ? '#6e7681' : '#8c959f', marginRight: 6 }}>目标:</span>
            <span style={{ color: isDark ? '#c9d1d9' : '#1f2328' }}>
              {iter.storyId ? `[${iter.storyId}] ` : ''}{iter.storyTitle}
            </span>
          </div>
        )}
        {!iter.storyTitle && (iter.phase === 'test' || iter.phase === 'fix') && (
          <div>
            <span style={{ color: isDark ? '#6e7681' : '#8c959f', marginRight: 6 }}>目标:</span>
            <span style={{ color: isDark ? '#c9d1d9' : '#1f2328' }}>
              {iter.phase === 'test' ? '验证所有任务' : '修复未通过的缺陷'}
            </span>
          </div>
        )}

        {files.length > 0 && (
          <div>
            <div style={{ color: isDark ? '#6e7681' : '#8c959f', marginBottom: 4, display: 'flex', alignItems: 'center', gap: 4 }}>
              <FileOutlined style={{ fontSize: 11 }} /> 文件变更 ({files.length})
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
              {files.slice(0, 8).map((f) => (
                <Tag key={f} style={{ fontSize: 11, margin: 0 }}>{f}</Tag>
              ))}
              {files.length > 8 && (
                <Tag style={{ fontSize: 11, margin: 0 }}>+{files.length - 8} 个</Tag>
              )}
            </div>
          </div>
        )}

        {iter.bugs?.length > 0 && (
          <div>
            <div style={{ color: isDark ? '#6e7681' : '#8c959f', marginBottom: 4, display: 'flex', alignItems: 'center', gap: 4 }}>
              <BugOutlined style={{ fontSize: 11 }} /> 缺陷（{iter.bugs.length}）
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {iter.bugs.slice(0, 5).map((bug, i) => {
                const severity = bug.severity || 'medium'
                const title = bug.title || bug.description?.slice(0, 60) || `缺陷 ${i + 1}`
                const taskId = bug.task_id || ''
                return (
                  <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11 }}>
                    <Tag color={SEVERITY_COLORS[severity] || '#8b949e'} style={{ margin: 0, fontSize: 10, lineHeight: '16px', padding: '0 5px', minWidth: 40, textAlign: 'center' }}>
                      {severity}
                    </Tag>
                    <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: isDark ? '#c9d1d9' : '#1f2328' }}>
                      {title}
                    </span>
                    {taskId && (
                      <span style={{ fontSize: 10, color: isDark ? '#484f58' : '#bbb', fontFamily: 'monospace', flexShrink: 0 }}>
                        {taskId}
                      </span>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        )}

        <FailureAndReflectionSection isDark={isDark} />

        <AgentActivitySection iter={iter} isDark={isDark} sectionKey={`iter-agent-${iter.iteration}`} />

        {isFailed && !isRunning && (
          <div style={{
            marginTop: 4, paddingTop: 8,
            borderTop: `1px solid ${isDark ? '#21262d' : '#e8e8e8'}`,
          }}>
            <div style={{ fontSize: 11, color: isDark ? '#8b949e' : '#656d76', marginBottom: 6, display: 'flex', alignItems: 'center', gap: 4 }}>
              <BulbOutlined style={{ fontSize: 10 }} /> 可尝试的操作
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {iter.bugs?.length > 0 && (
                <Button
                  size="small"
                  type="primary"
                  icon={<BugOutlined />}
                  onClick={() => quickFixBugs(selectedProjectName)}
                >
                  修复缺陷
                </Button>
              )}
              {(failedTestPhase || iter.bugs?.length > 0) && (
                <Button
                  size="small"
                  icon={<ReloadOutlined />}
                  onClick={() => resumeProject(selectedProjectName)}
                >
                  继续执行
                </Button>
              )}
              <Button
                size="small"
                icon={<SettingOutlined />}
                onClick={() => setSettingsOpen(true)}
              >
                切换模型
              </Button>
            </div>
            {failedDevPhase && (
              <div style={{ marginTop: 6, fontSize: 11, color: isDark ? '#8b949e' : '#656d76' }}>
                代码生成失败时，重跑测试通常无效。建议在左侧简化需求描述后重新运行，或切换更强的模型。
              </div>
            )}
          </div>
        )}
      </div>
    </Card>
  )
}
