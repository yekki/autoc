import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConfigProvider } from 'antd'
import StatusBar from '../../components/layout/StatusBar'
import useStore from '../../stores/useStore'

vi.mock('../../services/api', () => ({
  fetchCapabilities: vi.fn(),
  fetchProjects: vi.fn().mockResolvedValue([]),
  fetchConfig: vi.fn().mockResolvedValue(null),
  fetchModelConfig: vi.fn().mockResolvedValue(null),
}))

vi.mock('../../services/sse', () => ({
  SSEConnection: class { constructor() { this.connect = vi.fn(); this.close = vi.fn() } },
}))

const api = await import('../../services/api')

const MOCK_CAPS = {
  health: 'healthy',
  docker: { available: true, sandbox_mode: 'project' },
  model_configured: true,
  mcp: {
    enabled: true, health: 'healthy', server_count: 3,
    servers: [
      { name: 'filesystem', status: 'connected' },
      { name: 'browser', status: 'connected' },
      { name: 'context7', status: 'pending' },
    ],
  },
  tools: {
    builtin_count: 11,
    builtin: [
      { name: 'read_file', category: 'file' },
      { name: 'write_file', category: 'file' },
      { name: 'execute_command', category: 'shell' },
      { name: 'git_diff', category: 'git' },
      { name: 'format_code', category: 'quality' },
    ],
  },
}

function renderStatusBar() {
  return render(<ConfigProvider><StatusBar /></ConfigProvider>)
}

describe('StatusBar', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useStore.setState({
      theme: 'dark',
      modelConfig: {
        active: {
          coder: { provider: 'zhipu', model: 'glm-4.7' },
          critique: { provider: 'zhipu', model: 'qwen3-max' },
          helper: { provider: 'zhipu', model: 'qwen-plus' },
        },
      },
      isRunning: false,
      currentPhase: '',
    })
    api.fetchCapabilities.mockResolvedValue(MOCK_CAPS)
  })

  it('renders agent badges with role labels (R-018: model names in tooltip only)', () => {
    renderStatusBar()

    // R-018: 角色标签保持可见
    expect(screen.getByText('Coder AI')).toBeInTheDocument()
    expect(screen.getByText('Critique AI')).toBeInTheDocument()
    expect(screen.getByText('辅助 AI')).toBeInTheDocument()

    // R-018: 模型名移入 Tooltip，不在 DOM 可见区域显示
    expect(screen.queryByText('glm-4.7')).not.toBeInTheDocument()
    expect(screen.queryByText('qwen3-max')).not.toBeInTheDocument()
    expect(screen.queryByText('qwen-plus')).not.toBeInTheDocument()
  })

  it('shows online status when model config is set', () => {
    renderStatusBar()
    expect(screen.getByText('在线')).toBeInTheDocument()
  })

  it('shows offline status when no model config', () => {
    useStore.setState({ modelConfig: null })
    renderStatusBar()
    expect(screen.getByText('离线')).toBeInTheDocument()
  })

  it('shows tool count and MCP count after capabilities load', async () => {
    renderStatusBar()

    await waitFor(() => {
      expect(screen.getByText('11 工具 · 3 MCP')).toBeInTheDocument()
    })
  })

  it('shows health indicator dot for system status', async () => {
    renderStatusBar()

    await waitFor(() => {
      expect(screen.getByText('11 工具 · 3 MCP')).toBeInTheDocument()
    })
  })

  it('shows running phase tag when executing', () => {
    useStore.setState({ isRunning: true, currentPhase: '代码生成' })
    renderStatusBar()
    expect(screen.getByText('代码生成')).toBeInTheDocument()
  })

  it('opens capabilities popover on click', async () => {
    const user = userEvent.setup()
    renderStatusBar()

    await waitFor(() => {
      expect(screen.getByText('11 工具 · 3 MCP')).toBeInTheDocument()
    })

    const statusTrigger = screen.getByText('11 工具 · 3 MCP').closest('span')
    await user.click(statusTrigger)

    await waitFor(() => {
      expect(screen.getByText(/系统状态：就绪/)).toBeInTheDocument()
    })

    expect(screen.getByText('Docker 沙箱')).toBeInTheDocument()
    expect(screen.getByText('LLM 模型')).toBeInTheDocument()
    expect(screen.getByText('已配置')).toBeInTheDocument()
    expect(screen.getByText('project')).toBeInTheDocument()
  })

  it('shows agent tool categories in popover', async () => {
    const user = userEvent.setup()
    renderStatusBar()

    await waitFor(() => screen.getByText('11 工具 · 3 MCP'))
    await user.click(screen.getByText('11 工具 · 3 MCP').closest('span'))

    await waitFor(() => {
      expect(screen.getByText('Agent 工具（11）')).toBeInTheDocument()
    })
  })

  it('shows agent tools grouped by category', async () => {
    const user = userEvent.setup()
    renderStatusBar()

    await waitFor(() => screen.getByText('11 工具 · 3 MCP'))
    await user.click(screen.getByText('11 工具 · 3 MCP').closest('span'))

    await waitFor(() => {
      expect(screen.getByText('Agent 工具（11）')).toBeInTheDocument()
    })
  })

  it('shows unconfigured agent badge (R-018: simplified display)', () => {
    useStore.setState({
      modelConfig: {
        active: {
          coder: { provider: 'zhipu', model: 'glm-4.7' },
          critique: { provider: '', model: '' },
          helper: { provider: '', model: '' },
        },
      },
    })
    renderStatusBar()
    // R-018: 所有角色标签仍可见，无论是否已配置
    expect(screen.getByText('Coder AI')).toBeInTheDocument()
    expect(screen.getByText('Critique AI')).toBeInTheDocument()
    expect(screen.getByText('辅助 AI')).toBeInTheDocument()
  })

  it('handles capabilities loading failure gracefully', async () => {
    api.fetchCapabilities.mockRejectedValue(new Error('fail'))
    renderStatusBar()

    expect(screen.getByText('Coder AI')).toBeInTheDocument()
  })

  it('shows degraded health for partially available services', async () => {
    api.fetchCapabilities.mockResolvedValue({
      ...MOCK_CAPS,
      health: 'degraded',
      mcp: { enabled: true, health: 'degraded', server_count: 3, servers: [] },
    })
    const user = userEvent.setup()
    renderStatusBar()

    await waitFor(() => screen.getByText('11 工具 · 3 MCP'))
    await user.click(screen.getByText('11 工具 · 3 MCP').closest('span'))

    await waitFor(() => {
      expect(screen.getByText(/系统状态：部分可用/)).toBeInTheDocument()
    })
  })
})
