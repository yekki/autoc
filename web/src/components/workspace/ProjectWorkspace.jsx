import { useState, useEffect, useMemo, useRef } from 'react'
import { Tabs, Badge, Empty, Spin } from 'antd'
import {
  DashboardOutlined, CodeOutlined, GlobalOutlined,
  CodeSandboxOutlined, HistoryOutlined, ThunderboltOutlined,
  FileTextOutlined,
} from '@ant-design/icons'
import useStore from '../../stores/useStore'
import * as api from '../../services/api'
import PreviewPanel from '../shared/PreviewPanel'
import WebTerminal from '../shared/WebTerminal'
import OverviewTab from './OverviewTab'
import CodeTab from './CodeTab'
import RequirementHistoryTab from './RequirementHistoryTab'
import CostTab from './CostTab'
import LogTab from './LogTab'
import { formatTokenCount } from './helpers'

const TabScrollWrap = ({ children, noScroll = false }) => (
  <div style={{
    height: '100%',
    minHeight: 0,
    overflowY: noScroll ? 'hidden' : 'auto',
    overflowX: 'hidden',
  }}>
    {children}
  </div>
)

export default function ProjectWorkspace() {
  const theme = useStore(s => s.theme)
  const selectedProjectName = useStore(s => s.selectedProjectName)
  const executionFiles = useStore(s => s.executionFiles)
  const isRunning = useStore(s => s.isRunning)
  const logCount = useStore(s => s.executionLogs.length)
  const activeTab = useStore(s => s.activeTab)
  const setActiveTab = useStore(s => s.setActiveTab)
  const tokenRuns = useStore(s => s.executionTokenRuns)
  const sessionId = useStore(s => s.sessionId)
  const stats = useStore(s => s.executionStats)
  const executionPreview = useStore(s => s.executionPreview)
  const agentTokens = useStore(s => s.executionAgentTokens)

  const [project, setProject] = useState(null)
  const [workspaceFiles, setWorkspaceFiles] = useState([])
  const [loadingProject, setLoadingProject] = useState(false)

  // 加载项目信息：初始化 + 执行结束后刷新（修复执行后按钮/状态不更新）
  const prevRunningRef = useRef(isRunning)
  useEffect(() => {
    const wasRunning = prevRunningRef.current
    prevRunningRef.current = isRunning
    if (!selectedProjectName) return
    const shouldRefresh = !isRunning && wasRunning
    if (!project || shouldRefresh) {
      if (!project) setLoadingProject(true)
      api.fetchProject(selectedProjectName)
        .then(p => { setProject(p); setWorkspaceFiles(p?.workspace_files || []) })
        .catch(() => {})
        .finally(() => setLoadingProject(false))
    }
  }, [selectedProjectName, isRunning])

  // 执行过程中更新文件列表
  useEffect(() => {
    if (executionFiles?.length) {
      setWorkspaceFiles(prev => [...new Set([...prev, ...executionFiles])])
    } else if (executionFiles && executionFiles.length === 0 && isRunning) {
      setWorkspaceFiles([])
    }
  }, [executionFiles, isRunning])

  const isDark = theme === 'dark'

  // WebSocket 终端地址
  const terminalWsUrl = useMemo(() => {
    if (!selectedProjectName) return null
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const { hostname, port } = window.location
    return `${proto}//${hostname}${port ? ':' + port : ''}/api/v1/terminal/${encodeURIComponent(selectedProjectName)}`
  }, [selectedProjectName])

  if (!selectedProjectName) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
        <Empty description="请选择或创建一个项目" />
      </div>
    )
  }

  if (loadingProject && !project) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
        <Spin description="加载项目..." size="large" />
      </div>
    )
  }

  const _runsTotal = tokenRuns.reduce((s, r) => s + (r.total_tokens || 0), 0)
  const _currentInRuns = sessionId && tokenRuns.some(r => r.session_id === sessionId)
  const _liveExtra = (isRunning && !_currentInRuns && (stats.tokens || 0)) || 0
  const totalTokens = (_runsTotal + _liveExtra) || 0

  const pastCount = tokenRuns.filter(r => r.session_id && r.session_id !== sessionId).length

  // 所有 Tab 的内容定义（与 key 对应）
  const tabPanels = {
    overview: <TabScrollWrap><OverviewTab project={project} /></TabScrollWrap>,
    code: <TabScrollWrap><CodeTab projectName={selectedProjectName} workspaceFiles={workspaceFiles} /></TabScrollWrap>,
    preview: (
      <TabScrollWrap noScroll>
        <div style={{ height: '100%', padding: 16 }}>
          <PreviewPanel preview={executionPreview} isRunning={isRunning} isDark={isDark} height="100%" projectName={selectedProjectName} />
        </div>
      </TabScrollWrap>
    ),
    terminal: (
      <TabScrollWrap noScroll>
        <div style={{ height: '100%' }}>
          <WebTerminal wsUrl={terminalWsUrl} height="100%" />
        </div>
      </TabScrollWrap>
    ),
    log: <TabScrollWrap><LogTab /></TabScrollWrap>,
    history: <TabScrollWrap><RequirementHistoryTab /></TabScrollWrap>,
    cost: <TabScrollWrap><CostTab /></TabScrollWrap>,
  }

  // 一级主 Tab（始终显示）
  const primaryTabs = [
    {
      key: 'overview',
      label: (
        <span>
          <DashboardOutlined /> 概览
          {isRunning && <Badge status="processing" style={{ marginLeft: 6 }} />}
        </span>
      ),
    },
    {
      key: 'code',
      label: (
        <span>
          <CodeOutlined /> 代码
          {workspaceFiles.length > 0 && <Badge count={workspaceFiles.length} size="small" style={{ marginLeft: 6 }} />}
        </span>
      ),
    },
    {
      key: 'preview',
      label: (
        <span>
          <GlobalOutlined /> 预览
          {executionPreview?.available && <Badge status="success" style={{ marginLeft: 6 }} />}
        </span>
      ),
    },
  ]

  // 二级辅助 Tab（收入 "…" 下拉菜单）
  const secondaryTabMeta = [
    { key: 'terminal', label: '终端', icon: <CodeSandboxOutlined /> },
    {
      key: 'log', icon: <FileTextOutlined />,
      label: logCount > 0 ? `日志 (${logCount > 999 ? '999+' : logCount})` : '日志',
    },
    {
      key: 'history', icon: <HistoryOutlined />,
      label: pastCount > 0 ? `历史 (${pastCount})` : '需求历史',
    },
    {
      key: 'cost', icon: <ThunderboltOutlined />,
      label: totalTokens > 0 ? `成本 (${formatTokenCount(totalTokens)})` : '成本',
    },
  ]

  const tabBg = isDark ? '#161b22' : '#ffffff'
  const tabBorder = isDark ? '#30363d' : '#d0d7de'
  const activeColor = isDark ? '#58a6ff' : '#0969da'
  const inactiveColor = isDark ? '#8b949e' : '#656d76'
  const hoverBg = isDark ? '#21262d' : '#f6f8fa'

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* 自定义 Tab Bar */}
      <div style={{
        display: 'flex', alignItems: 'center',
        background: tabBg,
        borderBottom: `1px solid ${tabBorder}`,
        padding: '0 16px',
        flexShrink: 0,
        gap: 0,
      }}>
        {primaryTabs.map(tab => {
          const isActive = (activeTab || 'overview') === tab.key
          return (
            <div
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              style={{
                display: 'flex', alignItems: 'center',
                padding: '10px 16px',
                fontSize: 13,
                fontWeight: isActive ? 500 : 400,
                color: isActive ? activeColor : inactiveColor,
                borderBottom: isActive ? `2px solid ${activeColor}` : '2px solid transparent',
                cursor: 'pointer',
                userSelect: 'none',
                transition: 'color 0.15s, background 0.15s',
                borderRadius: '4px 4px 0 0',
                marginBottom: -1,
              }}
              onMouseEnter={e => { if (!isActive) e.currentTarget.style.background = hoverBg }}
              onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}
            >
              {tab.label}
            </div>
          )
        })}

        {/* 分隔线 */}
        <div style={{ width: 1, height: 16, background: tabBorder, margin: '0 4px', flexShrink: 0 }} />

        {/* 辅助 Tab 直接展开 */}
        {secondaryTabMeta.map(tab => {
          const isActive = (activeTab || 'overview') === tab.key
          return (
            <div
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              style={{
                display: 'flex', alignItems: 'center', gap: 6,
                padding: '10px 16px',
                fontSize: 13,
                fontWeight: isActive ? 500 : 400,
                color: isActive ? activeColor : inactiveColor,
                borderBottom: isActive ? `2px solid ${activeColor}` : '2px solid transparent',
                cursor: 'pointer',
                userSelect: 'none',
                transition: 'color 0.15s, background 0.15s',
                borderRadius: '4px 4px 0 0',
                marginBottom: -1,
                whiteSpace: 'nowrap',
              }}
              onMouseEnter={e => { if (!isActive) e.currentTarget.style.background = hoverBg }}
              onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}
            >
              {tab.icon}
              <span>{tab.label}</span>
            </div>
          )
        })}
      </div>

      {/* Tab 内容区：所有面板始终挂载，active 的才显示 */}
      <div style={{ flex: 1, minHeight: 0, position: 'relative' }}>
        {Object.entries(tabPanels).map(([key, panel]) => (
          <div
            key={key}
            style={{
              position: 'absolute', inset: 0,
              display: (activeTab || 'overview') === key ? 'block' : 'none',
              overflow: 'hidden',
            }}
          >
            {panel}
          </div>
        ))}
      </div>
    </div>
  )
}
