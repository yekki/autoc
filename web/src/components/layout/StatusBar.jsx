import { useMemo, useState, useEffect } from 'react'
import { Tooltip, Tag, Popover } from 'antd'
import {
  CheckCircleFilled,
  CloseCircleFilled,
  ExclamationCircleFilled,
  LoadingOutlined,
  ApiOutlined,
} from '@ant-design/icons'
import useStore from '../../stores/useStore'
import { fetchCapabilities } from '../../services/api'

const AGENT_LABELS = { coder: 'Coder AI', critique: 'Critique AI', helper: '辅助 AI' }

const HEALTH_MAP = {
  healthy:  { color: '#3fb950', label: '就绪' },
  degraded: { color: '#d29922', label: '部分可用' },
  unhealthy: { color: '#f85149', label: '未就绪' },
}

const CATEGORY_LABELS = { file: '文件', shell: '终端', git: 'Git', quality: '质量' }

// R-018: 默认只显示角色标签 + 状态点，模型名移入 Tooltip
function AgentBadge({ label, provider, model, isDark }) {
  const configured = !!(provider && model)
  const modelShort = model ? model.split('/').pop() : '-'
  const tooltipTitle = configured ? `${label}\n${provider} / ${modelShort}` : `${label}（未配置）`
  return (
    <Tooltip title={tooltipTitle} overlayStyle={{ whiteSpace: 'pre-line' }}>
      <span
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 3,
          padding: '0 5px',
          borderRadius: 3,
          fontSize: 11,
          lineHeight: '18px',
          cursor: 'default',
        }}
      >
        <span style={{
          width: 6, height: 6, borderRadius: '50%', flexShrink: 0,
          background: configured ? '#3fb950' : '#d29922',
          display: 'inline-block',
        }} />
        <span style={{ color: isDark ? '#8b949e' : '#656d76' }}>{label}</span>
      </span>
    </Tooltip>
  )
}

function CapabilitiesPopover({ caps, isDark }) {
  if (!caps) return <span style={{ fontSize: 11, opacity: 0.6 }}>加载中...</span>

  const toolsByCategory = {}
  for (const t of caps.tools?.builtin || []) {
    const cat = t.category || 'other'
    if (!toolsByCategory[cat]) toolsByCategory[cat] = []
    toolsByCategory[cat].push(t)
  }

  const healthInfo = HEALTH_MAP[caps.health] || HEALTH_MAP.unhealthy
  const itemStyle = { fontSize: 11, lineHeight: '20px', display: 'flex', alignItems: 'center', gap: 4 }
  const okDot = <CheckCircleFilled style={{ color: '#3fb950', fontSize: 9 }} />
  const warnDot = <ExclamationCircleFilled style={{ color: '#d29922', fontSize: 9 }} />
  const failDot = <CloseCircleFilled style={{ color: '#f85149', fontSize: 9 }} />
  const pendingDot = <span style={{ width: 7, height: 7, borderRadius: '50%', background: isDark ? '#484f58' : '#afb8c1', display: 'inline-block', flexShrink: 0 }} />

  return (
    <div style={{ width: 260, fontSize: 12 }}>
      <div style={{ fontWeight: 600, marginBottom: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{ width: 8, height: 8, borderRadius: '50%', background: healthInfo.color, display: 'inline-block' }} />
        系统状态：{healthInfo.label}
      </div>

      {/* Docker */}
      <div style={itemStyle}>
        {caps.docker?.available ? okDot : failDot}
        <span>Docker 沙箱</span>
        <span style={{ opacity: 0.5, marginLeft: 'auto' }}>
          {caps.docker?.available ? caps.docker.sandbox_mode : '不可用'}
        </span>
      </div>

      {/* 模型 */}
      <div style={itemStyle}>
        {caps.model_configured ? okDot : failDot}
        <span>LLM 模型</span>
        <span style={{ opacity: 0.5, marginLeft: 'auto' }}>
          {caps.model_configured ? '已配置' : '未配置'}
        </span>
      </div>

      {/* 工具 */}
      <div style={{ borderTop: `1px solid ${isDark ? '#30363d' : '#d0d7de'}`, marginTop: 8, paddingTop: 8 }}>
        <div style={{ fontWeight: 600, marginBottom: 4 }}>
          Agent 工具（{caps.tools?.builtin_count || 0}）
        </div>
        {Object.entries(toolsByCategory).map(([cat, tools]) => (
          <div key={cat} style={{ ...itemStyle, opacity: 0.8 }}>
            <span style={{ fontWeight: 500, minWidth: 32 }}>{CATEGORY_LABELS[cat] || cat}</span>
            <span style={{ opacity: 0.6 }}>
              {tools.map((t) => t.name.replace(/_/g, '_')).join('、')}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function StatusBar() {
  const theme = useStore((s) => s.theme)
  const modelConfig = useStore((s) => s.modelConfig)
  const isRunning = useStore((s) => s.isRunning)
  const currentPhase = useStore((s) => s.currentPhase)
  const isDark = theme === 'dark'

  const [caps, setCaps] = useState(null)

  useEffect(() => {
    fetchCapabilities().then(setCaps).catch(() => {})
    const timer = setInterval(() => {
      fetchCapabilities().then(setCaps).catch(() => {})
    }, 60_000)
    return () => clearInterval(timer)
  }, [])

  const agentModels = useMemo(() => {
    const active = modelConfig?.active || {}
    return Object.entries(AGENT_LABELS).map(([key, label]) => ({
      key,
      label,
      provider: active[key]?.provider || '',
      model: active[key]?.model || '',
    }))
  }, [modelConfig])

  const healthInfo = caps ? (HEALTH_MAP[caps.health] || HEALTH_MAP.unhealthy) : null
  const summaryText = caps
    ? (() => {
        const toolCount = caps.tools?.builtin_count || 0
        const mcpCount = caps.mcp?.server_count || 0
        return mcpCount > 0 ? `${toolCount} 工具 · ${mcpCount} MCP` : `${toolCount} 工具`
      })()
    : ''

  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        padding: '0 16px',
        height: 32,
        fontSize: 11,
        color: isDark ? '#8b949e' : '#656d76',
        borderTop: `1px solid ${isDark ? '#30363d' : '#d0d7de'}`,
        background: isDark ? '#161b22' : '#ffffff',
        flexShrink: 0,
      }}
    >
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
        {agentModels.map((a) => (
          <AgentBadge
            key={a.key}
            label={a.label}
            provider={a.provider}
            model={a.model}
            isDark={isDark}
          />
        ))}
      </span>

      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
        {isRunning && currentPhase && (
          <Tag
            color="processing"
            icon={<LoadingOutlined />}
            style={{ margin: 0, fontSize: 11, lineHeight: '18px', padding: '0 6px' }}
          >
            {currentPhase}
          </Tag>
        )}

        <Popover
          content={<CapabilitiesPopover caps={caps} isDark={isDark} />}
          trigger="click"
          placement="topRight"
        >
          <span
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 4,
              cursor: 'pointer', padding: '0 4px', borderRadius: 3,
              transition: 'background 0.2s',
            }}
            onMouseEnter={(e) => { e.currentTarget.style.background = isDark ? '#21262d' : '#f0f0f0' }}
            onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent' }}
          >
            {healthInfo && (
              <span style={{ width: 7, height: 7, borderRadius: '50%', background: healthInfo.color, display: 'inline-block' }} />
            )}
            <ApiOutlined style={{ fontSize: 11 }} />
            {summaryText && <span>{summaryText}</span>}
          </span>
        </Popover>

        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          {modelConfig ? (
            <>
              <CheckCircleFilled style={{ color: '#3fb950', fontSize: 9 }} />
              在线
            </>
          ) : (
            <>
              <CloseCircleFilled style={{ color: '#f85149', fontSize: 9 }} />
              离线
            </>
          )}
        </span>
      </span>
    </div>
  )
}
