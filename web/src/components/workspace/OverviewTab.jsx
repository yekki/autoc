import { useState, useEffect, useRef } from 'react'
import { Card, Tag, Button, Input, Tooltip, message, Alert } from 'antd'
import {
  CheckCircleFilled, CloseCircleFilled,
  DownOutlined, RightOutlined, PlayCircleOutlined,
  BugOutlined, ToolOutlined, SyncOutlined, RedoOutlined,
  EditOutlined, SaveOutlined, CloseOutlined,
  PlusOutlined, ThunderboltOutlined, SendOutlined,
  CheckOutlined, StopOutlined,
} from '@ant-design/icons'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import useStore from '../../stores/useStore'
import * as api from '../../services/api'
import { SessionRuntime, ExecutionResult } from './overview/SessionRuntimeCard'
import { VersionTimeline } from './overview/VersionTimeline'
import { RedefineProjectModal, AddFeatureModal, FixModal, IdleStartForm } from './overview/OverviewModals'

/** 将底层异常转为用户可读的错误提示 */
function toUserMsg(e, fallback = '操作失败') {
  if (!e?.message) return fallback
  if (/fetch|network|ERR_|HTTP\s*5/i.test(e.message)) return '网络连接失败，请检查后端服务是否正常'
  return e.message
}


/* ============================================================
   Area 1: 靶标 — 主需求
   ============================================================ */

function TargetSection({ requirement, techStack, version, isDark }) {
  const collapsed = useStore(s => s.isSectionCollapsed('overview-target', false))
  const toggleCollapsed = useStore(s => s.toggleSectionCollapsed)
  if (!requirement) return null
  return (
    <Card size="small" style={{ marginBottom: 12 }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            onClick={() => toggleCollapsed('overview-target')}
            style={{
              display: 'flex', alignItems: 'center', gap: 8,
              marginBottom: collapsed ? 0 : 8,
              cursor: 'pointer', userSelect: 'none',
            }}
          >
            <span style={{ width: 14, textAlign: 'center', flexShrink: 0 }}>
              {collapsed
                ? <RightOutlined style={{ fontSize: 9, color: isDark ? '#484f58' : '#afb8c1' }} />
                : <DownOutlined style={{ fontSize: 9, color: isDark ? '#484f58' : '#afb8c1' }} />}
            </span>
            {version && (
              <Tag color="blue" style={{ margin: 0, fontSize: 11, fontWeight: 600 }}>v{version}</Tag>
            )}
            <span style={{ fontSize: 11, color: isDark ? '#6e7681' : '#8c959f' }}>主需求</span>
            {collapsed && (
              <span style={{
                flex: 1, fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                color: isDark ? '#8b949e' : '#656d76',
              }}>
                {requirement.split('\n')[0].replace(/^#+\s*/, '').slice(0, 60)}
              </span>
            )}
          </div>
          {!collapsed && (
            <>
              <div className="requirement-markdown" style={{
                fontSize: 13, color: isDark ? '#c9d1d9' : '#1f2328', lineHeight: 1.7,
              }}>
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{requirement}</ReactMarkdown>
              </div>
              {techStack?.length > 0 && (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 10 }}>
                  {techStack.map((t, i) => (
                    <Tag key={i} style={{ margin: 0, fontSize: 11 }}>{t}</Tag>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </Card>
  )
}


/* ============================================================
   Area 1.5: PLAN.md 展示
   ============================================================ */

function PlanSection({ isDark }) {
  const planMd = useStore(s => s.executionPlanMd)
  const collapsed = useStore(s => s.isSectionCollapsed('overview-plan', false))
  const toggleCollapsed = useStore(s => s.toggleSectionCollapsed)
  const setSectionCollapsed = useStore(s => s.setSectionCollapsed)
  const isRunning = useStore(s => s.isRunning)
  const selectedProjectName = useStore(s => s.selectedProjectName)
  const resumeProject = useStore(s => s.resumeProject)
  const setExecutionPlanMd = useStore(s => s.setExecutionPlanMd)

  const [editMode, setEditMode] = useState(false)
  const [editContent, setEditContent] = useState('')
  const [saving, setSaving] = useState(false)

  if (!planMd) return null

  const handleEdit = (e) => {
    e.stopPropagation()
    setSectionCollapsed('overview-plan', false)
    setEditContent(planMd)
    setEditMode(true)
  }

  const handleCancel = (e) => {
    e.stopPropagation()
    if (editContent !== planMd) {
      if (!window.confirm('有未保存的修改，确认放弃？')) return
    }
    setEditMode(false)
  }

  const handleSave = async (e) => {
    e.stopPropagation()
    setSaving(true)
    try {
      await api.saveProjectFile(selectedProjectName, 'PLAN.md', editContent)
      setExecutionPlanMd(editContent)
      setEditMode(false)
      message.success('PLAN.md 已保存')
    } catch (err) {
      message.error(`保存失败: ${err.message}`)
    } finally {
      setSaving(false)
    }
  }

  const handleRerun = async (e) => {
    e.stopPropagation()
    try {
      await resumeProject(selectedProjectName)
    } catch (err) {
      message.error(err?.message || '重新执行失败')
    }
  }

  const showExpanded = !collapsed || editMode

  return (
    <Card size="small" style={{ marginBottom: 12 }}>
      <div
        onClick={editMode ? undefined : () => toggleCollapsed('overview-plan')}
        style={{
          display: 'flex', alignItems: 'center', gap: 8,
          cursor: editMode ? 'default' : 'pointer', userSelect: 'none',
          marginBottom: showExpanded ? 8 : 0,
        }}
      >
        {!editMode && (
          <span style={{ width: 14, textAlign: 'center', flexShrink: 0 }}>
            {collapsed
              ? <RightOutlined style={{ fontSize: 9, color: isDark ? '#484f58' : '#afb8c1' }} />
              : <DownOutlined style={{ fontSize: 9, color: isDark ? '#484f58' : '#afb8c1' }} />}
          </span>
        )}
        <span style={{ fontSize: 11, color: isDark ? '#6e7681' : '#8c959f', flexShrink: 0 }}>PLAN.md</span>
        {collapsed && !editMode && (
          <span style={{
            flex: 1, fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            color: isDark ? '#8b949e' : '#656d76',
          }}>
            {planMd.split('\n')[0].replace(/^#+\s*/, '').slice(0, 80)}
          </span>
        )}
        <span style={{ flex: 1 }} />
        {!isRunning && !editMode && (
          <>
            <Button
              size="small" icon={<EditOutlined />}
              onClick={handleEdit}
              style={{ fontSize: 11 }}
            >
              编辑
            </Button>
            <Button
              size="small" type="primary" icon={<PlayCircleOutlined />}
              onClick={handleRerun}
              style={{ fontSize: 11 }}
            >
              重新执行
            </Button>
          </>
        )}
        {editMode && (
          <>
            <Button size="small" icon={<CloseOutlined />} onClick={handleCancel}>取消</Button>
            <Button
              size="small" type="primary" icon={<SaveOutlined />}
              loading={saving} onClick={handleSave}
            >
              保存
            </Button>
          </>
        )}
      </div>
      {showExpanded && (
        editMode ? (
          <textarea
            value={editContent}
            onChange={e => setEditContent(e.target.value)}
            onKeyDown={e => {
              if ((e.ctrlKey || e.metaKey) && e.key === 's') {
                e.preventDefault()
                if (!saving) handleSave(e)
              }
            }}
            style={{
              width: '100%', minHeight: 400, fontSize: 12, fontFamily: 'monospace',
              background: isDark ? '#0d1117' : '#f6f8fa',
              color: isDark ? '#c9d1d9' : '#1f2328',
              border: `1px solid ${isDark ? '#388bfd66' : '#0969da66'}`,
              borderRadius: 6, padding: '8px 10px', resize: 'vertical',
              outline: 'none', lineHeight: 1.6, boxSizing: 'border-box',
            }}
          />
        ) : (
          <div className="requirement-markdown" style={{
            fontSize: 13, color: isDark ? '#c9d1d9' : '#1f2328', lineHeight: 1.7,
            maxHeight: 400, overflow: 'auto',
          }}>
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{planMd}</ReactMarkdown>
          </div>
        )
      )}
    </Card>
  )
}


/* ============================================================
   Bug 区块（执行结果下方，有 bug 时显示）
   ============================================================ */

function BugSection({ isDark }) {
  const bugs = useStore(s => s.executionBugsList)
  const isRunning = useStore(s => s.isRunning)
  const selectedProjectName = useStore(s => s.selectedProjectName)
  const quickFixBugs = useStore(s => s.quickFixBugs)
  const fixProgress = useStore(s => s.fixProgress)

  if (!bugs || bugs.length === 0) return null

  const isFixing = fixProgress?.status === 'fixing'
  const dimColor = isDark ? '#6e7681' : '#8c959f'

  const handleFixSingle = async (bug) => {
    try { await quickFixBugs(selectedProjectName, { bugTitles: [bug.title] }) } catch (e) { message.error(toUserMsg(e, '修复失败')) }
  }
  const handleFixAll = async () => {
    try { await quickFixBugs(selectedProjectName, { bugTitles: bugs.map(b => b.title) }) } catch (e) { message.error(toUserMsg(e, '修复失败')) }
  }

  return (
    <Card size="small" style={{ marginBottom: 12 }}
      title={<span style={{ fontSize: 13 }}><BugOutlined style={{ marginRight: 6 }} />缺陷 ({bugs.length})</span>}
      extra={
        bugs.length > 1 && !isRunning && !isFixing && (
          <Button size="small" type="primary" icon={<ToolOutlined />} onClick={handleFixAll}>全部修复</Button>
        )
      }
    >
      {bugs.map((bug, idx) => {
        const sevColor = { critical: '#f85149', high: '#d29922', medium: '#e3b341', low: '#58a6ff' }[bug.severity] || '#8b949e'
        return (
          <div key={bug.id || idx} style={{
            display: 'flex', alignItems: 'flex-start', gap: 8, padding: '6px 0',
            borderBottom: idx < bugs.length - 1 ? `1px solid ${isDark ? '#21262d' : '#f0f0f0'}` : 'none',
          }}>
            <span style={{ fontSize: 11, fontFamily: 'monospace', color: dimColor, flexShrink: 0, minWidth: 20, marginTop: 1 }}>
              #{idx + 1}
            </span>
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: sevColor, flexShrink: 0, marginTop: 6 }} title={bug.severity} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 12, fontWeight: 500, color: isDark ? '#c9d1d9' : '#1f2328' }}>{bug.title}</div>
              {bug.description && (
                <div style={{
                  fontSize: 11, color: dimColor, marginTop: 2,
                  overflow: 'hidden', textOverflow: 'ellipsis',
                  display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
                }}>
                  {bug.description}
                </div>
              )}
            </div>
            {!isRunning && !isFixing && (
              <Button size="small" icon={<ToolOutlined />} onClick={() => handleFixSingle(bug)} style={{ flexShrink: 0 }}>修复</Button>
            )}
            {isFixing && <SyncOutlined spin style={{ color: '#58a6ff', fontSize: 12, marginTop: 4 }} />}
          </div>
        )
      })}
    </Card>
  )
}


/* ============================================================
   S-002: Planning 确认门横幅
   ============================================================ */

function PlanApprovalBanner({ isDark, sessionId }) {
  const [rejecting, setRejecting] = useState(false)
  const [feedback, setFeedback] = useState('')
  const [loading, setLoading] = useState(false)

  const handleApprove = async () => {
    if (!sessionId) return
    setLoading(true)
    try {
      await api.approvePlan(sessionId, { approved: true })
      useStore.setState({ planApprovalPending: false })
    } catch (e) {
      message.error(e.message || '审批失败')
    } finally {
      setLoading(false)
    }
  }

  const handleReject = async () => {
    if (!sessionId) return
    setLoading(true)
    try {
      await api.approvePlan(sessionId, { approved: false, feedback: feedback.trim() || '用户拒绝计划' })
      useStore.setState({ planApprovalPending: false })
    } catch (e) {
      message.error(e.message || '操作失败')
    } finally {
      setLoading(false)
    }
  }

  const accentBg = isDark ? 'rgba(88,166,255,0.06)' : 'rgba(9,105,218,0.04)'
  const accentBorder = isDark ? '#388bfd44' : '#0969da33'

  return (
    <Card
      size="small"
      style={{ marginBottom: 12, background: accentBg, border: `1px solid ${accentBorder}` }}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 600, fontSize: 13, color: isDark ? '#58a6ff' : '#0969da', marginBottom: 4 }}>
            计划已生成，请确认后继续开发
          </div>
          <div style={{ fontSize: 12, color: isDark ? '#8b949e' : '#656d76', lineHeight: 1.6 }}>
            上方 PLAN.md 为本次开发计划。确认后 AI 将立即开始编码；拒绝则可修改需求后重新启动。
          </div>
          {rejecting && (
            <Input.TextArea
              value={feedback}
              onChange={e => setFeedback(e.target.value)}
              placeholder="说明拒绝原因（可选）..."
              autoSize={{ minRows: 2, maxRows: 4 }}
              autoFocus
              style={{ marginTop: 8, fontSize: 12, background: isDark ? '#0d1117' : '#fff' }}
            />
          )}
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, flexShrink: 0 }}>
          {!rejecting ? (
            <>
              <Button
                type="primary" size="small" icon={<CheckOutlined />}
                loading={loading} onClick={handleApprove}
              >
                确认开始开发
              </Button>
              <Button
                size="small" icon={<StopOutlined />} danger
                disabled={loading} onClick={() => setRejecting(true)}
              >
                拒绝
              </Button>
            </>
          ) : (
            <>
              <Button
                type="primary" size="small" danger icon={<StopOutlined />}
                loading={loading} onClick={handleReject}
              >
                确认拒绝
              </Button>
              <Button size="small" disabled={loading} onClick={() => setRejecting(false)}>
                取消
              </Button>
            </>
          )}
        </div>
      </div>
    </Card>
  )
}


/* ============================================================
   S-003: 完成态内联追加功能输入条
   ============================================================ */

function InlineAddFeature({ isDark, projectName, hasAuxiliary, onSubmit }) {
  const [text, setText] = useState('')
  const [expanded, setExpanded] = useState(false)
  const [polishing, setPolishing] = useState(false)
  const [polishElapsed, setPolishElapsed] = useState(0)
  const [originalText, setOriginalText] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const polishTimerRef = useRef(null)
  const recordAiAssistTokens = useStore(s => s.recordAiAssistTokens)

  const handlePolish = async () => {
    const t = text.trim()
    if (!t) return
    setPolishing(true)
    setPolishElapsed(0)
    setOriginalText(t)
    polishTimerRef.current = setInterval(() => setPolishElapsed(p => p + 1), 1000)
    try {
      const res = await api.aiAssist({ action: 'polish', project_name: projectName, description: t })
      if (res.tokens_used) recordAiAssistTokens(res.tokens_used, 'polish')
      if (res.description) {
        setText(res.description)
        const before = t.length, after = res.description.length
        message.success(`润色完成：${before} → ${after} 字`)
      }
    } catch (e) {
      message.error(e.message || 'AI 润色失败')
      setOriginalText('')
    } finally {
      setPolishing(false)
      clearInterval(polishTimerRef.current)
    }
  }

  const handleSubmit = async () => {
    const t = text.trim()
    if (!t) return
    setSubmitting(true)
    try {
      await onSubmit(t)
      setText('')
      setExpanded(false)
    } catch (e) {
      message.error(e.message || '操作失败')
    } finally {
      setSubmitting(false)
    }
  }

  const borderColor = isDark ? '#30363d' : '#d0d7de'
  const bg = isDark ? '#0d1117' : '#ffffff'
  const placeholder = '追加功能需求...'

  return (
    <div style={{
      border: `1px solid ${expanded ? (isDark ? '#388bfd66' : '#0969da66') : borderColor}`,
      borderRadius: 8, background: bg, transition: 'border-color 0.2s',
      marginBottom: 12,
    }}>
      {!expanded ? (
        <div
          onClick={() => setExpanded(true)}
          style={{
            padding: '10px 14px', cursor: 'text',
            fontSize: 13, color: isDark ? '#484f58' : '#afb8c1',
            display: 'flex', alignItems: 'center', gap: 8,
          }}
        >
          <PlusOutlined style={{ fontSize: 12 }} />
          {placeholder}
        </div>
      ) : (
        <div style={{ padding: '10px 12px' }}>
          <Input.TextArea
            value={text}
            onChange={e => setText(e.target.value)}
            placeholder={placeholder}
            autoSize={{ minRows: 3, maxRows: 10 }}
            autoFocus
            disabled={polishing || submitting}
            onKeyDown={e => {
              if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                e.preventDefault()
                if (text.trim() && !polishing && !submitting) handleSubmit()
              }
              if (e.key === 'Escape') { setText(''); setExpanded(false) }
            }}
            style={{
              fontSize: 13, background: 'transparent', border: 'none',
              padding: 0, resize: 'none', outline: 'none', boxShadow: 'none',
              color: isDark ? '#c9d1d9' : '#1f2328',
            }}
          />
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 8 }}>
            <div style={{ display: 'flex', gap: 6 }}>
              {originalText && !polishing && text !== originalText && (
                <Button
                  size="small" type="text"
                  onClick={() => { setText(originalText); setOriginalText(''); message.info('已恢复原文') }}
                  style={{ fontSize: 11, height: 22, color: isDark ? '#6e7681' : '#8c959f' }}
                >
                  撤销润色
                </Button>
              )}
              {hasAuxiliary && (
                <Tooltip title="AI 润色描述">
                  <Button
                    size="small" type="text" icon={<ThunderboltOutlined />}
                    loading={polishing} onClick={handlePolish}
                    disabled={!text.trim() || submitting}
                    style={{
                      fontSize: 11, height: 22, borderRadius: 11, padding: '0 8px',
                      color: isDark ? '#a78bfa' : '#7c3aed',
                      background: isDark ? 'rgba(167,139,250,0.08)' : 'rgba(124,58,237,0.06)',
                      border: `1px solid ${isDark ? 'rgba(167,139,250,0.2)' : 'rgba(124,58,237,0.18)'}`,
                    }}
                  >
                    {polishing ? `润色中 ${polishElapsed}s` : '润色'}
                  </Button>
                </Tooltip>
              )}
              <Button
                size="small" type="text" onClick={() => { setText(''); setExpanded(false) }}
                style={{ fontSize: 11, height: 22, color: isDark ? '#6e7681' : '#8c959f' }}
              >
                取消
              </Button>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ fontSize: 10, color: isDark ? '#484f58' : '#afb8c1' }}>⌘↵ 提交</span>
              <Button
                size="small" type="primary" icon={<SendOutlined />}
                loading={submitting} onClick={handleSubmit}
                disabled={!text.trim() || polishing}
              >
                开始开发
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}


/* ============================================================
   OverviewTab 主体
   ============================================================ */

export default function OverviewTab({ project }) {
  const isRunning = useStore(s => s.isRunning)
  const theme = useStore(s => s.theme)
  const isDark = theme === 'dark'
  const executionSummary = useStore(s => s.executionSummary)
  const executionRequirement = useStore(s => s.executionRequirement)
  const executionTaskList = useStore(s => s.executionTaskList)
  const executionFailure = useStore(s => s.executionFailure)
  const selectedProjectName = useStore(s => s.selectedProjectName)
  const planApprovalPending = useStore(s => s.planApprovalPending)
  const sessionId = useStore(s => s.sessionId)
  const resumeProjectAction = useStore(s => s.resumeProject)
  const redefineProjectAction = useStore(s => s.redefineProject)
  const addFeatureAction = useStore(s => s.addFeature)
  const startExecution = useStore(s => s.startExecution)
  const stopExecution = useStore(s => s.stopExecution)
  const quickFixBugs = useStore(s => s.quickFixBugs)
  const storeProject = useStore(s => s.getSelectedProject)()
  const modelConfig = useStore(s => s.modelConfig)
  const editProject = useStore(s => s.editProject)
  const auxCfg = modelConfig?.active?.helper || modelConfig?.active?.auxiliary
  const hasAuxiliary = !!(auxCfg?.provider && auxCfg?.model)

  const [redefineOpen, setRedefineOpen] = useState(false)
  const [fixOpen, setFixOpen] = useState(false)
  const [fixTask, setFixTask] = useState(null)
  const [idleRequirement, setIdleRequirement] = useState('')
  const [idleRunning, setIdleRunning] = useState(false)

  const executionExpectedVersion = useStore(s => s.executionExpectedVersion)
  const requirement = executionRequirement || project?.description || ''
  const techStack = storeProject?.tech_stack || project?.tech_stack || []
  const version = executionExpectedVersion || project?.version || storeProject?.version || '1.0.0'
  const effectiveStatus = project?.status || storeProject?.status || 'idle'
  const hasTasks = executionTaskList.length > 0 || (project?.total_tasks || 0) > 0

  const handleRedefine = async (newReq) => {
    try { await redefineProjectAction(selectedProjectName, newReq) } catch (e) { message.error(toUserMsg(e, '操作失败')) }
  }
  const handleAddFeature = async (newReq) => {
    try { await addFeatureAction(selectedProjectName, newReq) } catch (e) { message.error(toUserMsg(e, '操作失败')) }
  }
  const handleFix = async (task) => {
    try { await quickFixBugs(selectedProjectName, { bugTitles: task?.title ? [task.title] : undefined }) } catch (e) { message.error(toUserMsg(e, '修复失败')) }
  }
  const handleResume = async () => {
    try { await resumeProjectAction(selectedProjectName) } catch (e) { message.error(toUserMsg(e, '重试失败')) }
  }
  const handleIdleRun = async () => {
    const text = idleRequirement.trim()
    if (!text) return
    if (!selectedProjectName) { message.error('请先选择项目'); return }
    setIdleRunning(true)
    try {
      // 先启动执行（关键操作），成功后异步持久化描述，避免 PATCH 失败阻断执行
      await startExecution(text)
      editProject(selectedProjectName, { description: text }).catch(() => {})
    } catch (e) {
      message.error(toUserMsg(e, '启动失败，请重试'))
    } finally {
      setIdleRunning(false)
    }
  }

  const topActions = []
  if (!isRunning && requirement && effectiveStatus !== 'idle') {
    topActions.push(
      <Button key="redefine" size="small" icon={<RedoOutlined />} onClick={() => setRedefineOpen(true)}
        title="归档当前迭代，开始新的需求">
        新需求
      </Button>
    )
  }

  if (!isRunning && !executionSummary && (!project || effectiveStatus === 'idle')) {
    return (
      <IdleStartForm
        idleRequirement={idleRequirement}
        setIdleRequirement={setIdleRequirement}
        onRun={handleIdleRun}
        loading={idleRunning}
        projectName={selectedProjectName}
        isDark={isDark}
        hasAuxiliary={hasAuxiliary}
      />
    )
  }

  return (
    <div style={{ padding: 16, overflow: 'auto', height: '100%' }}>
      {topActions.length > 0 && (
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginBottom: 12 }}>
          {topActions}
        </div>
      )}

      {(isRunning || !executionSummary) && (
        <TargetSection requirement={requirement} techStack={techStack} version={version} isDark={isDark} />
      )}

      <PlanSection isDark={isDark} />

      {/* S-002: Planning 确认门，仅在等待审批时显示 */}
      {planApprovalPending && isRunning && (
        <PlanApprovalBanner
          isDark={isDark}
          sessionId={sessionId}
        />
      )}

      {isRunning && <SessionRuntime isDark={isDark} onStop={stopExecution} />}

      {!isRunning && executionSummary && (
        <ExecutionResult isDark={isDark} onRetry={handleResume} />
      )}

      {!isRunning && <BugSection isDark={isDark} />}

      {!isRunning && !executionSummary && executionFailure && (
        <Card size="small" style={{ marginBottom: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
            <CloseCircleFilled style={{ fontSize: 16, color: '#f85149' }} />
            <span style={{ fontSize: 14, fontWeight: 600, color: isDark ? '#e6edf3' : '#1f2328' }}>
              {executionFailure.reason || '执行中断'}
            </span>
          </div>
          {executionFailure.suggestions?.length > 0 && (
            <div style={{ fontSize: 12, color: isDark ? '#8b949e' : '#656d76', lineHeight: 1.8 }}>
              {executionFailure.suggestions.map((s, i) => <div key={i}>• {s}</div>)}
            </div>
          )}
          {hasTasks && (
            <Button size="small" type="primary" icon={<PlayCircleOutlined />} onClick={handleResume} style={{ marginTop: 8 }}>
              重试
            </Button>
          )}
        </Card>
      )}

      <VersionTimeline
        isDark={isDark}
        projectName={selectedProjectName}
        onAddFeature={null}
      />

      {/* S-003: 完成后内联追加功能，仅在非运行中且有历史版本时显示 */}
      {!isRunning && requirement && effectiveStatus !== 'idle' && (
        <InlineAddFeature
          isDark={isDark}
          projectName={selectedProjectName}
          hasAuxiliary={hasAuxiliary}
          onSubmit={handleAddFeature}
        />
      )}

      <RedefineProjectModal
        open={redefineOpen} onClose={() => setRedefineOpen(false)}
        onConfirm={handleRedefine} currentVersion={version}
        isDark={isDark} projectName={selectedProjectName} hasAuxiliary={hasAuxiliary}
      />
      <FixModal
        open={fixOpen}
        onClose={() => { setFixOpen(false); setFixTask(null) }}
        onConfirm={handleFix}
        task={fixTask}
      />
    </div>
  )
}
