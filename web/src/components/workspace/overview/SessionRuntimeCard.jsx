import { useMemo, useState } from 'react'
import {
  Card, Tag, Alert, Progress, Button,
} from 'antd'
import {
  CheckCircleFilled, CloseCircleFilled, SyncOutlined, ClockCircleOutlined,
  LoadingOutlined, PlayCircleOutlined, PauseCircleOutlined, ToolOutlined,
  FileAddOutlined, CodeOutlined, DownOutlined, RightOutlined,
} from '@ant-design/icons'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import useStore from '../../../stores/useStore'
import PhaseProgress from '../../shared/PhaseProgress'
import { formatTokenCount, estimateTokenCost } from '../helpers'

const COMPLEXITY_LABEL = { simple: '简单', medium: '中等', complex: '复杂' }
const COMPLEXITY_COLOR = { simple: '#3fb950', medium: '#d29922', complex: '#f85149' }

function parseAgentActions(content) {
  if (!content) return []
  const actions = []
  const lines = content.split('\n')
  for (const line of lines) {
    const writeMatch = line.match(/(?:write_file|create_file|Writing|Creating)\s*[:(]\s*['"`]?([^\s'"`)]+)/)
    if (writeMatch) {
      actions.push({ type: 'file', icon: <FileAddOutlined />, label: writeMatch[1].replace(/^\/workspace\//, '') })
      continue
    }
    const shellMatch = line.match(/(?:shell|execute|Running|run_command)[:(]\s*['"`]?(.{3,60})/)
    if (shellMatch) {
      actions.push({ type: 'cmd', icon: <CodeOutlined />, label: shellMatch[1].replace(/['"`]/g, '').trim() })
      continue
    }
  }
  return actions.slice(-5)
}

function AgentActivityPanel({ isDark, agentThinking, newlyCreatedFiles }) {
  const [thinkingExpanded, setThinkingExpanded] = useState(false)
  const actions = useMemo(() => parseAgentActions(agentThinking?.content), [agentThinking?.content])
  const fileCount = newlyCreatedFiles?.length || 0
  const dimColor = isDark ? '#6e7681' : '#8c959f'

  if (!agentThinking?.content && fileCount === 0) return null

  return (
    <div style={{
      marginTop: 10, borderRadius: 6,
      background: isDark ? '#161b22' : '#f6f8fa',
      border: `1px solid ${isDark ? '#21262d' : '#eef1f4'}`,
      overflow: 'hidden',
    }}>
      {fileCount > 0 && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 6,
          padding: '6px 10px', fontSize: 11, color: isDark ? '#3fb950' : '#1a7f37',
          borderBottom: agentThinking?.content ? `1px solid ${isDark ? '#21262d' : '#eef1f4'}` : 'none',
        }}>
          <FileAddOutlined style={{ fontSize: 12 }} />
          <span style={{ fontWeight: 500 }}>已生成 {fileCount} 个文件</span>
        </div>
      )}

      {actions.length > 0 && (
        <div style={{ padding: '4px 10px' }}>
          {actions.map((a, i) => (
            <div key={i} style={{
              display: 'flex', alignItems: 'center', gap: 6, padding: '3px 0',
              fontSize: 11, color: isDark ? '#8b949e' : '#656d76',
            }}>
              <span style={{ color: a.type === 'file' ? '#3fb950' : '#58a6ff', fontSize: 11, flexShrink: 0 }}>{a.icon}</span>
              <span style={{
                fontFamily: 'monospace', fontSize: 10,
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              }}>{a.label}</span>
            </div>
          ))}
        </div>
      )}

      {agentThinking?.content && actions.length === 0 && (
        <div style={{ padding: '6px 10px' }}>
          <div
            onClick={() => setThinkingExpanded(!thinkingExpanded)}
            style={{
              display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer',
              fontSize: 11, color: dimColor, userSelect: 'none',
            }}
          >
            <span style={{ width: 12, textAlign: 'center' }}>
              {thinkingExpanded
                ? <DownOutlined style={{ fontSize: 8 }} />
                : <RightOutlined style={{ fontSize: 8 }} />}
            </span>
            <span style={{ fontWeight: 500 }}>{agentThinking.agent || 'Agent'} 思考中</span>
          </div>
          {thinkingExpanded && (
            <div className="requirement-markdown" style={{
              marginTop: 4, fontSize: 11, lineHeight: 1.6,
              maxHeight: 120, overflow: 'auto',
              color: isDark ? '#8b949e' : '#656d76',
              wordBreak: 'break-word',
            }}>
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {agentThinking.content.slice(0, 500) + (agentThinking.content.length > 500 ? '\n...' : '')}
              </ReactMarkdown>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export function SessionRuntime({ isDark, onStop }) {
  const currentPhase = useStore(s => s.currentPhase)
  const sandboxStatus = useStore(s => s.sandboxStatus)
  const planningProgress = useStore(s => s.planningProgress)
  const agentThinking = useStore(s => s.agentThinking)
  const executionTaskList = useStore(s => s.executionTaskList)
  const executionStats = useStore(s => s.executionStats)
  const executionComplexity = useStore(s => s.executionComplexity)
  const executionFiles = useStore(s => s.executionFiles)
  const newlyCreatedFiles = useStore(s => s.newlyCreatedFiles)
  const lastDevSelfTest = useStore(s => s.lastDevSelfTest)
  const smokeCheckIssues = useStore(s => s.smokeCheckIssues)
  const deployGateStatus = useStore(s => s.deployGateStatus)
  const planningAcceptanceResult = useStore(s => s.planningAcceptanceResult)
  const lastPmDecision = useStore(s => s.lastPmDecision)

  const hasTasks = executionTaskList.length > 0
  const verifiedCount = executionTaskList.filter(t => t.passes || t.status === 'verified').length
  const totalTasks = executionTaskList.length
  const fileCount = executionFiles?.length || 0

  return (
    <Card size="small" style={{ marginBottom: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <SyncOutlined spin style={{ color: '#58a6ff', fontSize: 16 }} />
        <span style={{ fontSize: 14, fontWeight: 600, color: isDark ? '#e6edf3' : '#1f2328' }}>
          执行中
        </span>
        <PhaseProgress />
        <span style={{ flex: 1 }} />
        {fileCount > 0 && (
          <Tag style={{ margin: 0, fontSize: 10, lineHeight: '16px', padding: '0 5px', borderRadius: 10 }}>
            <FileAddOutlined style={{ marginRight: 3 }} />{fileCount} 文件
          </Tag>
        )}
        {executionComplexity && (
          <Tag color={COMPLEXITY_COLOR[executionComplexity] || '#8b949e'}
            style={{ margin: 0, fontSize: 10, lineHeight: '16px', padding: '0 5px' }}>
            {COMPLEXITY_LABEL[executionComplexity] || executionComplexity}
          </Tag>
        )}
        {onStop && (
          <Button size="small" danger icon={<PauseCircleOutlined />} onClick={onStop}>
            停止
          </Button>
        )}
      </div>

      {/* 沙箱准备阶段 */}
      {!sandboxStatus.ready && sandboxStatus.step && (
        <div style={{ marginBottom: 10 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
            <LoadingOutlined style={{ color: '#58a6ff' }} />
            <span>准备沙箱环境</span>
          </div>
          <Progress percent={sandboxStatus.progress} size="small" strokeColor="#58a6ff" style={{ maxWidth: 300, marginTop: 4 }} />
          <div style={{ fontSize: 11, color: isDark ? '#8b949e' : '#656d76', marginTop: 2 }}>{sandboxStatus.message}</div>
        </div>
      )}

      {/* S-004: PM 分析阶段 — 显示规划子步骤或默认占位文案 */}
      {!hasTasks && sandboxStatus.ready && (
        <div style={{ marginBottom: 10 }}>
          {planningProgress?.steps?.length > 0 ? (
            <div>
              {planningProgress.steps.map((s, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '2px 0', fontSize: 12 }}>
                  {s.completed
                    ? <CheckCircleFilled style={{ color: '#3fb950', fontSize: 12 }} />
                    : <SyncOutlined spin style={{ color: '#58a6ff', fontSize: 12 }} />}
                  <span style={{ color: s.completed ? (isDark ? '#8b949e' : '#656d76') : (isDark ? '#e6edf3' : '#1f2328') }}>
                    {s.message}
                  </span>
                </div>
              ))}
              <Progress
                percent={planningProgress.progress || 0} size="small"
                strokeColor="#58a6ff" style={{ maxWidth: 300, marginTop: 6 }}
                format={p => <span style={{ fontSize: 10 }}>{p}%</span>}
              />
            </div>
          ) : (
            // S-004: 无子步骤时显示默认三段式占位，提示规划正在进行
            <div>
              {[
                { label: '分析需求和约束', done: false },
                { label: '设计技术架构', done: false },
                { label: '拆解实现步骤', done: false },
              ].map((s, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '2px 0', fontSize: 12 }}>
                  <SyncOutlined spin={i === 0} style={{ color: i === 0 ? '#58a6ff' : (isDark ? '#30363d' : '#d0d7de'), fontSize: 12 }} />
                  <span style={{ color: i === 0 ? (isDark ? '#e6edf3' : '#1f2328') : (isDark ? '#484f58' : '#c6cbd1') }}>
                    {s.label}
                  </span>
                </div>
              ))}
              <div style={{ fontSize: 11, color: isDark ? '#484f58' : '#afb8c1', marginTop: 6 }}>
                {currentPhase || 'AI 规划中...'}
              </div>
            </div>
          )}
        </div>
      )}

      {/* 有任务后的进度 */}
      {hasTasks && (() => {
        const activeTask = executionTaskList.find(t => t.status === 'in_progress')
        const completedCount = executionTaskList.filter(t => t.status !== 'pending' && t.status !== 'in_progress').length
        const pendingCount = executionTaskList.filter(t => t.status === 'pending').length
        const unverifiedCount = executionTaskList.filter(t => !t.passes && t.status !== 'verified' && t.status !== 'pending').length
        const activeIdx = activeTask ? executionTaskList.indexOf(activeTask) + 1 : completedCount
        return (
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <Progress
                type="circle" size={48}
                percent={totalTasks > 0 ? Math.round((completedCount / totalTasks) * 100) : 0}
                strokeColor="#3fb950"
                format={() => <span style={{ fontSize: 12, fontWeight: 600 }}>{completedCount}/{totalTasks}</span>}
              />
              <div style={{ flex: 1, minWidth: 0 }}>
                {activeTask ? (
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 600, color: isDark ? '#e6edf3' : '#1f2328' }}>
                      <SyncOutlined spin style={{ color: '#58a6ff', fontSize: 11, marginRight: 6 }} />
                      <span style={{ fontSize: 11, color: '#58a6ff', marginRight: 4 }}>[{activeIdx}/{totalTasks}]</span>
                      {activeTask.title}
                    </div>
                    <div style={{ fontSize: 11, color: isDark ? '#8b949e' : '#656d76', marginTop: 2 }}>
                      {currentPhase || '处理中'}
                      {completedCount > 0 && ` · 已完成 ${completedCount}`}
                      {pendingCount > 0 && ` · 等待 ${pendingCount}`}
                      {executionStats.tokens > 0 && ` · ${formatTokenCount(executionStats.tokens)}`}
                    </div>
                  </div>
                ) : (
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 600, color: isDark ? '#e6edf3' : '#1f2328' }}>
                      <SyncOutlined spin style={{ color: '#58a6ff', fontSize: 11, marginRight: 6 }} />
                      {currentPhase || '处理中'}
                    </div>
                    <div style={{ fontSize: 11, color: isDark ? '#8b949e' : '#656d76', marginTop: 2 }}>
                      {unverifiedCount > 0 && `${unverifiedCount} 个任务待验证`}
                      {verifiedCount > 0 && ` · ${verifiedCount} 个已通过`}
                      {executionStats.tokens > 0 && ` · ${formatTokenCount(executionStats.tokens)}`}
                    </div>
                  </div>
                )}
              </div>
            </div>
            {/* 任务列表缩略 */}
            <div style={{ marginTop: 8, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
              {executionTaskList.map((t, i) => {
                const isPassed = t.passes || t.status === 'verified'
                const isActive = t.status === 'in_progress'
                const isFailed = t.status === 'failed'
                const bg = isPassed ? '#3fb950' : isActive ? '#58a6ff' : isFailed ? '#f85149' : (isDark ? '#30363d' : '#d0d7de')
                return (
                  <div key={t.id || i} title={`${t.id} ${t.title}`} style={{
                    width: 8, height: 8, borderRadius: '50%', background: bg,
                    animation: isActive ? 'phaseProgressPulse 1.5s infinite' : 'none',
                  }} />
                )
              })}
            </div>
          </div>
        )
      })()}

      {/* Dev 自测结果 */}
      {lastDevSelfTest && (
        <div style={{
          marginTop: 8, padding: '6px 10px', borderRadius: 6, fontSize: 11,
          background: lastDevSelfTest.passed ? (isDark ? '#0d2818' : '#f0fff4') : (isDark ? '#1a0f0f' : '#fff5f5'),
          border: `1px solid ${lastDevSelfTest.passed ? '#3fb95033' : '#f8514933'}`,
          display: 'flex', alignItems: 'center', gap: 6,
        }}>
          {lastDevSelfTest.passed
            ? <CheckCircleFilled style={{ color: '#3fb950', fontSize: 11 }} />
            : <CloseCircleFilled style={{ color: '#f85149', fontSize: 11 }} />}
          <span>开发者自测{lastDevSelfTest.passed ? '通过' : '未通过'}</span>
          {lastDevSelfTest.taskId && (
            <span style={{ color: isDark ? '#6e7681' : '#8c959f' }}>({lastDevSelfTest.taskId})</span>
          )}
        </div>
      )}

      {/* 冒烟检查警告 */}
      {smokeCheckIssues.length > 0 && (
        <Alert
          type="warning" showIcon
          message={`冒烟检查发现 ${smokeCheckIssues.length} 个问题`}
          description={smokeCheckIssues.slice(0, 3).join('；')}
          style={{ marginTop: 8, fontSize: 11, padding: '6px 10px' }}
        />
      )}

      {/* 部署 Gate 状态 */}
      {deployGateStatus && deployGateStatus.status && (
        <div style={{
          marginTop: 8, padding: '6px 10px', borderRadius: 6, fontSize: 11,
          background: isDark ? '#161b22' : '#f6f8fa',
          display: 'flex', alignItems: 'center', gap: 6,
        }}>
          {deployGateStatus.status === 'starting' && <LoadingOutlined style={{ color: '#58a6ff', fontSize: 11 }} />}
          {deployGateStatus.status === 'success' && <CheckCircleFilled style={{ color: '#3fb950', fontSize: 11 }} />}
          {deployGateStatus.status === 'failed' && <CloseCircleFilled style={{ color: '#f85149', fontSize: 11 }} />}
          <span>
            {deployGateStatus.status === 'starting' && '正在检查应用是否可启动...'}
            {deployGateStatus.status === 'success' && `应用启动成功${deployGateStatus.url ? `（${deployGateStatus.url}）` : ''}`}
            {deployGateStatus.status === 'failed' && (deployGateStatus.message || '应用启动失败')}
          </span>
        </div>
      )}

      {/* PM 验收结果 */}
      {planningAcceptanceResult && (
        <div style={{
          marginTop: 8, padding: '6px 10px', borderRadius: 6, fontSize: 11,
          background: planningAcceptanceResult.passed ? (isDark ? '#0d2818' : '#f0fff4') : (isDark ? '#1a0f0f' : '#fff5f5'),
          border: `1px solid ${planningAcceptanceResult.passed ? '#3fb95033' : '#f8514933'}`,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            {planningAcceptanceResult.passed
              ? <CheckCircleFilled style={{ color: '#3fb950', fontSize: 11 }} />
              : <CloseCircleFilled style={{ color: '#f85149', fontSize: 11 }} />}
            <span style={{ fontWeight: 500 }}>
              验收{planningAcceptanceResult.passed ? '通过' : '未通过'}
              {planningAcceptanceResult.score && ` · 评分: ${planningAcceptanceResult.score}`}
            </span>
          </div>
          {planningAcceptanceResult.answer && (
            <div style={{ marginTop: 4, color: isDark ? '#8b949e' : '#656d76' }}>
              {planningAcceptanceResult.answer.slice(0, 200)}
            </div>
          )}
        </div>
      )}

      {/* PM 决策提示 */}
      {lastPmDecision && lastPmDecision.action && (
        <div style={{
          marginTop: 8, padding: '6px 10px', borderRadius: 6, fontSize: 11,
          background: isDark ? '#161b22' : '#f6f8fa',
          border: `1px solid ${isDark ? '#30363d' : '#d0d7de'}`,
        }}>
          <span style={{ fontWeight: 500 }}>
            {lastPmDecision.userMessage || `PM 决策: ${lastPmDecision.action}`}
          </span>
          {lastPmDecision.reason && (
            <div style={{ marginTop: 2, color: isDark ? '#8b949e' : '#656d76' }}>
              {lastPmDecision.reason.slice(0, 150)}
            </div>
          )}
        </div>
      )}

      {/* Agent 活动面板（结构化） */}
      <AgentActivityPanel isDark={isDark} agentThinking={agentThinking} newlyCreatedFiles={newlyCreatedFiles} />
    </Card>
  )
}

export function TaskItem({ task, isDark, onFix }) {
  const isPassed = task.passes || task.status === 'verified'
  const isRunning = task.status === 'in_progress'
  const isFailed = task.status === 'failed'
  const isAwaitingVerification = !isPassed && !isFailed && task.status === 'completed'

  const icon = isPassed
    ? <CheckCircleFilled style={{ color: '#3fb950', fontSize: 12 }} />
    : isRunning
      ? <SyncOutlined spin style={{ color: '#58a6ff', fontSize: 12 }} />
      : isFailed
        ? <CloseCircleFilled style={{ color: '#f85149', fontSize: 12 }} />
        : isAwaitingVerification
          ? <ClockCircleOutlined style={{ color: '#d29922', fontSize: 12 }} />
          : <ClockCircleOutlined style={{ color: '#8b949e', fontSize: 12 }} />

  const dimColor = isDark ? '#6e7681' : '#8c959f'

  return (
    <div style={{ padding: '4px 0 4px 24px', fontSize: 12 }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 6 }}>
        <span style={{ marginTop: 1 }}>{icon}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <span style={{ fontWeight: isRunning ? 600 : 400, color: isDark ? '#c9d1d9' : '#1f2328' }}>
            {task.id} {task.title}
          </span>
          {isRunning && <span style={{ fontSize: 10, color: '#58a6ff', marginLeft: 6 }}>开发中</span>}
          {isAwaitingVerification && <span style={{ fontSize: 10, color: '#d29922', marginLeft: 6 }}>待验证</span>}
        </div>
        {task.elapsed_seconds > 0 && (
          <span style={{ color: dimColor, fontFamily: 'monospace', fontSize: 10, flexShrink: 0 }}>
            {task.elapsed_seconds >= 60
              ? `${Math.floor(task.elapsed_seconds / 60)}m${Math.round(task.elapsed_seconds % 60)}s`
              : `${Math.round(task.elapsed_seconds)}s`}
          </span>
        )}
        {task.tokens_used > 0 && (
          <span style={{ color: dimColor, fontFamily: 'monospace', fontSize: 10, flexShrink: 0 }}>
            {formatTokenCount(task.tokens_used)}
          </span>
        )}
        {isFailed && onFix && (
          <Button size="small" type="link" style={{ fontSize: 11, padding: '0 4px', height: 'auto' }}
            icon={<ToolOutlined style={{ fontSize: 10 }} />}
            onClick={(e) => { e.stopPropagation(); onFix(task) }}>
            修复
          </Button>
        )}
      </div>
      {isFailed && (
        <div style={{
          marginTop: 4, marginLeft: 18, padding: '6px 8px', borderRadius: 4,
          background: isDark ? '#1a0f0f' : '#fff5f5', fontSize: 11,
          color: isDark ? '#f85149' : '#cf222e', lineHeight: 1.5,
        }}>
          {task.error_info?.message || task.verification_notes || task.error || '验证未通过'}
          {task.error_info?.file_path && (
            <div style={{ color: isDark ? '#6e7681' : '#8c959f', marginTop: 2, fontSize: 10 }}>
              {task.error_info.file_path}{task.error_info.line_number ? `:${task.error_info.line_number}` : ''}
            </div>
          )}
          {task.files?.length > 0 && (
            <div style={{ color: isDark ? '#6e7681' : '#8c959f', marginTop: 2, fontSize: 10 }}>
              相关文件: {task.files.slice(0, 3).join(', ')}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export function ExecutionResult({ isDark, onRetry }) {
  const executionSummary = useStore(s => s.executionSummary)
  const executionTaskList = useStore(s => s.executionTaskList)
  const executionStats = useStore(s => s.executionStats)
  const executionFailure = useStore(s => s.executionFailure)
  const setActiveTab = useStore(s => s.setActiveTab)
  const storeProject = useStore(s => s.getSelectedProject)()
  const tokenRuns = useStore(s => s.executionTokenRuns)
  const expectedVersion = useStore(s => s.executionExpectedVersion)
  const executionPlanMd = useStore(s => s.executionPlanMd)
  const previewErrors = useStore(s => s.previewErrors) || []

  if (!executionSummary && !executionFailure) return null

  const version = expectedVersion || executionSummary?.version || storeProject?.version || '1.0.0'
  const hasLiveTasks = executionTaskList.length > 0
  const verifiedCount = hasLiveTasks
    ? executionTaskList.filter(t => t.passes || t.status === 'verified').length
    : (executionSummary?.tasks_verified ?? 0)
  const totalTasks = hasLiveTasks ? executionTaskList.length : (executionSummary?.tasks_total ?? 0)
  const success = totalTasks > 0 ? verifiedCount === totalTasks : !!executionSummary?.success
  const progressPercent = totalTasks > 0 ? Math.round((verifiedCount / totalTasks) * 100) : 0

  const failureReason = executionFailure?.reason
    || executionSummary?.failure_reason
    || (executionSummary?.success === false && executionSummary?.summary)
    || null

  const latestRun = tokenRuns?.[0]
  const startedAt = latestRun?.started_at
  const elapsed = executionStats.elapsed || latestRun?.elapsed_seconds || 0
  const timeRange = useMemo(() => {
    if (!startedAt) return ''
    const fmt = (ts) => new Date(ts * 1000).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
    return `${fmt(startedAt)} → ${fmt(startedAt + Math.round(elapsed))}`
  }, [startedAt, elapsed])

  // R-016: 有预览错误时降级显示橙色警告，但不改变任务通过判定
  const hasPreviewErrors = previewErrors.length > 0
  const statusColor = success ? (hasPreviewErrors ? '#d29922' : '#3fb950') : '#f85149'
  const mutedColor = isDark ? '#8b949e' : '#656d76'
  const dimColor = isDark ? '#6e7681' : '#8c959f'

  return (
    <Card size="small" style={{ marginBottom: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: totalTasks > 0 ? 10 : 0 }}>
        {success && !hasPreviewErrors
          ? <CheckCircleFilled style={{ fontSize: 20, color: statusColor }} />
          : success && hasPreviewErrors
          ? <span style={{ fontSize: 20, color: statusColor }}>⚠️</span>
          : <CloseCircleFilled style={{ fontSize: 20, color: statusColor }} />
        }
        <Tag style={{
          margin: 0, fontSize: 11, fontWeight: 600, fontFamily: 'monospace',
          border: 'none', background: isDark ? '#21262d' : '#eef1f4',
          color: isDark ? '#c9d1d9' : '#1f2328',
        }}>
          v{version}
        </Tag>
        <div style={{ flex: 1 }}>
          <span style={{ fontSize: 14, fontWeight: 600 }}>
            {totalTasks === 0 && !success ? '规划失败'
              : success ? `${totalTasks}/${totalTasks} 个任务通过`
              : `${verifiedCount}/${totalTasks} 个任务通过`}
          </span>
          {/* R-016: 预览有 JS 错误时显示警告标签 */}
          {success && hasPreviewErrors && (
            <Tag color="warning" style={{ marginLeft: 8, fontSize: 10 }}>
              预览有异常
            </Tag>
          )}
          <span style={{ fontSize: 11, color: mutedColor, marginLeft: 8 }}>
            {timeRange || (elapsed > 0 && `耗时 ${elapsed >= 60 ? `${(elapsed / 60).toFixed(0)}m${(elapsed % 60).toFixed(0)}s` : `${elapsed.toFixed(0)}s`}`)}
            {executionStats.tokens > 0 && (() => {
              const cost = estimateTokenCost(executionStats.tokens)
              return ` · 消耗 ${formatTokenCount(executionStats.tokens)}${cost ? ` (${cost})` : ''}`
            })()}
          </span>
        </div>
        {onRetry && (!success || !executionPlanMd) && (
          <Button size="small" type={success ? "default" : "primary"} icon={<PlayCircleOutlined />} onClick={onRetry}>
            {success ? "重新执行" : "重试"}
          </Button>
        )}
        <Progress type="circle" size={40} percent={progressPercent}
          strokeColor={statusColor}
          format={() => <span style={{ fontSize: 10 }}>{progressPercent}%</span>}
        />
      </div>

      {/* R-016: 预览运行时错误警告 */}
      {success && hasPreviewErrors && (
        <div style={{
          margin: '6px 0', padding: '6px 10px', borderRadius: 6, fontSize: 11,
          background: isDark ? '#1a1200' : '#fffbe6',
          border: `1px solid ${isDark ? '#d2992266' : '#ffe58f'}`,
        }}>
          <div style={{ fontWeight: 500, color: '#d29922', marginBottom: 4 }}>
            ⚠️ 检测到 {previewErrors.length} 个预览运行时错误
          </div>
          {previewErrors.slice(0, 3).map((e, i) => (
            <div key={i} style={{ fontFamily: 'monospace', fontSize: 10, color: isDark ? '#8b949e' : '#656d76', lineHeight: 1.5 }}>
              {e.type}: {e.message?.slice(0, 120)}
            </div>
          ))}
        </div>
      )}

      {/* 任务列表 */}
      {totalTasks > 0 && executionTaskList.length > 0 && (
        <div style={{ borderTop: `1px solid ${isDark ? '#21262d' : '#eef1f4'}`, paddingTop: 8 }}>
          {executionTaskList.map((t, i) => {
            const isPassed = t.passes || t.status === 'verified'
            const isFailed = t.status === 'failed' || (!t.passes && t.status !== 'pending' && t.status !== 'verified' && t.status !== 'in_progress' && t.status !== 'completed')
            const isPending = t.status === 'pending'
            const isAwaiting = !isPassed && !isFailed && t.status === 'completed'
            const failReason = t.error_info?.message || t.verification_notes || t.error || ''
            const failFile = t.error_info?.file_path
              ? `${t.error_info.file_path}${t.error_info.line_number ? ':' + t.error_info.line_number : ''}`
              : ''
            const icon = isPassed
              ? <CheckCircleFilled style={{ color: '#3fb950', fontSize: 12 }} />
              : isFailed
                ? <CloseCircleFilled style={{ color: '#f85149', fontSize: 12 }} />
                : isAwaiting
                  ? <ClockCircleOutlined style={{ color: '#d29922', fontSize: 12 }} />
                  : <ClockCircleOutlined style={{ color: dimColor, fontSize: 12 }} />
            return (
              <div key={t.id || i}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '5px 0', fontSize: 12 }}>
                  <span style={{ flexShrink: 0 }}>{icon}</span>
                  <span style={{ color: isDark ? '#8b949e' : '#656d76', fontFamily: 'monospace', fontSize: 11, flexShrink: 0 }}>{t.id}</span>
                  <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: isDark ? '#c9d1d9' : '#1f2328' }}>{t.title}</span>
                  {t.elapsed_seconds > 0 && (
                    <span style={{ color: dimColor, fontSize: 10, fontFamily: 'monospace', flexShrink: 0 }}>
                      {t.elapsed_seconds >= 60 ? `${Math.floor(t.elapsed_seconds / 60)}m${Math.round(t.elapsed_seconds % 60)}s` : `${Math.round(t.elapsed_seconds)}s`}
                    </span>
                  )}
                  {t.tokens_used > 0 && <span style={{ color: dimColor, fontSize: 10, fontFamily: 'monospace', flexShrink: 0 }}>{formatTokenCount(t.tokens_used)}</span>}
                  {isPending && <span style={{ color: dimColor, fontSize: 11, flexShrink: 0 }}>待执行</span>}
                  {isAwaiting && <span style={{ color: '#d29922', fontSize: 11, flexShrink: 0 }}>待验证</span>}
                </div>
                {isFailed && failReason && <div style={{ paddingLeft: 28, fontSize: 11, color: '#f85149', marginBottom: 2, lineHeight: 1.5 }}>{failReason}</div>}
                {isFailed && failFile && <div style={{ paddingLeft: 28, fontSize: 10, color: dimColor, marginBottom: 2 }}>{failFile}</div>}
              </div>
            )
          })}
        </div>
      )}

      {!success && failureReason && (
        <div style={{
          borderTop: `1px solid ${isDark ? '#21262d' : '#eef1f4'}`,
          padding: '8px 0', fontSize: 12, color: '#f85149', lineHeight: 1.6,
          display: 'flex', alignItems: 'baseline', gap: 8,
        }}>
          <span>{failureReason}</span>
          {executionFailure?.detail && (
            <span
              style={{ color: isDark ? '#58a6ff' : '#0969da', cursor: 'pointer', fontSize: 11, flexShrink: 0, whiteSpace: 'nowrap' }}
              onClick={() => setActiveTab('log')}
            >
              查看日志 →
            </span>
          )}
        </div>
      )}
    </Card>
  )
}
