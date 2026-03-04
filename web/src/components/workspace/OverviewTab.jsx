import { useState } from 'react'
import {
  Card, Typography, Tag, Alert, Progress, Row, Col, Statistic,
  Button, Empty,
} from 'antd'
import {
  CheckCircleFilled, CloseCircleFilled, SyncOutlined, ClockCircleOutlined,
  LoadingOutlined, CaretRightOutlined, BugOutlined, BulbOutlined,
  NumberOutlined, FileTextOutlined, MinusCircleOutlined, WarningOutlined,
  DownOutlined, RightOutlined, PlayCircleOutlined, PauseCircleOutlined,
  PlusOutlined, EditOutlined,
} from '@ant-design/icons'
import * as api from '../../services/api'
import useStore from '../../stores/useStore'
import SessionHeader from '../shared/SessionHeader'
import PhaseProgress from '../shared/PhaseProgress'
import IterationTimeline from '../shared/IterationTimeline'
import IterationDetail from '../shared/IterationDetail'
import { formatTokenCount, analyzeFailure } from './helpers'

const { Text } = Typography

const PHASE_COLORS = {
  refine: '#8b949e', pm_analysis: '#bc8cff', plan: '#58a6ff',
  dev: '#3fb950', test: '#d29922', fix: '#f85149',
}
const PHASE_LABEL = {
  refine: '优化', pm_analysis: 'PM', plan: '规划',
  dev: '开发', test: '测试', fix: '修复',
}

/* ---- StoryCard：单个任务折叠卡片 ---- */

function StoryCard({ task, isDark, defaultOpen }) {
  const [open, setOpen] = useState(defaultOpen)
  const isFailed = task.status === 'failed'
  const hasDetail = task.description || (task.verification_steps && task.verification_steps.length > 0) || isFailed
  const statusIcon = task.passes || task.status === 'verified'
    ? <CheckCircleFilled style={{ color: '#3fb950' }} />
    : task.status === 'completed'
      ? <CheckCircleFilled style={{ color: '#d29922' }} />
      : task.status === 'in_progress'
        ? <SyncOutlined spin style={{ color: '#58a6ff' }} />
        : isFailed
          ? <CloseCircleFilled style={{ color: '#f85149' }} />
          : <ClockCircleOutlined style={{ color: '#8b949e' }} />
  const statusLabel = task.passes || task.status === 'verified' ? '已验证'
    : task.status === 'completed' ? '已完成'
    : task.status === 'in_progress' ? '进行中'
    : isFailed ? '失败' : '待处理'

  const labelStyle = { fontSize: 11, color: isDark ? '#8b949e' : '#656d76', flexShrink: 0, minWidth: 56 }
  const valStyle = { fontSize: 12, color: isDark ? '#c9d1d9' : '#1f2328', lineHeight: 1.6 }
  const borderColor = isFailed
    ? (isDark ? '#f8514933' : '#f8514933')
    : (isDark ? '#30363d' : '#d0d7de')

  return (
    <div style={{
      border: `1px solid ${borderColor}`, borderRadius: 8, marginBottom: 8,
      background: isFailed ? (isDark ? '#1a0f0f' : '#fff5f5') : (isDark ? '#0d1117' : '#fff'),
      overflow: 'hidden',
    }}>
      <div
        onClick={() => hasDetail && setOpen(!open)}
        style={{
          display: 'flex', alignItems: 'center', gap: 8, padding: '10px 14px',
          cursor: hasDetail ? 'pointer' : 'default',
          borderBottom: open ? `1px solid ${isDark ? '#21262d' : '#d8dee4'}` : 'none',
        }}
      >
        {statusIcon}
        <span style={{ flex: 1, fontSize: 13, fontWeight: 500, color: isDark ? '#e6edf3' : '#1f2328' }}>
          {task.title}
        </span>
        <span style={{ fontSize: 10, fontFamily: 'monospace', color: isDark ? '#484f58' : '#afb8c1' }}>{task.id}</span>
        {task.passes && <Tag color="success" style={{ margin: 0, fontSize: 10 }}>已验证</Tag>}
        {!task.passes && task.status !== 'verified' && (
          <Tag color={isFailed ? 'error' : undefined} style={{ margin: 0, fontSize: 10 }}>{statusLabel}</Tag>
        )}
        {hasDetail && (
          <CaretRightOutlined style={{
            fontSize: 10, color: isDark ? '#484f58' : '#afb8c1',
            transform: open ? 'rotate(90deg)' : 'none', transition: 'transform 0.2s',
          }} />
        )}
      </div>
      {open && hasDetail && (
        <div style={{ padding: '12px 14px', fontSize: 12 }}>
          {isFailed && task.error_info && (
            <Alert type="error" showIcon message="执行失败"
              description={<div>
                <div>{task.error_info.message}</div>
                {task.error_info.suggestion && <div style={{ marginTop: 6 }}><strong>修复建议：</strong>{task.error_info.suggestion}</div>}
              </div>}
              style={{ marginBottom: 10, fontSize: 12 }}
            />
          )}
          {isFailed && !task.error_info && (
            <Alert type="error" showIcon message="任务未能完成"
              description="开发阶段未能产出预期的文件，可能是需求描述不够清晰或模型能力不足。尝试简化需求或切换更强的模型后重跑。"
              style={{ marginBottom: 10, fontSize: 12 }}
            />
          )}
          {task.description && (
            <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
              <span style={labelStyle}>描述</span>
              <span style={valStyle}>{task.description}</span>
            </div>
          )}
          {task.verification_steps?.length > 0 && (
            <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
              <span style={labelStyle}>验收标准</span>
              <div style={valStyle}>
                {task.verification_steps.map((step, i) => (
                  <div key={i} style={{ display: 'flex', gap: 6, padding: '1px 0' }}>
                    <NumberOutlined style={{ fontSize: 10, color: isDark ? '#484f58' : '#afb8c1', marginTop: 3, flexShrink: 0 }} />
                    <span>{step}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {task.files?.length > 0 && (
            <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
              <span style={labelStyle}>关联文件</span>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                {task.files.map((f, i) => <Tag key={i} icon={<FileTextOutlined />} style={{ fontSize: 11, margin: 0 }}>{f}</Tag>)}
              </div>
            </div>
          )}
          {task.verification_notes && (
            <div style={{ display: 'flex', gap: 8 }}>
              <span style={labelStyle}>验证结果</span>
              <span style={{ ...valStyle, color: task.passes ? '#3fb950' : '#f85149' }}>{task.verification_notes}</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/* ---- InitStepItem：初始化步骤指示器 ---- */

function InitStepItem({ label, status, isDark }) {
  const isActive = status === 'active'
  const isDone = status === 'done'
  const icon = isDone
    ? <CheckCircleFilled style={{ color: '#3fb950', fontSize: 16 }} />
    : isActive
      ? <LoadingOutlined style={{ color: '#58a6ff', fontSize: 16 }} />
      : <ClockCircleOutlined style={{ color: isDark ? '#484f58' : '#afb8c1', fontSize: 16 }} />

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 0', opacity: status === 'pending' ? 0.5 : 1 }}>
      {icon}
      <span style={{
        fontSize: 13, fontWeight: isActive ? 600 : 400,
        color: isDark ? (isActive ? '#e6edf3' : '#8b949e') : (isActive ? '#1f2328' : '#656d76'),
      }}>
        {label}
      </span>
    </div>
  )
}

/* ---- OverviewTab 主体 ---- */

export default function OverviewTab({ project }) {
  const isRunning = useStore(s => s.isRunning)
  const theme = useStore(s => s.theme)
  const isDark = theme === 'dark'
  const iterationHistory = useStore(s => s.iterationHistory)
  const currentPhase = useStore(s => s.currentPhase)
  const executionTaskList = useStore(s => s.executionTaskList)
  const executionBugsList = useStore(s => s.executionBugsList)
  const executionSummary = useStore(s => s.executionSummary)
  const executionStats = useStore(s => s.executionStats)
  const selectedProjectName = useStore(s => s.selectedProjectName)
  const quickFixBugs = useStore(s => s.quickFixBugs)
  const resumeProjectAction = useStore(s => s.resumeProject)


  const executionRequirement = useStore(s => s.executionRequirement)
  const refinerResult = useStore(s => s.executionRefinerResult)
  const executionPlan = useStore(s => s.executionPlan)
  const sandboxStatus = useStore(s => s.sandboxStatus)
  const pmProgress = useStore(s => s.pmProgress)
  const agentThinking = useStore(s => s.agentThinking)
  const executionFailure = useStore(s => s.executionFailure)
  const selectedIteration = useStore(s => s.selectedIteration)
  const collapsedSections = useStore(s => s.collapsedSections)
  const toggleSectionCollapsed = useStore(s => s.toggleSectionCollapsed)
  const storeProject = useStore(s => s.getSelectedProject)()
  const startExecution = useStore(s => s.startExecution)
  const stopExecution = useStore(s => s.stopExecution)

  // 迭代步骤列表（State 2/3 共用）
  const stepsCollapsed = !!collapsedSections['steps']
  const iterationStepsCard = iterationHistory.length > 0 ? (
    <Card size="small"
      title={
        <span
          onClick={() => toggleSectionCollapsed('steps')}
          style={{ fontSize: 13, cursor: 'pointer', userSelect: 'none', display: 'inline-flex', alignItems: 'center', gap: 6 }}
        >
          {stepsCollapsed ? <RightOutlined style={{ fontSize: 10 }} /> : <DownOutlined style={{ fontSize: 10 }} />}
          执行步骤（{iterationHistory.length} 步）
          {isRunning && <Tag color="processing" style={{ margin: '0 0 0 8px', fontSize: 10 }}>
            <SyncOutlined spin style={{ marginRight: 3 }} />实时
          </Tag>}
        </span>
      }
      style={{ marginTop: 12 }}
    >
      {stepsCollapsed ? null : <>
      {iterationHistory.map((iter) => {
        const pc = PHASE_COLORS[iter.phase] || '#8b949e'
        let statusIcon
        const resultKnown = iter.success === true || iter.success === false
        if (!resultKnown && isRunning) statusIcon = <SyncOutlined spin style={{ color: '#58a6ff' }} />
        else if (iter.success === true) statusIcon = <CheckCircleFilled style={{ color: '#3fb950' }} />
        else if (iter.success === false) statusIcon = <CloseCircleFilled style={{ color: '#f85149' }} />

        let summary = iter.storyTitle || ''
        if (iter.phase === 'plan') summary = 'PM 规划任务'
        if (iter.phase === 'test') summary = `验证所有任务${iter.bugs?.length ? ` — ${iter.bugs.length} 个缺陷` : ''}`
        if (iter.phase === 'fix') summary = '修复缺陷'
        if (iter.phase === 'dev' && iter.storyTitle) summary = iter.storyTitle
        if (iter.success === false && iter.error) summary += ` — ${iter.error}`

        return (
          <div key={iter.iteration} style={{
            display: 'flex', alignItems: 'center', gap: 8, padding: '6px 12px', fontSize: 12,
            borderBottom: `1px solid ${isDark ? '#161b22' : '#f6f8fa'}`,
          }}>
            <span style={{ width: 50, flexShrink: 0, fontVariantNumeric: 'tabular-nums', color: isDark ? '#6e7681' : '#8c959f' }}>
              第{iter.iteration}步
            </span>
            <Tag color={pc} style={{ margin: 0, fontSize: 10, lineHeight: '16px', minWidth: 38, textAlign: 'center', border: 'none' }}>
              {PHASE_LABEL[iter.phase] || iter.phase}
            </Tag>
            <span style={{ width: 16, textAlign: 'center' }}>{statusIcon}</span>
            {iter.tokensUsed > 0 && (
              <span style={{ width: 50, textAlign: 'right', flexShrink: 0, fontVariantNumeric: 'tabular-nums', color: isDark ? '#8b949e' : '#656d76', fontSize: 11 }}>
                {formatTokenCount(iter.tokensUsed)}
              </span>
            )}
            <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: isDark ? '#c9d1d9' : '#1f2328' }}>
              {summary}
            </span>
            {iter.elapsedSeconds > 0 && (
              <span style={{ flexShrink: 0, fontSize: 10, color: isDark ? '#484f58' : '#bbb', fontVariantNumeric: 'tabular-nums' }}>
                {iter.elapsedSeconds.toFixed(1)}s
              </span>
            )}
          </div>
        )
      })}
      <div style={{ padding: '8px 0' }}>
        <IterationTimeline />
        <IterationDetail />
      </div>
      </>}
    </Card>
  ) : null

  // 需求分析结果卡片
  const refinerCard = refinerResult ? (() => {
    const { quality, enhanced, warning } = refinerResult
    const score = quality?.score ?? enhanced?.quality_before
    const afterScore = enhanced?.quality_after
    const level = quality?.level
    const issues = quality?.issues || []
    const levelColor = level === 'high' ? '#3fb950' : level === 'medium' ? '#d29922' : '#f85149'
    if (!score && !warning) return null
    return (
      <Card size="small" title="需求分析" style={{ marginTop: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
          <Progress type="circle" size={48} percent={Math.round((score || 0) * 100)} strokeColor={levelColor}
            format={p => <span style={{ fontSize: 12 }}>{p}</span>} />
          <div>
            <div style={{ fontSize: 13, fontWeight: 500 }}>
              质量评分: {((score || 0) * 100).toFixed(0)}
              {afterScore != null && afterScore !== score && (
                <span style={{ color: '#3fb950', marginLeft: 8 }}>→ {(afterScore * 100).toFixed(0)}</span>
              )}
            </div>
            {enhanced?.enhancements?.length > 0 && <Tag color="success" style={{ marginTop: 4, fontSize: 10 }}>已自动优化</Tag>}
          </div>
        </div>
        {warning && <Alert type="warning" showIcon message={warning.message} style={{ marginBottom: 8, fontSize: 12 }} />}
        {issues.length > 0 && (
          <div style={{ fontSize: 11, color: isDark ? '#8b949e' : '#656d76' }}>
            {issues.slice(0, 3).map((issue, i) => (
              <div key={i} style={{ padding: '2px 0' }}>
                <Tag color="warning" style={{ fontSize: 10, margin: 0 }}>{issue.category}</Tag>{' '}{issue.description}
              </div>
            ))}
            {issues.length > 3 && <div style={{ padding: '2px 0' }}>...还有 {issues.length - 3} 项</div>}
          </div>
        )}
      </Card>
    )
  })() : null

  // 技术栈决策卡片
  const ACTION_CFG = {
    adopted:  { label: '采纳', color: '#3fb950' },
    replaced: { label: '替换', color: '#d29922' },
    added:    { label: '补充', color: '#58a6ff' },
    removed:  { label: '移除', color: '#f85149' },
  }
  const techDecisions = executionPlan?.tech_decisions || []
  const techDecisionCard = techDecisions.length > 0 ? (
    <Card size="small" title="技术栈决策" style={{ marginTop: 12 }}>
      <div style={{ fontSize: 12 }}>
        {techDecisions.map((td, idx) => {
          const cfg = ACTION_CFG[td.action] || ACTION_CFG.added
          return (
            <div key={idx} style={{
              display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0',
              borderBottom: idx < techDecisions.length - 1 ? `1px solid ${isDark ? '#161b22' : '#f6f8fa'}` : 'none',
            }}>
              <Tag style={{ margin: 0, fontSize: 10, minWidth: 36, textAlign: 'center', border: 'none', color: '#fff', background: cfg.color }}>
                {cfg.label}
              </Tag>
              <span style={{ fontWeight: 500, color: isDark ? '#e6edf3' : '#1f2328', minWidth: 80 }}>
                {td.tech}
              </span>
              {td.action === 'replaced' && td.original && (
                <span style={{ fontSize: 11, color: '#f85149', textDecoration: 'line-through', marginRight: 4 }}>
                  {td.original}
                </span>
              )}
              <span style={{ flex: 1, color: isDark ? '#8b949e' : '#656d76', fontSize: 11 }}>
                {td.reason}
              </span>
            </div>
          )
        })}
      </div>
    </Card>
  ) : null

  const verifiedCount = executionTaskList.filter(t => t.passes || t.status === 'verified').length
  const completedCount = executionTaskList.filter(t => t.status === 'completed' || t.status === 'verified').length
  const failedTasks = executionTaskList.filter(t => t.status === 'failed')
  const totalTasks = executionTaskList.length
  const progressPercent = totalTasks > 0 ? Math.round((verifiedCount / totalTasks) * 100) : 0

  const runningActions = isRunning ? [
    <Button key="stop" size="small" danger icon={<PauseCircleOutlined />} onClick={stopExecution}>
      停止
    </Button>,
  ] : null

  // State 1：正在初始化（还没有任务列表）
  if (isRunning && executionTaskList.length === 0) {
    const hasSandboxEvent = sandboxStatus.step !== ''
    const sandboxReady = sandboxStatus.ready
    const hasPmPhase = !!currentPhase
    const sandboxStep = !hasSandboxEvent ? 'active' : sandboxReady ? 'done' : 'active'
    const pmStep = !sandboxReady ? 'pending' : hasPmPhase ? 'active' : 'pending'

    return (
      <div style={{ padding: 16, overflow: 'auto', height: '100%' }}>
        <SessionHeader actions={runningActions} />
        <Card size="small" style={{ marginTop: 16 }}>
          <div style={{ padding: '8px 0' }}>
            <Text strong style={{ fontSize: 14, display: 'block', marginBottom: 16 }}>正在初始化...</Text>
            <InitStepItem label="准备沙箱环境" status={sandboxStep} isDark={isDark} />
            {hasSandboxEvent && !sandboxReady && (
              <div style={{ marginLeft: 26, marginBottom: 8 }}>
                <Progress percent={sandboxStatus.progress} size="small" strokeColor="#58a6ff" style={{ maxWidth: 300 }} />
                <div style={{ fontSize: 11, color: isDark ? '#8b949e' : '#656d76', marginTop: 2 }}>{sandboxStatus.message}</div>
              </div>
            )}
            {sandboxReady && (
              <div style={{ marginLeft: 26, marginBottom: 4 }}>
                <span style={{ fontSize: 11, color: '#3fb950' }}>Docker 沙箱就绪</span>
              </div>
            )}
            <InitStepItem label="PM 智能体分析需求" status={pmStep} isDark={isDark} />
            {pmStep === 'active' && (
              <div style={{ marginLeft: 26, marginBottom: 8 }}>
                {pmProgress?.steps?.length > 0 ? (
                  <div>
                    {pmProgress.steps.map((s, i) => (
                      <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '2px 0', fontSize: 11 }}>
                        {s.completed
                          ? <CheckCircleFilled style={{ color: '#3fb950', fontSize: 12 }} />
                          : <SyncOutlined spin style={{ color: '#58a6ff', fontSize: 12 }} />}
                        <span style={{ color: s.completed ? (isDark ? '#8b949e' : '#656d76') : (isDark ? '#e6edf3' : '#1f2328') }}>
                          {s.message}
                        </span>
                      </div>
                    ))}
                    <Progress
                      percent={pmProgress.progress || 0} size="small"
                      strokeColor="#58a6ff" style={{ maxWidth: 300, marginTop: 6 }}
                      format={p => <span style={{ fontSize: 10 }}>{p}%</span>}
                    />
                  </div>
                ) : currentPhase ? (
                  <Tag color="processing" style={{ fontSize: 10 }}>
                    <SyncOutlined spin style={{ marginRight: 3 }} /> {currentPhase}
                  </Tag>
                ) : null}
              </div>
            )}
            <InitStepItem label="生成任务列表" status={pmProgress?.step === 'save' || pmProgress?.step === 'complete' ? 'active' : 'pending'} isDark={isDark} />
          </div>
        </Card>
        {pmStep === 'active' && agentThinking?.content && (
          <Card size="small" title={<span style={{ fontSize: 12 }}>💭 {agentThinking.agent || 'PM'} 正在思考</span>} style={{ marginTop: 12 }}>
            <div style={{
              fontSize: 11, lineHeight: 1.6, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
              color: isDark ? '#8b949e' : '#656d76', maxHeight: 120, overflow: 'auto',
            }}>
              {agentThinking.content}
            </div>
          </Card>
        )}
        {techDecisionCard}
        {refinerCard}
      </div>
    )
  }

  // State 2：运行中，已有任务列表
  if (isRunning && executionTaskList.length > 0) {
    return (
      <div style={{ padding: 16, overflow: 'auto', height: '100%' }}>
        <SessionHeader actions={runningActions} />
        <Card size="small" style={{ marginTop: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 12 }}>
            <Progress type="circle" size={56}
              percent={progressPercent}
              strokeColor={failedTasks.length > 0 ? '#f85149' : '#3fb950'}
              format={() => <span style={{ fontSize: 13, fontWeight: 600 }}>{verifiedCount}/{totalTasks}</span>}
            />
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>任务执行进度</div>
              <PhaseProgress />
            </div>
          </div>
          <Row gutter={[8, 8]}>
            <Col span={6}><Statistic title="任务" value={`${completedCount}/${totalTasks}`} valueStyle={{ fontSize: 16 }} /></Col>
            <Col span={6}><Statistic title="已验证" value={`${verifiedCount}/${totalTasks}`} valueStyle={{ fontSize: 16, color: '#3fb950' }} /></Col>
            <Col span={6}><Statistic title="缺陷" value={executionStats.bugs || 0} valueStyle={{ fontSize: 16, color: executionStats.bugs > 0 ? (executionSummary?.success ? '#d29922' : '#f85149') : undefined }} /></Col>
            <Col span={6}><Statistic title="消耗" value={formatTokenCount(executionStats.tokens || 0)} valueStyle={{ fontSize: 16 }} /></Col>
          </Row>
        </Card>
        <Card size="small"
          title={
            <span
              onClick={() => toggleSectionCollapsed('stories')}
              style={{ fontSize: 13, cursor: 'pointer', userSelect: 'none', display: 'inline-flex', alignItems: 'center', gap: 6 }}
            >
              {collapsedSections['stories'] ? <RightOutlined style={{ fontSize: 10 }} /> : <DownOutlined style={{ fontSize: 10 }} />}
              PM 任务（{verifiedCount}/{totalTasks}）
              {currentPhase && <Tag color="processing" style={{ margin: '0 0 0 8px', fontSize: 10 }}>
                <SyncOutlined spin style={{ marginRight: 3 }} /> {currentPhase}
              </Tag>}
            </span>
          }
          extra={!collapsedSections['stories'] &&
            <div style={{ display: 'flex', gap: 10, fontSize: 10, color: isDark ? '#8b949e' : '#656d76' }}>
              <span><CheckCircleFilled style={{ color: '#3fb950', marginRight: 2 }} />已验证</span>
              <span><CheckCircleFilled style={{ color: '#d29922', marginRight: 2 }} />已完成</span>
              <span><SyncOutlined style={{ color: '#58a6ff', marginRight: 2 }} />进行中</span>
              <span><ClockCircleOutlined style={{ color: '#8b949e', marginRight: 2 }} />待处理</span>
            </div>
          }
          style={{ marginTop: 12 }}
        >
          {!collapsedSections['stories'] && executionTaskList.map((task, idx) => (
            <StoryCard key={task.id || idx} task={task} isDark={isDark}
              defaultOpen={task.status === 'in_progress' || task.status === 'failed'} />
          ))}
        </Card>
        {iterationStepsCard}
        {executionBugsList.length > 0 && (
          <Card size="small" title={<span><BugOutlined /> 发现的缺陷（{executionBugsList.length}）</span>} style={{ marginTop: 12 }}>
            {executionBugsList.slice(0, 5).map((bug, idx) => (
              <div key={idx} style={{
                display: 'flex', alignItems: 'center', gap: 8, padding: '5px 0', fontSize: 12,
                borderBottom: idx < executionBugsList.length - 1 ? `1px solid ${isDark ? '#161b22' : '#f6f8fa'}` : 'none',
              }}>
                <BugOutlined style={{ color: '#f85149', flexShrink: 0 }} />
                <span style={{ flex: 1 }}>{bug.title || bug.description || `缺陷 ${idx + 1}`}</span>
                {bug.severity && <Tag color={bug.severity === 'critical' || bug.severity === 'high' ? 'error' : 'warning'} style={{ margin: 0, fontSize: 10 }}>{bug.severity}</Tag>}
              </div>
            ))}
          </Card>
        )}
        {techDecisionCard}
        {refinerCard}
      </div>
    )
  }

  // 共享变量和函数（供 State 3 和 State 4 使用）
  const effectiveStatus = project?.status || storeProject?.status || 'idle'

  const PROJECT_STATUS_DISPLAY = {
    idle:       { label: '未开始',  color: '#8b949e', desc: '项目已创建，在上方输入需求后点击执行' },
    planning:   { label: '规划中',  color: '#58a6ff', desc: 'PM 智能体正在规划任务' },
    developing: { label: '开发中',  color: '#58a6ff', desc: 'Developer 智能体正在编写代码' },
    testing:    { label: '测试中',  color: '#d29922', desc: 'Tester 智能体正在验证任务' },
    incomplete: { label: '未完成',  color: '#d29922', desc: '执行正常结束，但部分任务未通过验证' },
    completed:  { label: '已完成',  color: '#3fb950', desc: '所有任务已验证通过，可追加新功能继续迭代' },
    aborted:    { label: '异常终止', color: '#f85149', desc: '上次执行被中断（崩溃/手动终止），可继续执行恢复进度' },
  }
  const psCfg = PROJECT_STATUS_DISPLAY[effectiveStatus] || null

  const requirement = executionRequirement || project?.description || ''
  const projTotalTasks = project?.total_tasks || storeProject?.total_tasks || 0
  const projVerifiedTasks = project?.verified_tasks || storeProject?.verified_tasks || 0
  const hasTasks = projTotalTasks > 0 || executionTaskList.length > 0
  const hasUnverifiedTasks = hasTasks && projVerifiedTasks < projTotalTasks
  const hasBugs = (executionBugsList || []).length > 0 || hasUnverifiedTasks

  const handleQuickFix = async () => {
    try { await quickFixBugs(selectedProjectName) } catch { /* */ }
  }
  const handleResume = async () => {
    try { await resumeProjectAction(selectedProjectName) } catch { /* */ }
  }

  const handleAddFeature = async () => {
    if (!requirement) return
    try { await startExecution(requirement) } catch { /* */ }
  }

  const getActionButtons = () => {
    if (isRunning) return null
    const s = effectiveStatus
    const buttons = []

    if ((s === 'aborted' || s === 'incomplete') && hasTasks) {
      buttons.push(
        <Button key="resume" type="primary" size="small" icon={<PlayCircleOutlined />}
          onClick={handleResume}>
          继续执行
        </Button>
      )
    }
    if (s === 'completed') {
      buttons.push(
        <Button key="add-feature" type="primary" size="small" icon={<PlusOutlined />}
          disabled={!requirement} onClick={handleAddFeature}>
          追加功能
        </Button>
      )
    }
    if ((s === 'incomplete' || s === 'aborted') && hasBugs) {
      buttons.push(
        <Button key="fix" size="small" icon={<BugOutlined />} onClick={handleQuickFix}>
          快速修复
        </Button>
      )
    }
    if (!buttons.length) return null
    return buttons
  }

  // State 3：执行结束，有摘要
  if (!isRunning && executionSummary) {
    const success = executionSummary.success && (verifiedCount > 0 || totalTasks === 0)
    const failure = !success ? analyzeFailure(executionSummary, executionTaskList, executionBugsList, iterationHistory) : null
    // 始终用当前 taskList 做诊断，不信任 executionFailure.reason（常为结果复述的旧字符串）
    let displayReason = ''
    if (!success) {
      const tt = totalTasks
      const tasksCompleted = executionTaskList.filter(t => t.status === 'completed' || t.status === 'verified').length
      const fileCount = executionSummary?.files?.length || 0
      const bugsOpen = executionSummary?.bugs_open || (executionBugsList || []).length || 0
      const exitReason = executionSummary?.exit_reason || ''
      const devIters = executionSummary?.dev_iterations ?? (iterationHistory || []).filter(i => i.phase === 'dev').length
      const backendDiagnosis = executionSummary?.failure_reason || ''

      if (backendDiagnosis) {
        displayReason = backendDiagnosis
      } else if (devIters === 0 && fileCount === 0) {
        displayReason = 'Developer 阶段未执行，系统在规划阶段后异常退出'
      } else if (exitReason === 'circuit_breaker') {
        displayReason = '连续多次迭代失败触发熔断保护，执行被自动终止'
      } else if (exitReason === 'max_iterations') {
        displayReason = '达到最大迭代次数限制，仍有任务未完成'
      } else if (exitReason === 'no_progress') {
        displayReason = '多次迭代无实质进展，系统主动退出避免资源浪费'
      } else if (bugsOpen > 0 && tasksCompleted > 0) {
        displayReason = `${tasksCompleted} 个任务已完成但验证受阻，存在 ${bugsOpen} 个 Bug 待修复`
      } else if (tasksCompleted === 0 && tt > 0) {
        displayReason = fileCount > 0
          ? `生成了 ${fileCount} 个文件但代码编写未完成，可能是开发阶段中断`
          : 'Developer 阶段未执行，系统在规划阶段后异常退出'
      } else if (tasksCompleted > 0 && tasksCompleted < tt) {
        displayReason = `部分任务完成 (${tasksCompleted}/${tt})，剩余任务在开发或测试阶段失败`
      }
    }

    return (
      <div style={{ padding: 16, overflow: 'auto', height: '100%' }}>
        <SessionHeader actions={getActionButtons()} />
        <Card size="small"
          title={
            <span style={{ fontSize: 12, fontWeight: 400, color: isDark ? '#8b949e' : '#656d76' }}>
              本次执行结果
            </span>
          }
          style={{ marginTop: 16 }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
            {success
              ? <CheckCircleFilled style={{ fontSize: 24, color: '#3fb950' }} />
              : <MinusCircleOutlined style={{ fontSize: 24, color: '#d29922' }} />
            }
            <div style={{ flex: 1 }}>
              <span style={{ fontSize: 16, fontWeight: 600 }}>
                {success ? '全部任务验证通过' : `${verifiedCount}/${totalTasks} 个任务验证通过`}
              </span>
              <div style={{ fontSize: 12, color: isDark ? '#8b949e' : '#656d76', marginTop: 2 }}>
                {executionStats.elapsed > 0 && `耗时 ${executionStats.elapsed.toFixed(1)}s`}
                {executionStats.tokens > 0 && ` · ${formatTokenCount(executionStats.tokens)}`}
              </div>
            </div>
            <Progress type="circle" size={48} percent={progressPercent}
              strokeColor={success ? '#3fb950' : '#d29922'}
              format={() => <span style={{ fontSize: 12 }}>{progressPercent}%</span>}
            />
          </div>
          {!success && displayReason && (
            <Alert type="warning" showIcon message="执行诊断"
              description={<div>
                <div>{displayReason}</div>
                {(() => {
                  const failedTasks = executionTaskList.filter(t => !t.passes && t.status !== 'verified')
                  if (failedTasks.length === 0) return null
                  return (
                    <div style={{ marginTop: 8, borderTop: `1px solid ${isDark ? '#30363d' : '#d8dee4'}`, paddingTop: 8 }}>
                      {failedTasks.slice(0, 5).map((t, i) => (
                        <div key={i} style={{ display: 'flex', gap: 6, padding: '3px 0', fontSize: 11 }}>
                          <CloseCircleFilled style={{ color: '#f85149', flexShrink: 0, marginTop: 2, fontSize: 10 }} />
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <span style={{ fontWeight: 500 }}>{t.title}</span>
                            {t.error_info?.message && (
                              <span style={{ color: isDark ? '#8b949e' : '#656d76' }}>{' — '}{t.error_info.message.length > 80 ? t.error_info.message.slice(0, 80) + '…' : t.error_info.message}</span>
                            )}
                            {!t.error_info?.message && t.verification_notes && (
                              <span style={{ color: isDark ? '#8b949e' : '#656d76' }}>{' — '}{t.verification_notes.length > 80 ? t.verification_notes.slice(0, 80) + '…' : t.verification_notes}</span>
                            )}
                            {!t.error_info?.message && !t.verification_notes && (
                              <span style={{ color: isDark ? '#8b949e' : '#656d76' }}>{' — '}{
                                t.status === 'pending' ? '未开始执行' :
                                t.status === 'in_progress' ? '执行中断' :
                                t.status === 'failed' ? '执行失败' :
                                '等待验证'
                              }</span>
                            )}
                          </div>
                        </div>
                      ))}
                      {failedTasks.length > 5 && (
                        <div style={{ fontSize: 11, color: isDark ? '#8b949e' : '#656d76', marginTop: 4 }}>
                          还有 {failedTasks.length - 5} 个任务待处理，展开下方任务列表查看详情
                        </div>
                      )}
                    </div>
                  )
                })()}
              </div>}
              style={{ marginBottom: 12, fontSize: 12 }}
            />
          )}
          {!success && failure?.tips?.length > 0 && (
            <Alert type="info" showIcon message="建议下一步"
              description={
                <div>
                  {failure.tips.map((tip, idx) => (
                    <div key={idx} style={{ display: 'flex', alignItems: 'flex-start', gap: 6, padding: '3px 0', fontSize: 12 }}>
                      <span style={{ color: '#58a6ff', flexShrink: 0, marginTop: 1 }}>{tip.icon}</span>
                      <span>{tip.text}</span>
                    </div>
                  ))}
                </div>
              }
              style={{ marginBottom: 12, fontSize: 12 }}
            />
          )}
        </Card>
        {iterationStepsCard}
        {techDecisionCard}

        {executionTaskList.length > 0 && (
          <Card size="small"
            title={
              <span
                onClick={() => toggleSectionCollapsed('stories')}
                style={{ fontSize: 13, cursor: 'pointer', userSelect: 'none', display: 'inline-flex', alignItems: 'center', gap: 6 }}
              >
                {collapsedSections['stories'] ? <RightOutlined style={{ fontSize: 10 }} /> : <DownOutlined style={{ fontSize: 10 }} />}
                PM 任务（{verifiedCount}/{totalTasks}）
              </span>
            }
            extra={!collapsedSections['stories'] &&
              <div style={{ display: 'flex', gap: 10, fontSize: 10, color: isDark ? '#8b949e' : '#656d76' }}>
                <span><CheckCircleFilled style={{ color: '#3fb950', marginRight: 2 }} />已验证</span>
                <span><CheckCircleFilled style={{ color: '#d29922', marginRight: 2 }} />已完成</span>
                <span><CloseCircleFilled style={{ color: '#f85149', marginRight: 2 }} />失败</span>
                <span><ClockCircleOutlined style={{ color: '#8b949e', marginRight: 2 }} />待处理</span>
              </div>
            }
            style={{ marginTop: 12 }}
          >
            {!collapsedSections['stories'] && executionTaskList.map((task, idx) => (
              <StoryCard key={task.id || idx} task={task} isDark={isDark}
                defaultOpen={task.status === 'failed' || executionTaskList.length <= 3} />
            ))}
          </Card>
        )}

        {executionBugsList.length > 0 && (
          <Card id="bugs-section" size="small" title={<span><BugOutlined /> 缺陷列表（{executionBugsList.length}）</span>} style={{ marginTop: 12 }}>
            {executionBugsList.map((bug, idx) => (
              <div key={idx} style={{
                padding: '8px 0', fontSize: 12,
                borderBottom: idx < executionBugsList.length - 1 ? `1px solid ${isDark ? '#161b22' : '#f6f8fa'}` : 'none',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                  <BugOutlined style={{ color: '#f85149' }} />
                  <span style={{ flex: 1, fontWeight: 500 }}>{bug.title || bug.description || `缺陷 ${idx + 1}`}</span>
                  {bug.severity && <Tag color={bug.severity === 'critical' || bug.severity === 'high' ? 'error' : 'warning'} style={{ margin: 0, fontSize: 10 }}>{bug.severity}</Tag>}
                  <Button size="small" type="link"
                    onClick={() => quickFixBugs(selectedProjectName, { bugIds: [bug.id || idx], bugTitles: [bug.title] })}>
                    修复
                  </Button>
                </div>
                {bug.description && bug.description !== bug.title && (
                  <div style={{ marginLeft: 22, color: isDark ? '#8b949e' : '#656d76', fontSize: 11 }}>{bug.description}</div>
                )}
                {bug.root_cause && (
                  <div style={{ marginLeft: 22, marginTop: 4 }}>
                    <Tag style={{ fontSize: 10, margin: 0 }}>根因</Tag>
                    <span style={{ fontSize: 11, marginLeft: 4, color: isDark ? '#c9d1d9' : '#1f2328' }}>{bug.root_cause}</span>
                  </div>
                )}
                {bug.fix_strategy && (
                  <div style={{ marginLeft: 22, marginTop: 2 }}>
                    <Tag color="blue" style={{ fontSize: 10, margin: 0 }}>修复策略</Tag>
                    <span style={{ fontSize: 11, marginLeft: 4, color: isDark ? '#c9d1d9' : '#1f2328' }}>{bug.fix_strategy}</span>
                  </div>
                )}
              </div>
            ))}
            <div style={{ marginTop: 12, textAlign: 'center' }}>
              <Button type="primary" size="small" icon={<BugOutlined />} onClick={() => quickFixBugs(selectedProjectName)}>
                全部修复
              </Button>
            </div>
          </Card>
        )}

        {success && (
          <div style={{ marginTop: 12, textAlign: 'center' }}>
            <Tag color="success" style={{ fontSize: 12 }}>所有任务已完成并验证通过</Tag>
          </div>
        )}
      </div>
    )
  }

  // State 4：空闲，无活跃会话摘要
  return (
    <div style={{ padding: 16, overflow: 'auto', height: '100%' }}>
      <SessionHeader actions={getActionButtons()} />
      {project ? (
        <>
          {/* 项目状态卡片 */}
          <Card size="small" style={{ marginTop: 16 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <div style={{
                width: 10, height: 10, borderRadius: '50%', flexShrink: 0,
                background: psCfg?.color || '#8b949e',
              }} />
              <div style={{ flex: 1 }}>
                <span style={{ fontSize: 14, fontWeight: 600, color: isDark ? '#e6edf3' : '#1f2328' }}>
                  项目状态：{psCfg?.label || project.status}
                </span>
                {psCfg?.desc && (
                  <div style={{ fontSize: 12, color: isDark ? '#8b949e' : '#656d76', marginTop: 2 }}>
                    {psCfg.desc}
                  </div>
                )}
              </div>
              {project.total_tasks > 0 && (
                <div style={{ textAlign: 'right', flexShrink: 0 }}>
                  <div style={{ fontSize: 20, fontWeight: 600, color: project.verified_tasks >= project.total_tasks ? '#3fb950' : (isDark ? '#c9d1d9' : '#1f2328') }}>
                    {project.verified_tasks}/{project.total_tasks}
                  </div>
                  <div style={{ fontSize: 11, color: isDark ? '#6e7681' : '#8c959f' }}>任务验证</div>
                </div>
              )}
            </div>
            {effectiveStatus === 'idle' && (
              <Alert type="info" showIcon icon={<EditOutlined />}
                message="在上方输入框中填写需求描述，然后点击执行按钮开始自动开发"
                style={{ marginTop: 10, fontSize: 12 }}
              />
            )}
          </Card>

          {/* 历史执行摘要 */}
          {project.sessions_count > 0 && (
            <Card size="small"
              title={<span style={{ fontSize: 13 }}>执行历史（{project.sessions_count} 次）</span>}
              style={{ marginTop: 12 }}
            >
              <div style={{ fontSize: 12, color: isDark ? '#8b949e' : '#656d76' }}>
                切换到「需求历史」标签查看需求变化和每次执行的详细记录
              </div>
            </Card>
          )}
        </>
      ) : (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '60%' }}>
          <Empty description="输入需求开始开发" />
        </div>
      )}
    </div>
  )
}
