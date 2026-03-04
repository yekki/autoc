import { useState, useRef, useEffect } from 'react'
import { Input, Button, Switch, message, Tooltip, Modal, Progress } from 'antd'
import {
  PlayCircleOutlined,
  SyncOutlined,
  LoadingOutlined,
  ClearOutlined,
  ExclamationCircleOutlined,
  ThunderboltOutlined,
  EditOutlined,
  CheckOutlined,
  CloseOutlined,
} from '@ant-design/icons'
import * as api from '../../services/api'
import useStore from '../../stores/useStore'

const { TextArea } = Input

export default function RequirementInput() {
  const theme = useStore((s) => s.theme)
  const isRunning = useStore((s) => s.isRunning)
  const startExecution = useStore((s) => s.startExecution)
  const redefineProject = useStore((s) => s.redefineProject)
  const addFeature = useStore((s) => s.addFeature)
  const selectedProjectName = useStore((s) => s.selectedProjectName)
  const executionRequirement = useStore((s) => s.executionRequirement)
  const executionTaskList = useStore((s) => s.executionTaskList)
  const getSelectedProject = useStore((s) => s.getSelectedProject)
  const editProject = useStore((s) => s.editProject)
  const recordAiAssistTokens = useStore((s) => s.recordAiAssistTokens)
  const modelConfig = useStore((s) => s.modelConfig)
  const isDark = theme === 'dark'
  const auxCfg = modelConfig?.active?.helper || modelConfig?.active?.auxiliary
  const hasAuxiliary = !!(auxCfg?.provider && auxCfg?.model)

  const project = getSelectedProject()

  const [editing, setEditing] = useState(false)
  const [draftText, setDraftText] = useState('')
  const [cleanWorkspace, setCleanWorkspace] = useState(true)
  const [polishing, setPolishing] = useState(false)
  const [polishElapsed, setPolishElapsed] = useState(0)
  const prevProjectRef = useRef(null)
  const polishTimerRef = useRef(null)

  const hasExistingTasks = executionTaskList.length > 0
  const displayRequirement = executionRequirement || project?.description || ''

  useEffect(() => {
    if (selectedProjectName && selectedProjectName !== prevProjectRef.current) {
      prevProjectRef.current = selectedProjectName
      setEditing(false)
    }
  }, [selectedProjectName])

  useEffect(() => {
    return () => {
      clearInterval(polishTimerRef.current)
    }
  }, [])

  const startEditing = () => {
    if (isRunning) return
    setDraftText(displayRequirement)
    setEditing(true)
  }

  const saveEdit = async () => {
    const text = draftText.trim()
    if (!text) {
      message.warning('需求描述不能为空')
      return
    }
    try {
      await editProject(selectedProjectName, { description: text })
      useStore.setState({ executionRequirement: text })
      setEditing(false)
      message.success('需求已保存')
    } catch {
      message.error('保存失败')
    }
  }

  const cancelEdit = () => {
    setEditing(false)
  }

  const doRun = async (text) => {
    try {
      if (hasExistingTasks) {
        if (cleanWorkspace) {
          await redefineProject(selectedProjectName, text)
        } else {
          await addFeature(selectedProjectName, text)
        }
      } else {
        await startExecution(text)
      }
    } catch (e) {
      message.error(e.message || '启动失败')
    }
  }

  const handleRun = async () => {
    const text = displayRequirement
    if (!text) {
      message.warning('请先编辑并保存需求描述')
      return
    }
    if (!hasExistingTasks) {
      try {
        const result = await api.refineRequirement({
          requirement: text,
          mode: 'assess',
          project_name: selectedProjectName,
        })
        if (result?.quality?.level === 'low') {
          const issues = (result?.quality?.issues || []).map(i => i.description).filter(Boolean)
          Modal.confirm({
            title: '需求描述质量较低',
            icon: <ExclamationCircleOutlined />,
            content: (
              <div style={{ fontSize: 12 }}>
                <p>系统检测到需求描述可能不够清晰，可能导致生成质量不佳：</p>
                {issues.length > 0 && (
                  <ul style={{ paddingLeft: 18, margin: '8px 0' }}>
                    {issues.slice(0, 3).map((issue, i) => <li key={i}>{issue}</li>)}
                  </ul>
                )}
                <p style={{ marginTop: 8 }}>是否仍要继续执行？</p>
              </div>
            ),
            okText: '仍然执行',
            cancelText: '修改需求',
            onOk: () => doRun(text),
          })
          return
        }
      } catch { /* 评估失败不阻塞 */ }
    }
    await doRun(text)
  }

  const handlePolishDesc = async () => {
    if (!selectedProjectName) return
    const text = draftText.trim()
    if (!text) {
      message.warning('请先输入需求描述')
      return
    }
    setPolishing(true)
    setPolishElapsed(0)
    polishTimerRef.current = setInterval(() => setPolishElapsed(p => p + 1), 1000)
    try {
      const res = await api.aiAssist({
        action: 'polish',
        project_name: project?.name || selectedProjectName,
        description: text,
      })
      if (res.tokens_used) recordAiAssistTokens(res.tokens_used, 'polish')
      if (res.description) {
        setDraftText(res.description)
        message.success('需求已润色')
      }
    } catch (e) {
      message.error(e.message || 'AI 润色失败')
    } finally {
      setPolishing(false)
      clearInterval(polishTimerRef.current)
    }
  }

  const runIcon = isRunning ? <LoadingOutlined />
    : hasExistingTasks ? <SyncOutlined />
    : <PlayCircleOutlined />

  const AiProgressBar = ({ elapsed, label }) => (
    <div style={{ marginTop: 6 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: isDark ? '#8b949e' : '#656d76', marginBottom: 2 }}>
        <span>{label}</span>
        <span>{elapsed}s</span>
      </div>
      <Progress
        percent={Math.min(95, elapsed * 2.5)}
        size="small"
        strokeColor="#722ed1"
        showInfo={false}
        style={{ marginBottom: 0 }}
      />
    </div>
  )

  return (
    <div style={{ padding: 12 }}>
      {/* 标题栏 */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        marginBottom: 6,
      }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: isDark ? '#c9d1d9' : '#1f2328' }}>
          需求
        </span>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          {editing ? (
            <>
              {hasAuxiliary && (
                <Tooltip title="AI 润色需求描述">
                  <Button
                    type="text" size="small" icon={<ThunderboltOutlined />}
                    loading={polishing} onClick={handlePolishDesc}
                    style={{
                      fontSize: 11, height: 20, borderRadius: 10, padding: '0 6px',
                      color: isDark ? '#a78bfa' : '#7c3aed',
                      background: isDark ? 'rgba(167,139,250,0.08)' : 'rgba(124,58,237,0.06)',
                      border: `1px solid ${isDark ? 'rgba(167,139,250,0.2)' : 'rgba(124,58,237,0.18)'}`,
                    }}
                  >
                    润色
                  </Button>
                </Tooltip>
              )}
              <Tooltip title="保存">
                <Button
                  type="link" size="small" icon={<CheckOutlined />}
                  onClick={saveEdit}
                  style={{ padding: '0 2px', height: 18, fontSize: 12, color: '#3fb950' }}
                />
              </Tooltip>
              <Tooltip title="取消">
                <Button
                  type="link" size="small" icon={<CloseOutlined />}
                  onClick={cancelEdit}
                  style={{ padding: '0 2px', height: 18, fontSize: 12, color: '#f85149' }}
                />
              </Tooltip>
            </>
          ) : (
            <Tooltip title="编辑需求">
              <Button
                type="link" size="small" icon={<EditOutlined />}
                disabled={isRunning}
                onClick={startEditing}
                style={{ padding: '0 2px', height: 18, fontSize: 12, color: isDark ? '#8b949e' : '#656d76' }}
              />
            </Tooltip>
          )}
        </span>
      </div>

      {/* 需求内容：查看态 / 编辑态 */}
      {editing ? (
        <div>
          <TextArea
            value={draftText}
            onChange={(e) => setDraftText(e.target.value)}
            autoSize={{ minRows: 3, maxRows: 10 }}
            autoFocus
            placeholder="描述你想要构建的软件..."
            style={{
              fontSize: 13,
              background: isDark ? '#0d1117' : '#ffffff',
              borderColor: '#722ed1',
            }}
          />
          {polishing && <AiProgressBar elapsed={polishElapsed} label="AI 润色中..." />}
        </div>
      ) : (
        <div
          onClick={!isRunning ? startEditing : undefined}
          style={{
            cursor: isRunning ? 'default' : 'pointer',
            padding: '6px 8px',
            background: isDark ? '#0d1117' : '#f6f8fa',
            borderRadius: 6,
            border: `1px solid ${isDark ? '#21262d' : '#d8dee4'}`,
            minHeight: 48,
          }}
        >
          {/* 查看态：需求文本 */}
          <div style={{
            fontSize: 12, lineHeight: 1.7,
            color: displayRequirement ? (isDark ? '#c9d1d9' : '#1f2328') : (isDark ? '#484f58' : '#8c959f'),
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
          }}>
            {displayRequirement || '点击编辑需求...'}
          </div>

        </div>
      )}

      {hasExistingTasks && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 6,
          marginTop: 8, fontSize: 12, color: isDark ? '#8b949e' : '#656d76',
        }}>
          <ClearOutlined style={{ fontSize: 11 }} />
          <Tooltip title={cleanWorkspace
            ? '清空旧文件，完全从头开始（推荐需求变化较大时使用）'
            : '保留已有文件，在现有代码基础上修改（适合微调需求）'
          }>
            <span style={{ cursor: 'help' }}>清空工作区</span>
          </Tooltip>
          <Switch
            size="small"
            checked={cleanWorkspace}
            onChange={setCleanWorkspace}
            disabled={isRunning}
          />
          <span style={{ fontSize: 11, color: isDark ? '#6e7681' : '#8c959f' }}>
            {cleanWorkspace ? '从头开始' : '增量修改'}
          </span>
        </div>
      )}
      <div style={{ marginTop: 8 }}>
        <Tooltip title={hasExistingTasks
          ? (cleanWorkspace ? '清空工作区，用当前需求从头开始' : '保留已有文件，增量修改')
          : ''
        }>
          <Button
            type="primary"
            size="small"
            icon={runIcon}
            disabled={isRunning || !displayRequirement}
            onClick={handleRun}
            block
          >
            {hasExistingTasks ? '重新运行' : '运行'}
          </Button>
        </Tooltip>
      </div>
    </div>
  )
}
