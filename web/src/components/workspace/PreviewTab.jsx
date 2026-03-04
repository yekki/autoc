import { useState, useCallback, useRef } from 'react'
import { Button, Space, Tag, Typography, Spin, Result, Tooltip, Alert } from 'antd'
import {
  GlobalOutlined, CodeOutlined, ReloadOutlined, ExpandOutlined,
  CompressOutlined, LinkOutlined, CloudServerOutlined, DesktopOutlined,
  StopOutlined, FullscreenOutlined, FullscreenExitOutlined,
} from '@ant-design/icons'
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

export default function PreviewTab() {
  const theme = useStore((s) => s.theme)
  const preview = useStore((s) => s.executionPreview)
  const isRunning = useStore((s) => s.isRunning)
  const isDark = theme === 'dark'

  const [iframeKey, setIframeKey] = useState(0)
  const [iframeError, setIframeError] = useState(false)
  const [iframeLoading, setIframeLoading] = useState(true)
  const [isFullscreen, setIsFullscreen] = useState(false)
  const containerRef = useRef(null)

  const handleIframeLoad = useCallback(() => {
    setIframeLoading(false)
    setIframeError(false)
  }, [])

  const handleIframeError = useCallback(() => {
    setIframeLoading(false)
    setIframeError(true)
  }, [])

  const toggleFullscreen = useCallback(() => {
    if (!containerRef.current) return
    if (!document.fullscreenElement) {
      containerRef.current.requestFullscreen().then(() => setIsFullscreen(true)).catch(() => {})
    } else {
      document.exitFullscreen().then(() => setIsFullscreen(false)).catch(() => {})
    }
  }, [])

  if (!preview && isRunning) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 'calc(100vh - 280px)', flexDirection: 'column', gap: 12 }}>
        <Spin size="large" />
        <div style={{ color: isDark ? '#8b949e' : '#656d76', fontSize: 14 }}>
          执行完成后将自动启动预览...
        </div>
      </div>
    )
  }

  if (!preview) {
    return (
      <Result
        icon={<GlobalOutlined style={{ color: isDark ? '#8b949e' : '#bbb', fontSize: 40 }} />}
        title="暂无预览"
        subTitle="项目执行完成后将自动检测类型并启动预览"
        style={{ padding: '48px 0' }}
      />
    )
  }

  const { available, url, project_type, command, runtime, message: msg, port } = preview
  const runtimeInfo = RUNTIME_LABELS[runtime] || RUNTIME_LABELS.local
  const typeLabel = TYPE_LABELS[project_type] || project_type

  if (available && url) {
    return (
      <div
        ref={containerRef}
        style={{
          height: isFullscreen ? '100vh' : 'calc(100vh - 280px)',
          display: 'flex',
          flexDirection: 'column',
          background: isDark ? '#0d1117' : '#ffffff',
        }}
      >
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          padding: '8px 12px', flexShrink: 0,
          borderBottom: `1px solid ${isDark ? '#21262d' : '#e8e8e8'}`,
        }}>
          <Space size={8}>
            <Tag icon={runtimeInfo.icon} color={runtimeInfo.color} style={{ margin: 0 }}>{runtimeInfo.label}</Tag>
            <Tag color="geekblue" style={{ margin: 0 }}>{typeLabel}</Tag>
            <Text type="secondary" style={{ fontSize: 12 }}>{command}</Text>
          </Space>
          <Space size={4}>
            <Tooltip title="刷新预览">
              <Button size="small" icon={<ReloadOutlined />} onClick={() => { setIframeKey((k) => k + 1); setIframeError(false); setIframeLoading(true) }} />
            </Tooltip>
            <Tooltip title="新窗口打开">
              <Button size="small" icon={<ExpandOutlined />} onClick={() => window.open(url, '_blank')} />
            </Tooltip>
            <Tooltip title={isFullscreen ? '退出全屏' : '全屏'}>
              <Button
                size="small"
                icon={isFullscreen ? <FullscreenExitOutlined /> : <FullscreenOutlined />}
                onClick={toggleFullscreen}
              />
            </Tooltip>
          </Space>
        </div>

        <div style={{ flex: 1, position: 'relative', overflow: 'hidden' }}>
          {iframeLoading && (
            <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', background: isDark ? '#0d1117' : '#fafafa', zIndex: 1 }}>
              <Spin tip="加载预览中..." />
            </div>
          )}
          {iframeError ? (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', gap: 12, color: isDark ? '#8b949e' : '#656d76' }}>
              <StopOutlined style={{ fontSize: 32, color: '#cf222e' }} />
              <div style={{ fontSize: 14 }}>预览页面加载失败</div>
              <Space>
                <Button size="small" onClick={() => { setIframeKey((k) => k + 1); setIframeError(false); setIframeLoading(true) }}>重试</Button>
                <Button size="small" type="link" onClick={() => window.open(url, '_blank')}>新窗口打开</Button>
              </Space>
            </div>
          ) : (
            <iframe
              key={iframeKey}
              src={url}
              title="Project Preview"
              style={{ width: '100%', height: '100%', border: 'none', display: 'block' }}
              sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-modals"
              onLoad={handleIframeLoad}
              onError={handleIframeError}
            />
          )}
        </div>

        <div style={{
          padding: '4px 12px', flexShrink: 0,
          borderTop: `1px solid ${isDark ? '#21262d' : '#e8e8e8'}`,
          display: 'flex', alignItems: 'center', gap: 4,
        }}>
          <LinkOutlined style={{ color: '#58a6ff', fontSize: 12 }} />
          <a href={url} target="_blank" rel="noopener noreferrer" style={{ fontSize: 12, color: '#58a6ff' }}>{url}</a>
          {port > 0 && <Text type="secondary" style={{ fontSize: 11 }}>(端口 {port})</Text>}
        </div>
      </div>
    )
  }

  if (available && project_type === 'cli_tool') {
    return (
      <div>
        <Space size={8} style={{ marginBottom: 12 }}>
          <Tag icon={runtimeInfo.icon} color={runtimeInfo.color}>{runtimeInfo.label}</Tag>
          <Tag color="orange">{typeLabel}</Tag>
          <Text code style={{ fontSize: 13 }}>$ {command}</Text>
        </Space>
        <pre style={{
          background: isDark ? '#0d1117' : '#f6f8fa',
          borderRadius: 6, padding: 16, margin: 0,
          fontSize: 13, lineHeight: 1.5,
          fontFamily: 'Menlo, Monaco, Consolas, monospace',
          whiteSpace: 'pre-wrap', wordBreak: 'break-all',
          color: isDark ? '#c9d1d9' : '#1f2328',
          maxHeight: 'calc(100vh - 320px)', overflow: 'auto',
        }}>
          {msg || '(无输出)'}
        </pre>
      </div>
    )
  }

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
