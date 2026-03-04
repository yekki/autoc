import { useState, useEffect, useMemo, useRef } from 'react'
import { Tabs, Badge, Empty, Spin } from 'antd'
import {
  DashboardOutlined, CodeOutlined, GlobalOutlined,
  CodeSandboxOutlined, HistoryOutlined, ThunderboltOutlined,
} from '@ant-design/icons'
import useStore from '../../stores/useStore'
import * as api from '../../services/api'
import PreviewPanel from '../shared/PreviewPanel'
import WebTerminal from '../shared/WebTerminal'
import OverviewTab from './OverviewTab'
import CodeTab from './CodeTab'
import RequirementHistoryTab from './RequirementHistoryTab'
import CostTab from './CostTab'
import { formatTokenCount } from './helpers'

export default function ProjectWorkspace() {
  const theme = useStore(s => s.theme)
  const selectedProjectName = useStore(s => s.selectedProjectName)
  const executionFiles = useStore(s => s.executionFiles)
  const isRunning = useStore(s => s.isRunning)
  const activeTab = useStore(s => s.activeTab)
  const setActiveTab = useStore(s => s.setActiveTab)
  const tokenRuns = useStore(s => s.executionTokenRuns)
  const sessionId = useStore(s => s.sessionId)
  const stats = useStore(s => s.executionStats)
  const executionPreview = useStore(s => s.executionPreview)

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

  const totalTokens = tokenRuns.reduce((s, r) => s + (r.total_tokens || 0), 0) || stats.tokens || 0

  const tabItems = [
    {
      key: 'overview',
      label: (
        <span>
          <DashboardOutlined /> 概览
          {isRunning && <Badge status="processing" style={{ marginLeft: 6 }} />}
        </span>
      ),
      children: <OverviewTab project={project} />,
    },
    {
      key: 'code',
      label: (
        <span>
          <CodeOutlined /> 代码
          {workspaceFiles.length > 0 && <Badge count={workspaceFiles.length} size="small" style={{ marginLeft: 6 }} />}
        </span>
      ),
      children: <CodeTab projectName={selectedProjectName} workspaceFiles={workspaceFiles} />,
    },
    {
      key: 'preview',
      label: (
        <span>
          <GlobalOutlined /> 预览
          {executionPreview?.available && <Badge status="success" style={{ marginLeft: 6 }} />}
        </span>
      ),
      children: (
        <div style={{ height: '100%', padding: 16 }}>
          <PreviewPanel preview={executionPreview} isRunning={isRunning} isDark={isDark} height="100%" />
        </div>
      ),
    },
    {
      key: 'terminal',
      label: <span><CodeSandboxOutlined /> 终端</span>,
      children: (
        <div style={{ height: '100%' }}>
          <WebTerminal wsUrl={terminalWsUrl} height="100%" />
        </div>
      ),
    },
    {
      key: 'history',
      label: (
        <span>
          <HistoryOutlined /> 需求历史
          {(() => {
            const pastCount = tokenRuns.filter(r => r.session_id && r.session_id !== sessionId).length
            return pastCount > 0 && <Badge count={pastCount} size="small" style={{ marginLeft: 6 }} />
          })()}
        </span>
      ),
      children: <RequirementHistoryTab />,
    },
    {
      key: 'cost',
      label: (
        <span>
          <ThunderboltOutlined /> 成本
          {totalTokens > 0 && <Badge count={formatTokenCount(totalTokens)} size="small" style={{ marginLeft: 6 }} />}
        </span>
      ),
      children: <CostTab />,
    },
  ]

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <Tabs
        activeKey={activeTab || 'overview'}
        onChange={setActiveTab}
        items={tabItems}
        destroyOnHidden={false}
        tabBarStyle={{
          margin: 0,
          padding: '0 16px',
          background: isDark ? '#161b22' : '#ffffff',
          borderBottom: `1px solid ${isDark ? '#30363d' : '#d0d7de'}`,
        }}
        tabBarGutter={24}
        className="workspace-tabs"
      />
      <style>{`
        .workspace-tabs { flex: 1; display: flex; flex-direction: column; }
        .workspace-tabs > .ant-tabs-content-holder { flex: 1; min-height: 0; }
        .workspace-tabs .ant-tabs-content { height: 100%; }
        .workspace-tabs .ant-tabs-tabpane { height: 100%; }
      `}</style>
    </div>
  )
}
