import { useEffect, useRef, useState, useCallback } from 'react'
import { Button, Space, Tooltip, Typography } from 'antd'
import {
  ClearOutlined, FullscreenOutlined, FullscreenExitOutlined,
  SwapOutlined, ReloadOutlined,
} from '@ant-design/icons'
import useStore from '../../stores/useStore'

const { Text } = Typography

let Terminal, FitAddon, WebLinksAddon
const loadXterm = async () => {
  if (!Terminal) {
    const [xtermMod, fitMod, linksMod] = await Promise.all([
      import('@xterm/xterm'),
      import('@xterm/addon-fit'),
      import('@xterm/addon-web-links'),
      import('@xterm/xterm/css/xterm.css'),
    ])
    Terminal = xtermMod.Terminal
    FitAddon = fitMod.FitAddon
    WebLinksAddon = linksMod.WebLinksAddon
  }
}

const DARK_THEME = {
  background: '#1a1a2e',
  foreground: '#e0e0e0',
  cursor: '#528bff',
  cursorAccent: '#1a1a2e',
  selectionBackground: 'rgba(82, 139, 255, 0.3)',
  black: '#1a1a2e',
  brightBlack: '#555555',
  red: '#ff6b6b',
  brightRed: '#ff8787',
  green: '#51cf66',
  brightGreen: '#69db7c',
  yellow: '#ffd43b',
  brightYellow: '#ffe066',
  blue: '#528bff',
  brightBlue: '#748ffc',
  magenta: '#cc5de8',
  brightMagenta: '#da77f2',
  cyan: '#22b8cf',
  brightCyan: '#3bc9db',
  white: '#e0e0e0',
  brightWhite: '#ffffff',
}

const LIGHT_THEME = {
  background: '#ffffff',
  foreground: '#333333',
  cursor: '#1890ff',
  selectionBackground: 'rgba(24, 144, 255, 0.2)',
  black: '#333333',
  red: '#e74c3c',
  green: '#27ae60',
  yellow: '#f39c12',
  blue: '#1890ff',
  magenta: '#8e44ad',
  cyan: '#16a085',
  white: '#f5f5f5',
}

const CONNECT_TIMEOUT_MS = 8000
const FALLBACK_DELAY_MS = 800

export default function WebTerminal({ wsUrl, height = 400 }) {
  const theme = useStore(s => s.theme)
  const termRef = useRef(null)
  const containerRef = useRef(null)
  const fitAddonRef = useRef(null)
  const wsRef = useRef(null)
  const mountedRef = useRef(true)
  const connectTimerRef = useRef(null)
  const autoFallbackRef = useRef(false)

  const [connected, setConnected] = useState(false)
  const [fullscreen, setFullscreen] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [activeMode, setActiveMode] = useState(null)
  const [connecting, setConnecting] = useState(false)

  const connectWsRef = useRef(null)

  const connectWs = useCallback((url, term, mode = 'local') => {
    if (!url || !term || !mountedRef.current) return

    if (wsRef.current) {
      autoFallbackRef.current = false
      wsRef.current.close()
      wsRef.current = null
    }

    setConnecting(true)
    setConnected(false)
    setActiveMode(null)

    const sep = url.includes('?') ? '&' : '?'
    const fullUrl = `${url}${sep}mode=${mode}`
    let didOpen = false

    clearTimeout(connectTimerRef.current)
    connectTimerRef.current = setTimeout(() => {
      if (wsRef.current && wsRef.current.readyState !== WebSocket.OPEN) {
        wsRef.current.close()
        if (mountedRef.current) {
          setConnecting(false)
          term.writeln('\x1b[31m✗ 连接超时\x1b[0m')
        }
      }
    }, CONNECT_TIMEOUT_MS)

    try {
      const ws = new WebSocket(fullUrl)

      ws.onopen = () => {
        clearTimeout(connectTimerRef.current)
        if (wsRef.current !== ws) return
        didOpen = true
        setConnected(true)
        setConnecting(false)
        if (termRef.current && termRef.current.cols > 0 && termRef.current.rows > 0) {
          ws.send(JSON.stringify({
            type: 'resize',
            cols: termRef.current.cols,
            rows: termRef.current.rows,
          }))
        }
      }

      ws.onmessage = (event) => {
        if (wsRef.current !== ws) return
        const msg = JSON.parse(event.data)
        if (msg.type === 'output') {
          term.write(msg.data)
        } else if (msg.type === 'error') {
          term.writeln(`\r\n\x1b[31m✗ ${msg.data}\x1b[0m`)
        } else if (msg.type === 'status') {
          if (msg.data === 'connected') {
            const realMode = msg.mode || mode
            setActiveMode(realMode)
            autoFallbackRef.current = realMode === 'docker'
          } else if (msg.data === 'exited') {
            term.writeln('\r\n\x1b[33mShell 已退出\x1b[0m')
          } else if (msg.data === 'docker_unavailable') {
            term.writeln('\x1b[33m⚠ Docker 不可用，切换回本地终端\x1b[0m')
            setTimeout(() => {
              if (mountedRef.current) {
                connectWsRef.current?.(url, term, 'local')
              }
            }, FALLBACK_DELAY_MS)
          }
        }
      }

      ws.onclose = () => {
        clearTimeout(connectTimerRef.current)
        if (wsRef.current !== ws) return
        setConnected(false)
        setConnecting(false)

        if (autoFallbackRef.current && mountedRef.current) {
          autoFallbackRef.current = false
          term.writeln('\r\n\x1b[33m⚠ Docker 连接中断，切换到本地终端...\x1b[0m')
          setTimeout(() => {
            if (mountedRef.current) {
              connectWsRef.current?.(url, term, 'local')
            }
          }, FALLBACK_DELAY_MS)
          return
        }

        if (didOpen) {
          term.writeln('\r\n\x1b[90m连接已关闭\x1b[0m')
        }
      }

      ws.onerror = () => {
        clearTimeout(connectTimerRef.current)
        if (wsRef.current !== ws) return
        if (!autoFallbackRef.current) {
          setConnecting(false)
          term.writeln('\x1b[31m✗ 连接失败\x1b[0m')
          term.writeln('\x1b[90m提示: 请检查后端服务是否运行中\x1b[0m')
        }
      }

      wsRef.current = ws
    } catch {
      clearTimeout(connectTimerRef.current)
      setConnecting(false)
      term.writeln('\x1b[31m✗ 连接失败\x1b[0m')
    }
  }, [])

  connectWsRef.current = connectWs

  const initTerminal = useCallback(async () => {
    await loadXterm()
    if (!containerRef.current || termRef.current) return

    const fitAddon = new FitAddon()
    const webLinksAddon = new WebLinksAddon()
    const term = new Terminal({
      fontFamily: "'JetBrains Mono', 'Fira Code', 'SF Mono', Monaco, Menlo, monospace",
      fontSize: 13,
      lineHeight: 1.3,
      cursorBlink: true,
      cursorStyle: 'bar',
      scrollback: 5000,
      theme: theme === 'dark' ? DARK_THEME : LIGHT_THEME,
      allowProposedApi: true,
    })

    term.loadAddon(fitAddon)
    term.loadAddon(webLinksAddon)
    term.open(containerRef.current)
    fitAddon.fit()

    termRef.current = term
    fitAddonRef.current = fitAddon
    setLoaded(true)

    term.onData((data) => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: 'input', data }))
      }
    })

    term.onResize(({ cols, rows }) => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: 'resize', cols, rows }))
      }
    })

    if (wsUrl) {
      connectWs(wsUrl, term, 'local')
    }

    document.fonts.ready.then(() => {
      if (fitAddonRef.current && mountedRef.current) fitAddonRef.current.fit()
    })

    return () => {
      term.dispose()
      termRef.current = null
    }
  }, [wsUrl, theme, connectWs])

  useEffect(() => {
    mountedRef.current = true
    initTerminal()
    return () => {
      mountedRef.current = false
      clearTimeout(connectTimerRef.current)
      wsRef.current?.close()
      termRef.current?.dispose()
      termRef.current = null
    }
  }, [initTerminal])

  useEffect(() => {
    if (fitAddonRef.current) {
      setTimeout(() => fitAddonRef.current?.fit(), 100)
    }
  }, [fullscreen])

  useEffect(() => {
    const observer = new ResizeObserver(() => fitAddonRef.current?.fit())
    if (containerRef.current) observer.observe(containerRef.current)
    return () => observer.disconnect()
  }, [loaded])

  const handleClear = () => termRef.current?.clear()

  const handleToggle = () => {
    if (!wsUrl || !termRef.current || connecting) return
    const newMode = activeMode === 'docker' ? 'local' : 'docker'
    const label = newMode === 'docker' ? 'Docker' : '本地'
    termRef.current.writeln(`\r\n\x1b[90m切换到${label}终端...\x1b[0m`)
    connectWs(wsUrl, termRef.current, newMode)
  }

  const handleReconnect = () => {
    if (!wsUrl || !termRef.current) return
    connectWs(wsUrl, termRef.current, activeMode || 'local')
  }

  const containerStyle = fullscreen
    ? { position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, zIndex: 1000 }
    : { height, display: 'flex', flexDirection: 'column' }

  const isDark = theme === 'dark'

  const modeLabel = activeMode === 'docker'
    ? 'Docker 终端'
    : activeMode === 'local'
    ? '本地终端'
    : '终端'

  return (
    <div style={containerStyle}>
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '4px 8px',
        borderBottom: `1px solid ${isDark ? '#333' : '#e0e0e0'}`,
        background: isDark ? '#252526' : '#f3f3f3',
        flexShrink: 0,
      }}>
        <Space size={4} style={{ alignItems: 'center' }}>
          <Text style={{ fontSize: 12, fontWeight: 500, color: isDark ? '#ccc' : '#333' }}>
            {modeLabel}
          </Text>
          {connecting ? (
            <Text type="warning" style={{ fontSize: 11 }}>◌ 连接中...</Text>
          ) : connected ? (
            <Text type="success" style={{ fontSize: 11 }}>● 已连接</Text>
          ) : (
            <Text type="secondary" style={{ fontSize: 11 }}>○ 未连接</Text>
          )}
        </Space>
        <Space size={4}>
          {connected && (
            <Tooltip title={activeMode === 'docker' ? '切换到本地终端' : '切换到 Docker 终端'}>
              <Button type="text" size="small" icon={<SwapOutlined />} onClick={handleToggle} />
            </Tooltip>
          )}
          <Tooltip title="清屏">
            <Button type="text" size="small" icon={<ClearOutlined />} onClick={handleClear} />
          </Tooltip>
          {!connected && !connecting && wsUrl && (
            <Tooltip title="重新连接">
              <Button type="text" size="small" icon={<ReloadOutlined />} onClick={handleReconnect} />
            </Tooltip>
          )}
          <Tooltip title={fullscreen ? '退出全屏' : '全屏'}>
            <Button type="text" size="small"
              icon={fullscreen ? <FullscreenExitOutlined /> : <FullscreenOutlined />}
              onClick={() => setFullscreen(!fullscreen)}
            />
          </Tooltip>
        </Space>
      </div>
      <div ref={containerRef} style={{ flex: 1, minHeight: 0, padding: 4 }}
        onClick={() => termRef.current?.focus()} />
    </div>
  )
}
