import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
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
  refineRequirement: vi.fn(),
  startRun: vi.fn(),
  updateProject: vi.fn().mockResolvedValue({}),
}))

vi.mock('../../services/sse', () => ({
  SSEConnection: class { constructor() { this.connect = vi.fn(); this.close = vi.fn() } },
}))

function renderOverviewTab(props = {}) {
  return render(
    <ConfigProvider>
      <OverviewTab project={props.project || null} />
    </ConfigProvider>
  )
}

describe('OverviewTab', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useStore.setState({
      theme: 'dark',
      isRunning: false,
      selectedProjectName: 'test-proj',
      projects: [{ name: 'test-proj', folder: 'test-proj', status: 'idle', tech_stack: [] }],
      executionRequirement: '',
      executionTaskList: [],
      executionStats: { ...EMPTY_STATS },
      executionSummary: null,
      executionFailure: null,
      executionBugsList: [],
      executionTokenRuns: [],
      executionAgentTokens: null,
      executionPreview: null,
      currentPhase: '',
      sandboxStatus: { step: '', message: '', progress: 0, ready: false },
      planningProgress: null,
      agentThinking: null,
      executionComplexity: '',
      lastDevSelfTest: null,
      smokeCheckIssues: [],
      deployGateStatus: null,
      planningAcceptanceResult: null,
      lastPmDecision: null,
      fixProgress: { status: 'idle', currentBug: null, current: 0, total: 0, results: [], fixedCount: 0, elapsedSeconds: 0, verified: null },
      modelConfig: null,
      collapsedSections: {},
    })
  })

  // ── Idle 态 ──

  describe('idle state', () => {
    it('renders "开始开发" form with input and run button', () => {
      renderOverviewTab({ project: { status: 'idle' } })

      expect(screen.getAllByText('开始开发').length).toBeGreaterThan(0)
      expect(screen.getByPlaceholderText('描述你想要构建的软件...')).toBeInTheDocument()

      const buttons = screen.getAllByRole('button')
      const runBtn = buttons.find(b => b.textContent.includes('开始开发'))
      expect(runBtn).toBeDisabled()
    })

    it('enables run button when requirement is typed', async () => {
      const user = userEvent.setup()
      renderOverviewTab({ project: { status: 'idle' } })

      const textarea = screen.getByPlaceholderText('描述你想要构建的软件...')
      await user.type(textarea, '做一个待办应用')

      const buttons = screen.getAllByRole('button')
      const runBtn = buttons.find(b => b.textContent.includes('开始开发'))
      expect(runBtn).not.toBeDisabled()
    })
  })

  // ── Running 态 ──

  describe('running state', () => {
    beforeEach(() => {
      useStore.setState({
        isRunning: true,
        executionRequirement: '做一个待办应用',
        projects: [{ name: 'test-proj', status: 'developing', tech_stack: ['React'] }],
      })
    })

    it('shows "执行中" indicator', () => {
      renderOverviewTab()
      expect(screen.getByText('执行中')).toBeInTheDocument()
    })

    it('shows stop button in running state', () => {
      renderOverviewTab()
      expect(screen.getByText('停止')).toBeInTheDocument()
    })

    it('shows sandbox preparation progress', () => {
      useStore.setState({
        sandboxStatus: { step: 'pull_image', message: '拉取镜像中...', progress: 40, ready: false },
      })
      renderOverviewTab()
      expect(screen.getByText('准备沙箱环境')).toBeInTheDocument()
      expect(screen.getByText('拉取镜像中...')).toBeInTheDocument()
    })

    it('shows PM analysis steps when sandbox is ready', () => {
      useStore.setState({
        sandboxStatus: { step: 'ready', message: '', progress: 100, ready: true },
        planningProgress: {
          step: 'analyze', progress: 50, message: '分析需求',
          steps: [
            { step: 'prepare', message: '准备分析', completed: true },
            { step: 'analyze', message: '分析需求', completed: false },
          ],
        },
      })
      renderOverviewTab()
      expect(screen.getByText('准备分析')).toBeInTheDocument()
      expect(screen.getByText('分析需求')).toBeInTheDocument()
    })

    it('shows task progress when tasks exist', () => {
      useStore.setState({
        sandboxStatus: { step: 'ready', message: '', progress: 100, ready: true },
        executionTaskList: [
          { id: 't1', title: 'Build API', status: 'completed', passes: true },
          { id: 't2', title: 'Build UI', status: 'in_progress', passes: false },
          { id: 't3', title: 'Tests', status: 'pending', passes: false },
        ],
        executionStats: { ...EMPTY_STATS, tasks: { total: 3, completed: 1, verified: 1 }, tokens: 5000 },
        currentPhase: 'dev',
      })
      renderOverviewTab()
      // 活跃任务的标题显示在执行卡片中
      expect(screen.getByText(/Build UI/)).toBeInTheDocument()
      // 进度格式 [2/3]
      expect(screen.getByText(/\[2\/3\]/)).toBeInTheDocument()
    })

    it('shows complexity badge when assessed', () => {
      useStore.setState({ executionComplexity: 'complex' })
      renderOverviewTab()
      expect(screen.getByText('复杂')).toBeInTheDocument()
    })

    it('shows agent thinking indicator when agent is thinking', () => {
      useStore.setState({
        agentThinking: { agent: 'planner', content: '正在分析登录需求的依赖关系...', iteration: 1, timestamp: Date.now() },
      })
      renderOverviewTab()
      // AgentActivityPanel 显示 "planner 思考中" 标题（内容默认折叠）
      expect(screen.getByText(/思考中/)).toBeInTheDocument()
    })

    it('shows dev self-test result', () => {
      useStore.setState({
        lastDevSelfTest: { taskId: 't1', passed: false, results: [] },
        sandboxStatus: { step: 'ready', message: '', progress: 100, ready: true },
        executionTaskList: [{ id: 't1', title: 'Task', status: 'in_progress', passes: false }],
      })
      renderOverviewTab()
      expect(screen.getByText('开发者自测未通过')).toBeInTheDocument()
    })
  })

  // ── Result 态 ──

  describe('result state (execution completed)', () => {
    beforeEach(() => {
      useStore.setState({
        isRunning: false,
        executionRequirement: '做一个待办应用',
        executionSummary: {
          success: true, elapsed_seconds: 120, total_tokens: 15000,
          tasks_completed: 3, tasks_total: 3,
        },
        executionTaskList: [
          { id: 't1', title: 'Build API', status: 'verified', passes: true },
          { id: 't2', title: 'Build UI', status: 'verified', passes: true },
          { id: 't3', title: 'Tests', status: 'verified', passes: true },
        ],
        executionStats: {
          ...EMPTY_STATS,
          tasks: { total: 3, completed: 3, verified: 3 },
          tokens: 15000, elapsed: 120,
        },
        projects: [{ name: 'test-proj', status: 'completed', tech_stack: ['React'] }],
      })
    })

    it('shows success result with task count', () => {
      renderOverviewTab()
      expect(screen.getByText('3/3 个任务通过')).toBeInTheDocument()
    })

    it('shows task list with verified icons', () => {
      renderOverviewTab()
      expect(screen.getByText('t1')).toBeInTheDocument()
      expect(screen.getByText('Build API')).toBeInTheDocument()
    })

    it('shows retry button on failure', () => {
      useStore.setState({
        executionSummary: { success: false, elapsed_seconds: 60 },
        executionTaskList: [
          { id: 't1', title: 'API', status: 'verified', passes: true },
          { id: 't2', title: 'UI', status: 'failed', passes: false },
        ],
        executionStats: { ...EMPTY_STATS, tasks: { total: 2, completed: 1, verified: 1 } },
      })
      renderOverviewTab()
      expect(screen.getByText('重试')).toBeInTheDocument()
    })

    it('shows "新需求" button for non-idle projects with history', () => {
      useStore.setState({
        projects: [{ name: 'test-proj', status: 'completed', tech_stack: [] }],
      })
      renderOverviewTab({ project: { status: 'completed', name: 'test-proj' } })
      expect(screen.getByText('新需求')).toBeInTheDocument()
    })
  })

  // ── Failure 态（断连/错误，无 summary）──

  describe('failure state (disconnection/error)', () => {
    it('shows failure card with reason and suggestions', () => {
      useStore.setState({
        executionRequirement: 'req',
        executionFailure: {
          reason: '与后端的连接中断',
          suggestions: ['检查后端服务是否运行中', '刷新页面后点击继续执行'],
        },
        executionTaskList: [{ id: 't1', title: 'Task', status: 'failed', passes: false }],
        projects: [{ name: 'test-proj', status: 'incomplete', tech_stack: [] }],
      })
      renderOverviewTab({ project: { status: 'incomplete', name: 'test-proj' } })

      expect(screen.getByText('与后端的连接中断')).toBeInTheDocument()
      expect(screen.getByText(/检查后端服务是否运行中/)).toBeInTheDocument()
    })

    it('shows retry button in failure state when tasks exist', () => {
      useStore.setState({
        executionRequirement: 'req',
        executionFailure: { reason: '超时', suggestions: [] },
        executionTaskList: [{ id: 't1', title: 'Task', status: 'failed', passes: false }],
        projects: [{ name: 'test-proj', status: 'incomplete', tech_stack: [] }],
      })
      renderOverviewTab({ project: { status: 'incomplete', name: 'test-proj' } })
      expect(screen.getByText('重试')).toBeInTheDocument()
    })
  })

  // ── Bug 区 ──

  describe('bug section', () => {
    it('shows bug list with fix buttons when bugs exist', () => {
      useStore.setState({
        executionRequirement: 'req',
        executionSummary: { success: false },
        executionBugsList: [
          { id: 'b1', title: 'NPE in handler', severity: 'high', description: 'Null pointer' },
          { id: 'b2', title: 'Missing validation', severity: 'medium', description: 'No input check' },
        ],
        executionTaskList: [{ id: 't1', status: 'failed', passes: false }],
        executionStats: { ...EMPTY_STATS, bugs: 2 },
        projects: [{ name: 'test-proj', status: 'incomplete', tech_stack: [] }],
      })
      renderOverviewTab()

      expect(screen.getByText('NPE in handler')).toBeInTheDocument()
      expect(screen.getByText('Missing validation')).toBeInTheDocument()
      expect(screen.getByText('全部修复')).toBeInTheDocument()

      const fixButtons = screen.getAllByText('修复')
      expect(fixButtons.length).toBeGreaterThanOrEqual(2)
    })
  })
})
