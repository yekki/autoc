import { useState, useCallback, useEffect } from 'react'
import { Button, Typography, Tag, Space, Alert, Spin, Tooltip, Drawer, Input, message } from 'antd'
import {
  GlobalOutlined, CodeOutlined, ReloadOutlined, ExpandOutlined,
  LinkOutlined, CloudServerOutlined, DesktopOutlined, StopOutlined,
  PlayCircleOutlined, PoweroffOutlined, ApiOutlined, RocketOutlined,
  SyncOutlined, SettingOutlined, PlusOutlined, DeleteOutlined,
  EyeOutlined, EyeInvisibleOutlined, CheckCircleFilled,
} from '@ant-design/icons'
import * as api from '../../services/api'
import useStore from '../../stores/useStore'

const { Text, Paragraph } = Typography

const RUNTIME_LABELS = {
  local: { icon: <DesktopOutlined />, label: '本地', color: 'blue' },
  docker: { icon: <CodeOutlined />, label: 'Docker', color: 'purple' },
  cloud: { icon: <CloudServerOutlined />, label: '云端', color: 'green' },
  e2b: { icon: <CloudServerOutlined />, label: 'E2B', color: 'cyan' },
}

const TYPE_LABELS = {
  web_frontend: '前端应用',
  web_fullstack: '全栈应用',
  web_backend: '后端 API',
  cli_tool: 'CLI 工具',
  library: '代码库',
  unknown: '未知',
}

const TerminalIcon = () => (
  <span style={{ fontFamily: 'Menlo, Monaco, Consolas, monospace', fontWeight: 700, fontSize: '0.85em' }}>&gt;_</span>
)

const TYPE_META = {
  web_frontend: { icon: <GlobalOutlined />, color: '#1677ff', tagColor: 'blue', desc: '前端 Web 应用，可启动开发服务器在浏览器中预览' },
  web_fullstack: { icon: <RocketOutlined />, color: '#722ed1', tagColor: 'purple', desc: '全栈 Web 应用，包含前后端服务' },
  web_backend: { icon: <ApiOutlined />, color: '#13c2c2', tagColor: 'cyan', desc: '后端 API 服务，可启动服务器查看接口' },
  cli_tool: { icon: <TerminalIcon />, color: '#fa8c16', tagColor: 'orange', desc: '命令行工具，可运行查看使用说明' },
}

const FASTAPI_PATHS = [
  { key: 'docs', label: 'Swagger UI', path: '/docs' },
  { key: 'redoc', label: 'ReDoc', path: '/redoc' },
  { key: 'root', label: 'API 根路径', path: '' },
]

const GENERIC_API_PATHS = [
  { key: 'health', label: '健康检查', path: '/health' },
  { key: 'api', label: '/api', path: '/api' },
  { key: 'root', label: '根路径', path: '' },
]

function getApiPaths(framework) {
  if (framework === 'fastapi') return FASTAPI_PATHS
  return GENERIC_API_PATHS
}

function EmptyDetectedState({ detected, isDark, starting, onStart }) {
  const { project_type, command } = detected
  const meta = TYPE_META[project_type]
  if (!meta) return null

  const isCli = project_type === 'cli_tool'
  const isWeb = project_type.startsWith('web_')

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center',
      justifyContent: 'center', padding: '40px 24px', gap: 0,
      height: '100%', minHeight: 300,
    }}>
      <div style={{
        fontSize: 44, lineHeight: 1, color: meta.color,
        marginBottom: 16, opacity: 0.85,
      }}>
        {meta.icon}
      </div>
      <Tag color={meta.tagColor} style={{ fontSize: 14, padding: '2px 12px', marginBottom: 8 }}>
        {TYPE_LABELS[project_type]}
      </Tag>
      <div style={{
        color: isDark ? '#8b949e' : '#656d76', fontSize: 13,
        textAlign: 'center', maxWidth: 400, marginBottom: 16,
      }}>
        {meta.desc}
      </div>
      {command && (
        <div style={{
          background: isDark ? '#161b22' : '#f6f8fa',
          borderRadius: 6, padding: '6px 14px', marginBottom: 20,
          border: `1px solid ${isDark ? '#30363d' : '#d0d7de'}`,
          fontFamily: 'Menlo, Monaco, Consolas, monospace',
          fontSize: 12, color: isDark ? '#79c0ff' : '#0550ae',
        }}>
          $ {command}
        </div>
      )}
      <Button
        type="primary"
        size="large"
        icon={isCli ? <PlayCircleOutlined /> : <GlobalOutlined />}
        loading={starting}
        onClick={onStart}
      >
        {isCli ? '运行查看使用说明' : isWeb ? '启动浏览器预览' : '启动预览'}
      </Button>
    </div>
  )
}

function EnvVarsDrawer({ open, onClose, projectName, isDark, onSaveAndRestart }) {
  const [envVars, setEnvVars] = useState({})
  const [declaredKeys, setDeclaredKeys] = useState([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [visibleKeys, setVisibleKeys] = useState({})
  const [newKey, setNewKey] = useState('')

  useEffect(() => {
    if (!open || !projectName) return
    setLoading(true)
    api.fetchProjectEnv(projectName)
      .then((r) => {
        setEnvVars(r.env_vars || {})
        setDeclaredKeys(r.declared_keys || [])
      })
      .catch(() => message.error('加载环境变量失败'))
      .finally(() => setLoading(false))
  }, [open, projectName])

  const handleSave = async (restart) => {
    setSaving(true)
    try {
      await api.saveProjectEnv(projectName, envVars)
      message.success('环境变量已保存')
      if (restart) {
        onSaveAndRestart?.()
        onClose()
      }
    } catch (e) {
      message.error(e.message || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleAddKey = () => {
    const key = newKey.trim().toUpperCase().replace(/[^A-Z0-9_]/g, '_')
    if (!key) return
    if (key in envVars) { message.warning('变量已存在'); return }
    setEnvVars((prev) => ({ ...prev, [key]: '' }))
    setNewKey('')
  }

  const allKeys = [...new Set([...declaredKeys, ...Object.keys(envVars)])]
  const looksSecret = (k) => /key|secret|token|password|credential/i.test(k)

  return (
    <Drawer
      title="项目环境变量"
      open={open}
      onClose={onClose}
      width={480}
      styles={{ body: { padding: '16px 24px' } }}
      footer={
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <Button onClick={onClose}>取消</Button>
          <Space>
            <Button onClick={() => handleSave(false)} loading={saving}>仅保存</Button>
            <Button type="primary" icon={<SyncOutlined />} onClick={() => handleSave(true)} loading={saving}>
              保存并重启服务
            </Button>
          </Space>
        </div>
      }
    >
      {loading ? (
        <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>
      ) : (
        <>
          {declaredKeys.length > 0 && (
            <div style={{
              marginBottom: 16, padding: '8px 12px', borderRadius: 6,
              background: isDark ? '#161b22' : '#f0f5ff',
              border: `1px solid ${isDark ? '#30363d' : '#d6e4ff'}`,
              fontSize: 12, color: isDark ? '#8b949e' : '#656d76',
            }}>
              检测到 .env.example 中声明了 {declaredKeys.length} 个变量
            </div>
          )}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {allKeys.map((key) => {
              const isSecret = looksSecret(key)
              const visible = visibleKeys[key]
              return (
                <div key={key} style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <div style={{
                    width: 160, flexShrink: 0,
                    fontFamily: 'Menlo, Monaco, Consolas, monospace',
                    fontSize: 12, color: isDark ? '#79c0ff' : '#0550ae',
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }} title={key}>
                    {key}
                  </div>
                  <Input
                    size="small"
                    type={isSecret && !visible ? 'password' : 'text'}
                    value={envVars[key] || ''}
                    placeholder={declaredKeys.includes(key) ? '(需要填写)' : ''}
                    onChange={(e) => setEnvVars((prev) => ({ ...prev, [key]: e.target.value }))}
                    style={{ flex: 1, fontFamily: 'Menlo, Monaco, monospace', fontSize: 12 }}
                    suffix={
                      isSecret ? (
                        <Tooltip title={visible ? '隐藏' : '显示'}>
                          <span
                            style={{ cursor: 'pointer', color: isDark ? '#8b949e' : '#656d76' }}
                            onClick={() => setVisibleKeys((p) => ({ ...p, [key]: !p[key] }))}
                          >
                            {visible ? <EyeOutlined /> : <EyeInvisibleOutlined />}
                          </span>
                        </Tooltip>
                      ) : null
                    }
                  />
                  {!declaredKeys.includes(key) && (
                    <Tooltip title="删除">
                      <Button
                        size="small" type="text" danger icon={<DeleteOutlined />}
                        onClick={() => setEnvVars((prev) => {
                          const next = { ...prev }
                          delete next[key]
                          return next
                        })}
                      />
                    </Tooltip>
                  )}
                </div>
              )
            })}
          </div>
          <div style={{ marginTop: 16, display: 'flex', gap: 8 }}>
            <Input
              size="small" placeholder="新变量名 (如 API_KEY)"
              value={newKey}
              onChange={(e) => setNewKey(e.target.value)}
              onPressEnter={handleAddKey}
              style={{ flex: 1, fontFamily: 'Menlo, Monaco, monospace', fontSize: 12 }}
            />
            <Button size="small" icon={<PlusOutlined />} onClick={handleAddKey}>添加</Button>
          </div>
          {allKeys.length === 0 && (
            <div style={{
              textAlign: 'center', padding: '32px 0',
              color: isDark ? '#8b949e' : '#656d76', fontSize: 13,
            }}>
              暂无环境变量，点击上方「添加」按钮新增
            </div>
          )}
        </>
      )}
    </Drawer>
  )
}


export default function PreviewPanel({ preview, isRunning, isDark, height = 400, projectName }) {
  const [iframeKey, setIframeKey] = useState(0)
  const [iframeError, setIframeError] = useState(false)
  const [iframeLoading, setIframeLoading] = useState(true)
  const [starting, setStarting] = useState(false)
  const [restarting, setRestarting] = useState(false)
  const [envDrawerOpen, setEnvDrawerOpen] = useState(false)
  const [detected, setDetected] = useState(null)
  const [detecting, setDetecting] = useState(false)
  const [autoStartAttempted, setAutoStartAttempted] = useState(false)
  const [apiPathKey, setApiPathKey] = useState('root')

  // preview_ready 触发新预览时自动刷新 iframe，避免浏览器缓存旧内容
  useEffect(() => {
    if (!preview?.url) return
    setIframeKey((k) => k + 1)
    setIframeError(false)
    setIframeLoading(true)
  }, [preview])

  useEffect(() => {
    if (isRunning || !projectName || detected) return
    // 有 URL 的 Web 预览说明服务正在运行，信任它
    if (preview?.url) return
    // 无 URL 的预览（CLI 历史残留）或无预览 → 都需要重新检测
    let cancelled = false
    setDetecting(true)
    api.detectPreviewType(projectName)
      .then((r) => {
        if (cancelled) return
        setDetected(r)
        // 历史残留类型与实际检测不符 → 清除过期预览
        if (preview && !preview.url && r.project_type !== preview.project_type) {
          useStore.setState({ executionPreview: null })
        }
      })
      .catch(() => {})
      .finally(() => { if (!cancelled) setDetecting(false) })
    return () => { cancelled = true }
  }, [projectName, preview, isRunning, detected])

  // SSE 推送新 preview 时清空 detected 缓存 + 根据 framework 设置默认 tab
  useEffect(() => {
    if (preview) {
      setDetected(null)
      setAutoStartAttempted(false)
      setApiPathKey(preview.framework === 'fastapi' ? 'docs' : 'health')
    }
  }, [preview])

  // 后端 API 路径自动探测：找到第一个能响应的路径
  useEffect(() => {
    if (!preview?.url || preview.project_type !== 'web_backend') return
    const fw = preview.framework || ''
    const paths = fw === 'fastapi' ? FASTAPI_PATHS : GENERIC_API_PATHS
    // 只在默认 key 时探测（用户手动切换的不覆盖）
    const defaultKey = fw === 'fastapi' ? 'docs' : 'health'
    if (apiPathKey !== defaultKey) return

    let cancelled = false
    const base = preview.url.replace(/\/+$/, '')

    const tryPaths = async () => {
      for (const p of paths) {
        if (cancelled) return
        try {
          const res = await fetch(`${base}${p.path}`, { method: 'HEAD', mode: 'no-cors' })
          // no-cors: opaque = 可达; cors: ok = 可达
          if (res.type === 'opaque' || res.ok) {
            if (!cancelled) setApiPathKey(p.key)
            return
          }
        } catch { /* 继续下一个 */ }
      }
      // 全部不可达，兜底到根路径
      if (!cancelled) setApiPathKey('root')
    }
    tryPaths()
    return () => { cancelled = true }
  }, [preview])

  const handleIframeLoad = useCallback(() => {
    setIframeLoading(false)
    setIframeError(false)
  }, [])

  const handleIframeError = useCallback(() => {
    setIframeLoading(false)
    setIframeError(true)
  }, [])

  const handleStartPreview = useCallback(async () => {
    if (!projectName) return
    setStarting(true)
    try {
      const result = await api.startPreview(projectName)
      if (result.available) {
        useStore.setState({ executionPreview: result })
        message.success('预览已启动')
      } else {
        message.warning(result.message || '预览启动失败')
      }
    } catch (e) {
      message.error(e.message || '启动预览失败')
    } finally {
      setStarting(false)
    }
  }, [projectName])

  // 执行完成后检测到可预览类型 → 自动启动（仅尝试一次）
  useEffect(() => {
    if (autoStartAttempted || preview || isRunning || starting || !detected) return
    const isPreviewable = detected.project_type && detected.project_type !== 'unknown' && detected.project_type !== 'library'
    if (!isPreviewable || !projectName) return
    setAutoStartAttempted(true)
    handleStartPreview()
  }, [detected, preview, isRunning, autoStartAttempted, projectName, starting, handleStartPreview])

  const handleStopPreview = async () => {
    if (!projectName) return
    try {
      await api.stopPreview(projectName)
      useStore.setState({ executionPreview: null })
      message.success('预览已停止')
    } catch (e) {
      message.error(e.message || '停止预览失败')
    }
  }

  const handleRestartPreview = async () => {
    if (!projectName) return
    setRestarting(true)
    try {
      const result = await api.restartPreview(projectName)
      if (result.available) {
        useStore.setState({ executionPreview: result })
        message.success('服务已重启')
      } else {
        message.warning(result.message || '重启失败')
      }
    } catch (e) {
      message.error(e.message || '重启服务失败')
    } finally {
      setRestarting(false)
    }
  }

  // 正在执行中
  if (!preview && isRunning) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height, flexDirection: 'column', gap: 12 }}>
        <Spin size="large" />
        <div style={{ color: isDark ? '#8b949e' : '#656d76', fontSize: 13 }}>
          执行完成后将自动启动预览...
        </div>
      </div>
    )
  }

  // 无预览：按检测到的项目类型展示不同 UI
  if (!preview) {
    if (detecting) {
      return (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height, flexDirection: 'column', gap: 12 }}>
          <Spin />
          <div style={{ color: isDark ? '#8b949e' : '#656d76', fontSize: 13 }}>检测项目类型...</div>
        </div>
      )
    }
    if (detected && detected.project_type !== 'unknown' && detected.project_type !== 'library') {
      return <EmptyDetectedState detected={detected} isDark={isDark} starting={starting} onStart={handleStartPreview} />
    }
    return (
      <div style={{
        display: 'flex', flexDirection: 'column', alignItems: 'center',
        justifyContent: 'center', height, gap: 12, padding: 24,
      }}>
        <GlobalOutlined style={{ fontSize: 40, color: isDark ? '#8b949e' : '#bbb' }} />
        <div style={{ fontSize: 16, fontWeight: 500, color: isDark ? '#c9d1d9' : '#1f2328' }}>暂无预览</div>
        <div style={{ color: isDark ? '#8b949e' : '#656d76', fontSize: 13, textAlign: 'center' }}>
          未检测到可预览的项目类型
        </div>
        {projectName && (
          <Button
            type="primary"
            icon={<PlayCircleOutlined />}
            loading={starting}
            onClick={handleStartPreview}
            style={{ marginTop: 8 }}
          >
            尝试启动预览
          </Button>
        )}
      </div>
    )
  }

  const { available, url, project_type, command, runtime, message: msg, port, framework } = preview
  const runtimeInfo = RUNTIME_LABELS[runtime] || RUNTIME_LABELS.local
  const typeLabel = TYPE_LABELS[project_type] || project_type

  // Web 应用预览
  if (available && url) {
    const isBackendApi = project_type === 'web_backend'
    const apiPaths = getApiPaths(framework)
    const baseUrl = url.replace(/\/+$/, '')
    const apiPathSuffix = isBackendApi
      ? (apiPaths.find((p) => p.key === apiPathKey)?.path ?? '')
      : ''
    const displayUrl = `${baseUrl}${apiPathSuffix}`

    const previewToolbar = (
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8, padding: '4px 0' }}>
        <Space size={6}>
          <Tag icon={runtimeInfo.icon} color={runtimeInfo.color} style={{ margin: 0 }}>{runtimeInfo.label}</Tag>
          <Tag color="geekblue" style={{ margin: 0 }}>{typeLabel}</Tag>
          <Text type="secondary" style={{ fontSize: 11 }}>{command}</Text>
        </Space>
        <Space size={4}>
          <Tooltip title="刷新">
            <Button size="small" icon={<ReloadOutlined />} onClick={() => { setIframeKey((k) => k + 1); setIframeError(false); setIframeLoading(true) }} />
          </Tooltip>
          {projectName && (
            <Tooltip title="重启服务">
              <Button size="small" icon={<SyncOutlined />} loading={restarting} onClick={handleRestartPreview} />
            </Tooltip>
          )}
          {projectName && (
            <Tooltip title="环境变量">
              <Button size="small" icon={<SettingOutlined />} onClick={() => setEnvDrawerOpen(true)} />
            </Tooltip>
          )}
          <Tooltip title="新窗口打开">
            <Button size="small" icon={<ExpandOutlined />} onClick={() => window.open(displayUrl, '_blank')} />
          </Tooltip>
          {projectName && (
            <Tooltip title="停止预览">
              <Button size="small" danger icon={<PoweroffOutlined />} onClick={handleStopPreview} />
            </Tooltip>
          )}
        </Space>
      </div>
    )

    const envDrawer = (
      <EnvVarsDrawer
        open={envDrawerOpen}
        onClose={() => setEnvDrawerOpen(false)}
        projectName={projectName}
        isDark={isDark}
        onSaveAndRestart={handleRestartPreview}
      />
    )

    // ── 后端 API：状态面板（替代无意义的 iframe JSON 展示）──
    if (isBackendApi) {
      const frameworkLabel = { flask: 'Flask', fastapi: 'FastAPI', django: 'Django', node: 'Node.js', go: 'Go' }[framework] || 'HTTP'
      return (
        <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
          {previewToolbar}

          {/* 服务状态卡片 */}
          <div style={{
            display: 'flex', alignItems: 'center', gap: 12, padding: '16px 20px',
            background: isDark ? '#0d2818' : '#f6ffed',
            border: `1px solid ${isDark ? '#1a4d2e' : '#b7eb8f'}`,
            borderRadius: 8, marginBottom: 12,
          }}>
            <CheckCircleFilled style={{ color: '#52c41a', fontSize: 28 }} />
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 600, fontSize: 15, color: isDark ? '#f0f6fc' : '#1f2328' }}>
                {frameworkLabel} API 服务运行中
              </div>
              <div style={{ fontSize: 12, color: isDark ? '#8b949e' : '#656d76', marginTop: 2 }}>
                {url}{port > 0 ? ` · 端口 ${port}` : ''}
              </div>
            </div>
            <Button
              type="primary" size="small" icon={<ExpandOutlined />}
              onClick={() => window.open(url, '_blank')}
            >
              打开 API
            </Button>
          </div>

          {/* 可用端点 */}
          <div style={{
            flex: 1, overflow: 'auto',
            background: isDark ? '#0d1117' : '#ffffff',
            borderRadius: 8,
            border: `1px solid ${isDark ? '#21262d' : '#d0d7de'}`,
          }}>
            <div style={{
              padding: '10px 16px',
              borderBottom: `1px solid ${isDark ? '#21262d' : '#d0d7de'}`,
              fontSize: 13, fontWeight: 600,
              color: isDark ? '#c9d1d9' : '#1f2328',
            }}>
              可用端点
            </div>
            <div style={{ padding: '8px 16px' }}>
              {apiPaths.map((item) => (
                <div
                  key={item.key}
                  onClick={() => window.open(`${baseUrl}${item.path}`, '_blank')}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 10,
                    padding: '8px 12px', borderRadius: 6, cursor: 'pointer',
                    marginBottom: 4,
                    background: isDark ? 'transparent' : 'transparent',
                    transition: 'background 0.15s',
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.background = isDark ? '#161b22' : '#f6f8fa' }}
                  onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent' }}
                >
                  <Tag color="blue" style={{ margin: 0, fontSize: 11, fontFamily: 'Menlo, Monaco, monospace' }}>
                    GET
                  </Tag>
                  <span style={{
                    fontFamily: 'Menlo, Monaco, Consolas, monospace',
                    fontSize: 13, color: isDark ? '#79c0ff' : '#0550ae',
                  }}>
                    {item.path || '/'}
                  </span>
                  <span style={{ fontSize: 12, color: isDark ? '#8b949e' : '#656d76' }}>
                    {item.label}
                  </span>
                  <ExpandOutlined style={{ marginLeft: 'auto', fontSize: 11, color: isDark ? '#484f58' : '#afb8c1' }} />
                </div>
              ))}
            </div>
          </div>

          {/* 提示：这是纯 API，没有前端页面 */}
          <div style={{
            marginTop: 10, padding: '10px 14px',
            background: isDark ? '#1c1917' : '#fffbe6',
            border: `1px solid ${isDark ? '#44403c' : '#ffe58f'}`,
            borderRadius: 8, fontSize: 13, lineHeight: 1.6,
            color: isDark ? '#d6d3d1' : '#78350f',
          }}>
            <div style={{ fontWeight: 600, marginBottom: 2 }}>💡 这是一个纯后端 API 服务</div>
            <div>应用目前只有后端接口，没有可视化的前端页面。如需 Web 界面，在对话中告诉 AutoC「添加前端页面」即可自动生成。</div>
          </div>

          {envDrawer}
        </div>
      )
    }

    // ── 前端 / 全栈应用：iframe 预览 ──
    return (
      <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
        {previewToolbar}
        <div style={{ flex: 1, position: 'relative', borderRadius: 6, overflow: 'hidden', border: `1px solid ${isDark ? '#30363d' : '#d0d7de'}` }}>
          {iframeLoading && (
            <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', background: isDark ? '#0d1117' : '#fafafa', zIndex: 1 }}>
              <Spin description="加载预览中..." />
            </div>
          )}
          {iframeError ? (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', gap: 12, color: isDark ? '#8b949e' : '#656d76' }}>
              <StopOutlined style={{ fontSize: 28, color: '#cf222e' }} />
              <div>预览页面加载失败</div>
              <Space>
                <Button size="small" onClick={() => { setIframeKey(k => k + 1); setIframeError(false); setIframeLoading(true) }}>重试</Button>
                <Button size="small" type="link" onClick={() => window.open(displayUrl, '_blank')}>新窗口打开</Button>
              </Space>
            </div>
          ) : (
            <iframe
              key={`${iframeKey}-${apiPathKey}`}
              src={`${displayUrl}${displayUrl.includes('?') ? '&' : '?'}_t=${iframeKey}`}
              title="Project Preview"
              style={{ width: '100%', height: '100%', border: 'none', display: 'block' }}
              sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-modals"
              onLoad={handleIframeLoad}
              onError={handleIframeError}
            />
          )}
        </div>
        <div style={{ marginTop: 4, display: 'flex', alignItems: 'center', gap: 4 }}>
          <LinkOutlined style={{ color: '#58a6ff', fontSize: 11 }} />
          <a href={displayUrl} target="_blank" rel="noopener noreferrer" style={{ fontSize: 11, color: '#58a6ff' }}>{displayUrl}</a>
          {port > 0 && <Text type="secondary" style={{ fontSize: 10 }}>(端口 {port})</Text>}
        </div>
        {envDrawer}
      </div>
    )
  }

  // CLI 工具：显示使用说明输出
  if (available && project_type === 'cli_tool') {
    return (
      <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          marginBottom: 8, padding: '4px 0',
        }}>
          <Space size={6}>
            <Tag icon={runtimeInfo.icon} color={runtimeInfo.color}>{runtimeInfo.label}</Tag>
            <Tag color="orange">{typeLabel}</Tag>
            <Text code style={{ fontSize: 12 }}>$ {command}</Text>
          </Space>
          <Space size={4}>
            <Tooltip title="重新运行">
              <Button size="small" icon={<ReloadOutlined />} loading={starting} onClick={handleStartPreview} />
            </Tooltip>
            {projectName && (
              <Tooltip title="环境变量">
                <Button size="small" icon={<SettingOutlined />} onClick={() => setEnvDrawerOpen(true)} />
              </Tooltip>
            )}
            {projectName && (
              <Tooltip title="停止">
                <Button size="small" danger icon={<PoweroffOutlined />} onClick={handleStopPreview} />
              </Tooltip>
            )}
          </Space>
        </div>
        <div style={{
          flex: 1, overflow: 'auto',
          background: isDark ? '#0d1117' : '#f6f8fa',
          borderRadius: 6, border: `1px solid ${isDark ? '#21262d' : '#d0d7de'}`,
        }}>
          <pre style={{
            padding: 16, margin: 0,
            fontSize: 13, lineHeight: 1.6,
            fontFamily: 'Menlo, Monaco, Consolas, monospace',
            whiteSpace: 'pre-wrap', wordBreak: 'break-all',
            color: isDark ? '#c9d1d9' : '#1f2328',
          }}>
            {msg || '(无输出)'}
          </pre>
        </div>
        <EnvVarsDrawer
          open={envDrawerOpen}
          onClose={() => setEnvDrawerOpen(false)}
          projectName={projectName}
          isDark={isDark}
          onSaveAndRestart={handleRestartPreview}
        />
      </div>
    )
  }

  // 预览启动失败
  return (
    <Alert
      type="warning"
      showIcon
      message="预览未能启动"
      description={
        <div>
          <Paragraph style={{ margin: 0 }}>
            <Text type="secondary">项目类型:</Text> {typeLabel}
          </Paragraph>
          {command && <Paragraph style={{ margin: '4px 0 0' }}><Text type="secondary">尝试命令:</Text> <Text code>{command}</Text></Paragraph>}
          {msg && <Paragraph style={{ margin: '4px 0 0' }}><Text type="secondary">错误信息:</Text> {msg}</Paragraph>}
        </div>
      }
    />
  )
}
