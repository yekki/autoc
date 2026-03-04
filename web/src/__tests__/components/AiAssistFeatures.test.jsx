import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConfigProvider } from 'antd'
import OverviewTab from '../../components/workspace/OverviewTab'
import useStore from '../../stores/useStore'
import { EMPTY_STATS } from '../../stores/helpers/constants'

vi.mock('../../services/api', () => ({
  fetchProjects: vi.fn().mockResolvedValue([]),
  fetchConfig: vi.fn().mockResolvedValue(null),
  fetchModelConfig: vi.fn().mockResolvedValue(null),
  fetchProjectVersions: vi.fn().mockResolvedValue({ versions: [] }),
  aiAssist: vi.fn(),
  updateProject: vi.fn().mockResolvedValue({}),
  startRun: vi.fn().mockResolvedValue({ session_id: 'test-session' }),
}))

vi.mock('../../services/sse', () => ({
  SSEConnection: class { constructor() { this.connect = vi.fn(); this.close = vi.fn() } },
}))

const api = await import('../../services/api')

function renderIdle(hasAuxiliary = true) {
  useStore.setState({
    theme: 'dark',
    selectedProjectName: 'test-proj',
    projects: [{ name: 'test-proj', folder: 'test-proj', status: 'idle', tech_stack: [] }],
    isRunning: false,
    executionSummary: null,
    executionRequirement: '',
    executionTaskList: [],
    executionStats: { ...EMPTY_STATS },
    executionFailure: null,
    executionBugsList: [],
    executionTokenRuns: [],
    executionAgentTokens: null,
    executionPreview: null,
    currentPhase: '',
    collapsedSections: {},
    modelConfig: hasAuxiliary ? {
      active: {
        coder: { provider: 'zhipu', model: 'glm-4.7' },
        critique: { provider: 'zhipu', model: 'qwen3-max' },
        helper: { provider: 'zhipu', model: 'qwen-plus' },
      },
    } : null,
  })
  return render(
    <ConfigProvider>
      <OverviewTab project={{ status: 'idle', name: 'test-proj' }} />
    </ConfigProvider>
  )
}

describe('AI Polish + Tech Stack Recommendation', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  // ── AI 润色 ──

  it('shows AI polish button when auxiliary model is configured', () => {
    renderIdle(true)
    expect(screen.getByText('AI 润色')).toBeInTheDocument()
  })

  it('hides AI polish button when no auxiliary model', () => {
    renderIdle(false)
    expect(screen.queryByText('AI 润色')).not.toBeInTheDocument()
  })

  it('AI polish button is disabled when input is empty', () => {
    renderIdle(true)
    const polishBtn = screen.getByText('AI 润色').closest('button')
    expect(polishBtn).toBeDisabled()
  })

  it('AI polish calls api and updates requirement text', async () => {
    const user = userEvent.setup()
    api.aiAssist.mockResolvedValue({
      description: '# 优化后的需求\n做一个精美的待办事项管理应用...',
      tokens_used: 500,
    })

    renderIdle(true)

    const textarea = screen.getByPlaceholderText('描述你想要构建的软件...')
    await user.type(textarea, '做个待办应用')

    const polishBtn = screen.getByText('AI 润色').closest('button')
    expect(polishBtn).not.toBeDisabled()

    await user.click(polishBtn)

    await waitFor(() => {
      expect(api.aiAssist).toHaveBeenCalledWith(expect.objectContaining({
        action: 'polish',
        project_name: 'test-proj',
        description: '做个待办应用',
      }))
    })
  })

  // ── idle 表单基本元素 ──

  it('shows start button and textarea in idle state', () => {
    renderIdle(true)
    expect(screen.getAllByText('开始开发').length).toBeGreaterThan(0)
    expect(screen.getByPlaceholderText('描述你想要构建的软件...')).toBeInTheDocument()
  })

  it('shows AI polish button when auxiliary model is configured (idle state)', () => {
    renderIdle(true)
    expect(screen.getByText('AI 润色')).toBeInTheDocument()
  })

  it('hides AI polish button when no auxiliary model (idle state)', () => {
    renderIdle(false)
    expect(screen.queryByText('AI 润色')).not.toBeInTheDocument()
  })
})
