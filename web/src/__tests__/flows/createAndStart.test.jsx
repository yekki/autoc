import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConfigProvider } from 'antd'
import useStore from '../../stores/useStore'
import { EMPTY_STATS, buildResetState } from '../../stores/helpers/constants'

vi.mock('../../services/api', () => ({
  fetchProjects: vi.fn().mockResolvedValue([]),
  createProject: vi.fn(),
  updateProject: vi.fn().mockResolvedValue({}),
  startRun: vi.fn().mockResolvedValue({ session_id: 'test-session' }),
  fetchConfig: vi.fn().mockResolvedValue(null),
  fetchModelConfig: vi.fn().mockResolvedValue(null),
  fetchProjectVersions: vi.fn().mockResolvedValue({ versions: [] }),
  stopRun: vi.fn().mockResolvedValue({}),
  aiAssist: vi.fn(),
}))

vi.mock('../../services/sse', () => ({
  SSEConnection: class {
    constructor() { this.connect = vi.fn(); this.close = vi.fn() }
  },
}))

const api = await import('../../services/api')
const { default: WelcomePage } = await import('../../components/WelcomePage')
const { default: OverviewTab } = await import('../../components/workspace/OverviewTab')

describe('Create project → Input requirement → Start execution flow', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useStore.setState({
      ...buildResetState(),
      theme: 'dark',
      projects: [],
      selectedProjectName: null,
    })
  })

  // ── WelcomePage: 创建项目入口（S-001 v2.1：统一为快速启动面板）──

  it('shows quick start form with launch button in empty state', () => {
    render(<ConfigProvider><WelcomePage /></ConfigProvider>)
    // S-001: 首屏展示快速启动面板，不再单独显示"创建项目"按钮
    expect(screen.getByText('一键启动')).toBeInTheDocument()
    // 兜底链接仍然存在
    expect(screen.getByText('或者先创建空项目，稍后填写需求')).toBeInTheDocument()
  })

  it('clicking fallback link triggers store action to open modal', async () => {
    const user = userEvent.setup()
    render(<ConfigProvider><WelcomePage /></ConfigProvider>)

    await user.click(screen.getByText('或者先创建空项目，稍后填写需求'))
    expect(useStore.getState().createProjectOpen).toBe(true)
  })

  it('shows quick start panel (collapsed) when projects exist', () => {
    useStore.setState({
      projects: [{ name: 'proj1', folder: 'proj1', status: 'idle', tech_stack: [] }],
    })
    render(<ConfigProvider><WelcomePage /></ConfigProvider>)
    // S-001 v2.1: QuickStartPanel 替代了独立的"新建项目"按钮
    expect(screen.getByText('一键启动')).toBeInTheDocument()
  })

  // ── OverviewTab idle 态: 输入需求 → 开始开发 ──

  it('start button is disabled when requirement is empty', () => {
    useStore.setState({
      selectedProjectName: 'my-app',
      projects: [{ name: 'my-app', folder: 'my-app', status: 'idle', tech_stack: [] }],
      isRunning: false,
      executionSummary: null,
      executionRequirement: '',
    })
    render(<ConfigProvider><OverviewTab project={{ status: 'idle', name: 'my-app' }} /></ConfigProvider>)

    const startBtn = screen.getAllByRole('button').find(b => b.textContent.includes('开始开发'))
    expect(startBtn).toBeDisabled()
  })

  it('start button enables after entering requirement', async () => {
    const user = userEvent.setup()
    useStore.setState({
      selectedProjectName: 'my-app',
      projects: [{ name: 'my-app', folder: 'my-app', status: 'idle', tech_stack: [] }],
      isRunning: false,
      executionSummary: null,
      executionRequirement: '',
    })
    render(<ConfigProvider><OverviewTab project={{ status: 'idle', name: 'my-app' }} /></ConfigProvider>)

    const textarea = screen.getByPlaceholderText('描述你想要构建的软件...')
    await user.type(textarea, '做一个 API 服务')

    const startBtn = screen.getAllByRole('button').find(b => b.textContent.includes('开始开发'))
    expect(startBtn).not.toBeDisabled()
  })

  it('full flow: input requirement → click start → calls updateProject + startRun', async () => {
    const user = userEvent.setup()
    useStore.setState({
      selectedProjectName: 'my-app',
      projects: [{ name: 'my-app', folder: 'my-app', status: 'idle', tech_stack: [] }],
      isRunning: false,
      executionSummary: null,
      executionRequirement: '',
      modelConfig: null,
    })
    render(<ConfigProvider><OverviewTab project={{ status: 'idle', name: 'my-app' }} /></ConfigProvider>)

    const textarea = screen.getByPlaceholderText('描述你想要构建的软件...')
    await user.type(textarea, '用 React 做一个待办事项应用')

    const startBtn = screen.getAllByRole('button').find(b => b.textContent.includes('开始开发'))
    await user.click(startBtn)

    await waitFor(() => {
      expect(api.updateProject).toHaveBeenCalledWith('my-app', expect.objectContaining({
        description: '用 React 做一个待办事项应用',
      }))
    })
  })

  it('start button and requirement textarea are visible in idle form', () => {
    useStore.setState({
      selectedProjectName: 'my-app',
      projects: [{ name: 'my-app', folder: 'my-app', status: 'idle', tech_stack: [] }],
      isRunning: false,
      executionSummary: null,
    })
    render(<ConfigProvider><OverviewTab project={{ status: 'idle', name: 'my-app' }} /></ConfigProvider>)
    // "开始开发" 出现在标题和按钮中，使用 getAllByText
    expect(screen.getAllByText('开始开发').length).toBeGreaterThan(0)
    expect(screen.getByPlaceholderText('描述你想要构建的软件...')).toBeInTheDocument()
  })
})
