/**
 * 核心用户动线集成测试
 *
 * 模拟完整的用户旅程：
 * 1. 创建项目 → 切换到工作台
 * 2. 输入需求 → 启动执行
 * 3. SSE 事件流 → 实时更新状态
 * 4. 执行完成 → 结果展示
 * 5. 历史回放 → 状态恢复
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { create } from 'zustand'
import { EMPTY_STATS, buildResetState } from '../../stores/helpers/constants'
import { createProjectSlice } from '../../stores/slices/projectSlice'
import { createExecutionSlice } from '../../stores/slices/executionSlice'
import { createSseSlice } from '../../stores/slices/sseSlice'

vi.mock('../../services/api', () => ({
  fetchProjects: vi.fn(),
  fetchProject: vi.fn(),
  createProject: vi.fn(),
  deleteProject: vi.fn(),
  batchDeleteProjects: vi.fn(),
  updateProject: vi.fn(),
  fetchConfig: vi.fn(),
  fetchModelConfig: vi.fn(),
  startRun: vi.fn(),
  stopRun: vi.fn().mockResolvedValue({}),
  resumeProject: vi.fn(),
  quickFixBugs: vi.fn(),
  redefineProject: vi.fn(),
  addFeature: vi.fn(),
  fetchSessions: vi.fn(),
  fetchSessionEvents: vi.fn(),
}))

vi.mock('../../services/sse', () => ({
  SSEConnection: class {
    constructor(sessionId, handlers) {
      this.connect = vi.fn()
      this.close = vi.fn()
      this._handlers = handlers
    }
  },
}))

vi.mock('../../stores/slices/historySlice', () => ({
  invalidateHistoryLoad: vi.fn(),
  createHistorySlice: () => ({
    loadProjectHistory: vi.fn(),
  }),
}))

const api = await import('../../services/api')

function createFullStore() {
  return create((set, get) => ({
    projects: [],
    selectedProjectName: null,
    viewMode: 'welcome',
    activeTab: 'overview',
    selectedTaskId: null,
    sessionId: null,
    sseConnection: null,
    executionRequirement: '',
    executionLogs: [],
    executionHistory: [],
    executionStats: { ...EMPTY_STATS },
    executionPlan: null,
    executionFiles: [],
    newlyCreatedFiles: [],
    executionSummary: null,
    executionBugsList: [],
    executionTokenRuns: [],
    executionAgentTokens: null,
    executionTaskList: [],
    executionPreview: null,
    executionRefinerResult: null,
    executionFailure: null,
    isRunning: false,
    currentPhase: '',
    currentIteration: { round: 0, maxRounds: 0, iteration: 0, maxIterations: 0 },
    iterationHistory: [],
    selectedIteration: null,
    sandboxStatus: { step: '', message: '', progress: 0, ready: false },
    planningProgress: null,
    agentThinking: null,
    executionComplexity: '',
    lastDevSelfTest: null,
    smokeCheckIssues: [],
    deployGateStatus: null,
    lastFailureAnalysis: null,
    lastReflection: null,
    planningAcceptanceResult: null,
    lastPmDecision: null,
    _lastErrorMessage: '',
    fixProgress: { status: 'idle', currentBug: null, current: 0, total: 0, results: [], fixedCount: 0, elapsedSeconds: 0, verified: null },
    aiAssistTokens: { total: 0, calls: 0, records: [] },
    createProjectOpen: false,
    editProjectOpen: false,
    editProjectTarget: null,
    theme: 'dark',
    collapsedSections: {},
    systemConfig: null,
    modelConfig: null,
    settingsOpen: false,
    setActiveTab: (tab) => set({ activeTab: tab }),
    _archiveCurrentLogs: () => {
      const s = get()
      return [...s.executionHistory]
    },
    ...createProjectSlice(set, get),
    ...createExecutionSlice(set, get),
    ...createSseSlice(set, get),
    loadProjectHistory: vi.fn(),
  }))
}

describe('用户动线: 创建项目 → 执行 → SSE 事件 → 完成', () => {
  let store

  beforeEach(() => {
    store = createFullStore()
    vi.clearAllMocks()
    localStorage.clear()
  })

  it('完整动线：创建项目 → 启动执行 → 接收 SSE 事件 → 执行完成', async () => {
    // ── Step 1: 创建项目 ──
    api.createProject.mockResolvedValue({ name: 'todo-app' })
    api.fetchProjects.mockResolvedValue([
      { name: 'todo-app', folder: 'todo-app', tech_stack: ['React', 'Express'] },
    ])

    await store.getState().createProject({ name: 'todo-app', folder: 'todo-app' })

    let state = store.getState()
    expect(state.selectedProjectName).toBe('todo-app')
    expect(state.viewMode).toBe('workspace')
    expect(state.activeTab).toBe('overview')
    expect(state.projects).toHaveLength(1)

    // ── Step 2: 启动执行 ──
    api.startRun.mockResolvedValue({ session_id: 'sess-001' })

    await store.getState().startExecution('开发一个带登录功能的待办应用')

    state = store.getState()
    expect(state.isRunning).toBe(true)
    expect(state.sessionId).toBe('sess-001')
    expect(state.executionRequirement).toBe('开发一个带登录功能的待办应用')

    // ── Step 3: SSE 事件流 ──
    const handleEvent = store.getState()._handleSSEEvent

    // 3a: 沙箱准备
    handleEvent({ type: 'sandbox_preparing', data: { step: 'pull', message: '拉取镜像', progress: 30 } })
    expect(store.getState().sandboxStatus.progress).toBe(30)

    handleEvent({ type: 'sandbox_ready', data: { message: '沙箱就绪' } })
    expect(store.getState().sandboxStatus.ready).toBe(true)

    // 3b: PM 分析
    handleEvent({ type: 'planning_progress', data: { step: 'analyze', message: '分析需求', progress: 50 } })
    expect(store.getState().planningProgress.step).toBe('analyze')

    // 3c: 计划就绪
    handleEvent({
      type: 'plan_ready',
      data: {
        tasks: [
          { id: 'task-1', title: '实现用户认证', description: 'JWT + bcrypt' },
          { id: 'task-2', title: '实现待办 CRUD', description: 'REST API' },
          { id: 'task-3', title: '实现前端界面', description: 'React components' },
        ],
        tech_stack: ['React', 'Express', 'MongoDB'],
      },
    })

    state = store.getState()
    expect(state.executionTaskList).toHaveLength(3)
    expect(state.executionStats.tasks.total).toBe(3)
    expect(state.planningProgress).toBeNull()

    // 3d: 开发迭代
    handleEvent({ type: 'iteration_start', data: { iteration: 1, phase: 'dev' } })
    expect(store.getState().iterationHistory).toHaveLength(1)

    handleEvent({ type: 'task_start', data: { task_id: 'task-1' } })
    expect(store.getState().executionTaskList.find(t => t.id === 'task-1').status).toBe('in_progress')

    handleEvent({ type: 'file_created', data: { file: 'src/auth.js' } })
    handleEvent({ type: 'file_created', data: { file: 'src/routes/users.js' } })
    expect(store.getState().executionFiles).toHaveLength(2)
    expect(store.getState().newlyCreatedFiles).toHaveLength(2)

    handleEvent({ type: 'task_complete', data: { task_id: 'task-1' } })
    expect(store.getState().executionTaskList.find(t => t.id === 'task-1').status).toBe('completed')
    expect(store.getState().executionStats.tasks.completed).toBe(1)

    // 3e: 任务验证
    handleEvent({ type: 'task_verified', data: { task_id: 'task-1', passes: true } })
    expect(store.getState().executionTaskList.find(t => t.id === 'task-1').passes).toBe(true)
    expect(store.getState().executionStats.tasks.verified).toBe(1)

    // 继续完成 task-2 和 task-3
    handleEvent({ type: 'task_start', data: { task_id: 'task-2' } })
    handleEvent({ type: 'task_complete', data: { task_id: 'task-2' } })
    handleEvent({ type: 'task_verified', data: { task_id: 'task-2', passes: true } })

    handleEvent({ type: 'task_start', data: { task_id: 'task-3' } })
    handleEvent({ type: 'file_created', data: { file: 'src/App.jsx' } })
    handleEvent({ type: 'task_complete', data: { task_id: 'task-3' } })
    handleEvent({ type: 'task_verified', data: { task_id: 'task-3', passes: true } })

    expect(store.getState().executionStats.tasks.completed).toBe(3)
    expect(store.getState().executionStats.tasks.verified).toBe(3)

    // 3f: 测试结果
    handleEvent({
      type: 'test_result',
      data: { tests_passed: 12, tests_total: 12, bug_count: 0 },
    })
    expect(store.getState().executionStats.tests).toEqual({ passed: 12, total: 12 })

    // 3g: Token 统计
    handleEvent({
      type: 'token_session',
      data: {
        total_tokens: 15000, prompt_tokens: 8000, completion_tokens: 7000,
        agent_tokens: { pm: 3000, dev: 10000, test: 2000 },
      },
    })
    expect(store.getState().executionAgentTokens.dev).toBe(10000)
    expect(store.getState().executionStats.tokens).toBe(15000)

    // 3h: 迭代完成
    handleEvent({
      type: 'iteration_done',
      data: { iteration: 1, phase: 'dev', success: true, tokens_used: 15000, elapsed_seconds: 180 },
    })

    // 3i: 预览就绪
    handleEvent({
      type: 'preview_ready',
      data: { url: 'http://localhost:8888', available: true },
    })
    expect(store.getState().executionPreview.url).toBe('http://localhost:8888')
    expect(store.getState().activeTab).toBe('preview')

    // ── Step 4: 执行完成 ──
    api.fetchProjects.mockResolvedValue([
      { name: 'todo-app', folder: 'todo-app', status: 'completed', tech_stack: ['React', 'Express', 'MongoDB'] },
    ])

    handleEvent({
      type: 'done',
      data: {
        success: true, total_tokens: 15000, elapsed_seconds: 180,
        tasks_total: 3, tasks_completed: 3, tasks_verified: 3,
        tests_total: 12, tests_passed: 12,
      },
    })

    state = store.getState()
    expect(state.isRunning).toBe(false)
    expect(state.executionStats.tokens).toBe(15000)
    expect(state.executionTaskList.every(t => t.status !== 'in_progress')).toBe(true)
    // done 事件会触发 fetchProjects 刷新项目列表
    expect(api.fetchProjects).toHaveBeenCalled()
  })

  it('动线：执行失败 → 失败信息展示 → 快速修复', async () => {
    // 设置运行中状态
    api.createProject.mockResolvedValue({})
    api.fetchProjects.mockResolvedValue([{ name: 'proj', folder: 'proj' }])
    await store.getState().createProject({ name: 'proj' })

    api.startRun.mockResolvedValue({ session_id: 'sess-f' })
    await store.getState().startExecution('build it')

    const handleEvent = store.getState()._handleSSEEvent

    // 执行中发现 bug
    handleEvent({
      type: 'plan_ready',
      data: { tasks: [{ id: 't1', title: 'API' }] },
    })
    handleEvent({ type: 'task_start', data: { task_id: 't1' } })
    handleEvent({ type: 'task_complete', data: { task_id: 't1' } })
    handleEvent({
      type: 'test_result',
      data: {
        tests_passed: 3, tests_total: 5, bug_count: 2,
        bugs: [
          { id: 'b1', title: 'NPE in handler', severity: 'high' },
          { id: 'b2', title: 'Missing validation', severity: 'medium' },
        ],
      },
    })

    expect(store.getState().executionBugsList).toHaveLength(2)
    expect(store.getState().executionStats.bugs).toBe(2)

    // 执行失败完成
    handleEvent({
      type: 'done', data: { success: false, failure_reason: '测试未全部通过' },
    })

    expect(store.getState().isRunning).toBe(false)
    expect(store.getState().executionFailure.reason).toBe('测试未全部通过')

    // 快速修复
    api.quickFixBugs.mockResolvedValue({ session_id: 'sess-fix' })

    await store.getState().quickFixBugs('proj')

    const fixState = store.getState()
    expect(fixState.isRunning).toBe(true)
    expect(fixState.fixProgress.status).toBe('fixing')
    expect(fixState.sessionId).toBe('sess-fix')
  })

  it('动线：切换项目 → 状态重置', async () => {
    // 先有执行状态
    store.setState({
      projects: [
        { name: 'A', folder: 'A' },
        { name: 'B', folder: 'B' },
      ],
      selectedProjectName: 'A',
      viewMode: 'workspace',
      executionTaskList: [{ id: 't1', status: 'completed' }],
      executionStats: { ...EMPTY_STATS, tasks: { total: 5, completed: 3, verified: 2 } },
    })

    // 切换到项目 B
    store.getState().selectProject('B')

    const state = store.getState()
    expect(state.selectedProjectName).toBe('B')
    expect(state.executionTaskList).toEqual([])
    expect(state.executionStats.tasks.total).toBe(0)
    expect(state.loadProjectHistory).toHaveBeenCalledWith('B')
  })

  it('动线：返回仪表盘 → 状态清理', () => {
    store.setState({
      selectedProjectName: 'A',
      viewMode: 'workspace',
    })

    store.getState().backToAllProjects()

    expect(store.getState().selectedProjectName).toBeNull()
    expect(store.getState().viewMode).toBe('welcome')
    expect(localStorage.getItem('autoc-selected-project')).toBeNull()
  })

  it('动线：SSE 断线 → 错误展示 → 重试', async () => {
    api.startRun.mockResolvedValue({ session_id: 'sess-d' })
    store.setState({ selectedProjectName: 'proj', projects: [{ name: 'proj', folder: 'proj' }] })

    await store.getState().startExecution('req')
    expect(store.getState().isRunning).toBe(true)

    // SSE 断线
    store.getState()._handleSSEDisconnect()

    const state = store.getState()
    expect(state.isRunning).toBe(false)
    expect(state.executionFailure.reason).toBe('与后端的连接中断')
    expect(state.executionFailure.suggestions).toContain('检查后端服务是否运行中')

    // 重试
    api.startRun.mockResolvedValue({ session_id: 'sess-retry' })
    await store.getState().retryExecution()
    expect(store.getState().isRunning).toBe(true)
    expect(store.getState().sessionId).toBe('sess-retry')
  })
})
