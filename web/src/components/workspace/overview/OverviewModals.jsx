import { useState, useRef, useEffect } from 'react'
import { Modal, Input, Button, Tooltip, Progress, message } from 'antd'
import { ThunderboltOutlined, PlayCircleOutlined } from '@ant-design/icons'
import useStore from '../../../stores/useStore'
import * as api from '../../../services/api'

const { TextArea } = Input

function AiProgressBar({ elapsed, label, isDark }) {
  return (
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
}

export function RedefineProjectModal({ open, onClose, onConfirm, currentVersion, isDark, projectName, hasAuxiliary }) {
  const recordAiAssistTokens = useStore(s => s.recordAiAssistTokens)
  const [requirement, setRequirement] = useState('')
  const [polishing, setPolishing] = useState(false)
  const [polishElapsed, setPolishElapsed] = useState(0)
  const polishTimerRef = useRef(null)

  useEffect(() => { return () => { clearInterval(polishTimerRef.current) } }, [])

  const handleConfirm = () => {
    if (!requirement.trim()) return
    onConfirm(requirement.trim())
    setRequirement('')
    onClose()
  }

  const handlePolish = async () => {
    const text = requirement.trim()
    if (!text) return
    setPolishing(true)
    setPolishElapsed(0)
    polishTimerRef.current = setInterval(() => setPolishElapsed(p => p + 1), 1000)
    try {
      const res = await api.aiAssist({ action: 'polish', project_name: projectName, description: text })
      if (res.tokens_used) recordAiAssistTokens(res.tokens_used, 'polish')
      if (res.description) { setRequirement(res.description); message.success('需求已润色') }
    } catch (e) {
      message.error(e.message || 'AI 润色失败')
    } finally {
      setPolishing(false)
      clearInterval(polishTimerRef.current)
    }
  }

  const accentColor = isDark ? '#a78bfa' : '#7c3aed'
  const accentBg = isDark ? 'rgba(167,139,250,0.08)' : 'rgba(124,58,237,0.06)'
  const accentBorder = isDark ? 'rgba(167,139,250,0.2)' : 'rgba(124,58,237,0.18)'
  const aiBtnStyle = { fontSize: 11, height: 22, borderRadius: 11, padding: '0 8px', color: accentColor, background: accentBg, border: `1px solid ${accentBorder}` }

  return (
    <Modal
      title="新需求"
      open={open}
      onCancel={onClose}
      onOk={handleConfirm}
      okText="确认并开始"
      okButtonProps={{ disabled: !requirement.trim() || polishing, danger: true }}
      cancelText="取消"
      destroyOnHidden
      width={560}
    >
      <div style={{ marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
          <span style={{ fontSize: 13, fontWeight: 500 }}>需求描述</span>
          {hasAuxiliary && (
            <Tooltip title="AI 润色需求描述，使其更清晰完整">
              <Button type="text" size="small" icon={<ThunderboltOutlined />}
                loading={polishing} onClick={handlePolish}
                disabled={!requirement.trim()} style={aiBtnStyle}>
                AI 润色
              </Button>
            </Tooltip>
          )}
        </div>
        <TextArea
          rows={8} placeholder="描述你的新项目需求..."
          value={requirement} onChange={e => setRequirement(e.target.value)}
          autoSize={{ minRows: 8, maxRows: 16 }}
          style={{ fontSize: 14, background: isDark ? '#0d1117' : '#ffffff', borderColor: isDark ? '#30363d' : '#d0d7de' }}
        />
        {polishing && <AiProgressBar elapsed={polishElapsed} label="AI 润色中..." isDark={isDark} />}
      </div>
      <div style={{
        fontSize: 11, color: isDark ? '#6e7681' : '#8b949e', lineHeight: 1.6,
        padding: '8px 10px', borderRadius: 6,
        background: isDark ? 'rgba(255,200,0,0.04)' : 'rgba(255,200,0,0.06)',
        border: `1px solid ${isDark ? 'rgba(255,200,0,0.1)' : 'rgba(255,200,0,0.15)'}`,
      }}>
        当前迭代 v{currentVersion} 将被归档。代码会保存为 Git Tag，可在需求历史中恢复。
      </div>
    </Modal>
  )
}

export function AddFeatureModal({ open, onClose, onConfirm, isDark, projectName, hasAuxiliary }) {
  const recordAiAssistTokens = useStore(s => s.recordAiAssistTokens)
  const [requirement, setRequirement] = useState('')
  const [polishing, setPolishing] = useState(false)
  const [polishElapsed, setPolishElapsed] = useState(0)
  const polishTimerRef = useRef(null)

  useEffect(() => { return () => { clearInterval(polishTimerRef.current) } }, [])

  const handleConfirm = () => {
    if (!requirement.trim()) return
    onConfirm(requirement.trim())
    setRequirement('')
    onClose()
  }

  const handlePolish = async () => {
    const text = requirement.trim()
    if (!text) return
    setPolishing(true)
    setPolishElapsed(0)
    polishTimerRef.current = setInterval(() => setPolishElapsed(p => p + 1), 1000)
    try {
      const res = await api.aiAssist({ action: 'polish', project_name: projectName, description: text })
      if (res.tokens_used) recordAiAssistTokens(res.tokens_used, 'polish')
      if (res.description) { setRequirement(res.description); message.success('需求已润色') }
    } catch (e) {
      message.error(e.message || 'AI 润色失败')
    } finally {
      setPolishing(false)
      clearInterval(polishTimerRef.current)
    }
  }

  const accentColor = isDark ? '#a78bfa' : '#7c3aed'
  const accentBg = isDark ? 'rgba(167,139,250,0.08)' : 'rgba(124,58,237,0.06)'
  const accentBorder = isDark ? 'rgba(167,139,250,0.2)' : 'rgba(124,58,237,0.18)'
  const aiBtnStyle = { fontSize: 11, height: 22, borderRadius: 11, padding: '0 8px', color: accentColor, background: accentBg, border: `1px solid ${accentBorder}` }

  return (
    <Modal
      title="追加功能"
      open={open}
      onCancel={onClose}
      onOk={handleConfirm}
      okText="开始开发"
      okButtonProps={{ disabled: !requirement.trim() || polishing }}
      cancelText="取消"
      destroyOnHidden
      width={560}
    >
      <div style={{ marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
          <span style={{ fontSize: 13, fontWeight: 500 }}>功能描述</span>
          {hasAuxiliary && (
            <Tooltip title="AI 润色需求描述，使其更清晰完整">
              <Button type="text" size="small" icon={<ThunderboltOutlined />}
                loading={polishing} onClick={handlePolish}
                disabled={!requirement.trim()} style={aiBtnStyle}>
                AI 润色
              </Button>
            </Tooltip>
          )}
        </div>
        <TextArea
          rows={6} placeholder="描述要追加的功能..."
          value={requirement} onChange={e => setRequirement(e.target.value)}
          autoFocus
          autoSize={{ minRows: 6, maxRows: 14 }}
          style={{ fontSize: 14, background: isDark ? '#0d1117' : '#ffffff', borderColor: isDark ? '#30363d' : '#d0d7de' }}
        />
        {polishing && <AiProgressBar elapsed={polishElapsed} label="AI 润色中..." isDark={isDark} />}
      </div>
      <div style={{ fontSize: 11, color: isDark ? '#6e7681' : '#8b949e', lineHeight: 1.6 }}>
        在现有代码基础上增量开发新功能，已有代码不受影响。
      </div>
    </Modal>
  )
}

export function FixModal({ open, onClose, onConfirm, task }) {
  const [description, setDescription] = useState('')

  const handleConfirm = () => {
    onConfirm(task, description.trim())
    setDescription('')
    onClose()
  }

  return (
    <Modal
      title="修复问题"
      open={open}
      onCancel={onClose}
      onOk={handleConfirm}
      okText="开始修复"
      cancelText="取消"
      destroyOnHidden
    >
      {task && (
        <div style={{ padding: '8px 10px', borderRadius: 6, marginBottom: 12, fontSize: 12, background: '#fff5f5', border: '1px solid #f8514933' }}>
          <div style={{ fontWeight: 500 }}>{task.id} {task.title}</div>
          {task.error_info?.message && <div style={{ color: '#cf222e', marginTop: 4 }}>{task.error_info.message}</div>}
        </div>
      )}
      <TextArea
        rows={2} placeholder="补充修复说明（可选）..."
        value={description} onChange={e => setDescription(e.target.value)}
      />
    </Modal>
  )
}

export function IdleStartForm({ idleRequirement, setIdleRequirement, onRun, loading, projectName, isDark, hasAuxiliary }) {
  const recordAiAssistTokens = useStore(s => s.recordAiAssistTokens)
  const [polishing, setPolishing] = useState(false)
  const [polishElapsed, setPolishElapsed] = useState(0)
  const [originalText, setOriginalText] = useState('')
  const polishTimerRef = useRef(null)

  useEffect(() => { return () => { clearInterval(polishTimerRef.current) } }, [])

  const handlePolish = async () => {
    const text = idleRequirement.trim()
    if (!text) { message.warning('请先输入需求描述'); return }
    setPolishing(true)
    setPolishElapsed(0)
    setOriginalText(text)
    polishTimerRef.current = setInterval(() => setPolishElapsed(p => p + 1), 1000)
    try {
      const res = await api.aiAssist({ action: 'polish', project_name: projectName, description: text })
      if (res.tokens_used) recordAiAssistTokens(res.tokens_used, 'polish')
      if (res.description) {
        setIdleRequirement(res.description)
        const before = text.length, after = res.description.length
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

  const dimColor = isDark ? '#6e7681' : '#8c959f'

  return (
    <div style={{ padding: 16, overflow: 'auto', height: '100%' }}>
      <div style={{ maxWidth: 560, margin: '0 auto', paddingTop: '10%' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
          <div style={{ fontSize: 20, fontWeight: 600, color: isDark ? '#e6edf3' : '#1f2328' }}>
            开始开发
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            {originalText && !polishing && idleRequirement !== originalText && (
              <Button
                type="text" size="small"
                onClick={() => { setIdleRequirement(originalText); setOriginalText(''); message.info('已恢复原文') }}
                style={{ fontSize: 11, height: 24, borderRadius: 12, padding: '0 10px', color: dimColor }}
              >
                撤销润色
              </Button>
            )}
            {hasAuxiliary && (
              <Tooltip title="AI 润色需求描述，使其更清晰完整">
                <Button
                  type="text" size="small" icon={<ThunderboltOutlined />}
                  loading={polishing} onClick={handlePolish}
                  disabled={!idleRequirement.trim() || loading}
                  style={{
                    fontSize: 11, height: 24, borderRadius: 12, padding: '0 10px',
                    color: isDark ? '#a78bfa' : '#7c3aed',
                    background: isDark ? 'rgba(167,139,250,0.08)' : 'rgba(124,58,237,0.06)',
                    border: `1px solid ${isDark ? 'rgba(167,139,250,0.2)' : 'rgba(124,58,237,0.18)'}`,
                  }}
                >
                  {polishing ? `润色中 ${polishElapsed}s` : 'AI 润色'}
                </Button>
              </Tooltip>
            )}
          </div>
        </div>
        <Input.TextArea
          value={idleRequirement}
          onChange={e => setIdleRequirement(e.target.value)}
          placeholder="描述你想要构建的软件..."
          autoSize={{ minRows: 5, maxRows: 12 }}
          disabled={polishing || loading}
          style={{
            fontSize: 14,
            background: isDark ? '#0d1117' : '#ffffff',
            borderColor: isDark ? '#30363d' : '#d0d7de',
            marginBottom: polishing ? 0 : 12,
          }}
        />
        {polishing && <AiProgressBar elapsed={polishElapsed} label="AI 润色中..." isDark={isDark} />}
        <div style={{ marginTop: polishing ? 12 : 0 }}>
          <Button
            type="primary" size="large" icon={<PlayCircleOutlined />}
            disabled={!idleRequirement.trim() || polishing} onClick={onRun}
            loading={loading} block
          >
            开始开发
          </Button>
        </div>
      </div>
    </div>
  )
}
