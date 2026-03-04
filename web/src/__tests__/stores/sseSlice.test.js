import { describe, it, expect, vi, beforeEach } from 'vitest'
import { create } from 'zustand'
import { createSseSlice } from '../../stores/slices/sseSlice'
import { EMPTY_STATS } from '../../stores/helpers/constants'

function createTestStore(overrides = {}) {
  return create((set, get) => ({
    projects: [{ name: 'proj', folder: 'proj', tech_stack: ['React'] }],
    selectedProjectName: 'proj',
    sessionId: 'sess-1',
    sseConnection: null,
    executionLogs: [],
    executionHistory: [],
    executionStats: { ...EMPTY_STATS },
    executionTaskList: [],
    executionFiles: [],
    newlyCreatedFiles: [],
    executionBugsList: [],
    executionTokenRuns: [],
    executionAgentTokens: null,
    executionPlan: null,
    executionSummary: null,
    executionPreview: null,
    executionRefinerResult: null,
    executionFailure: null,
    planningProgress: null,
    agentThinking: null,
    currentPhase: '',
    currentIteration: { round: 0, maxRounds: 0, iteration: 0, maxIterations: 0 },
    iterationHistory: [],
    isRunning: true,
    activeTab: 'overview',
    fixProgress: { status: 'idle', currentBug: null, current: 0, total: 0, results: [], fixedCount: 0, elapsedSeconds: 0, verified: null },
    executionComplexity: '',
    lastDevSelfTest: null,
    smokeCheckIssues: [],
    deployGateStatus: null,
    lastFailureAnalysis: null,
    lastReflection: null,
    planningAcceptanceResult: null,
    lastPmDecision: null,
    _lastErrorMessage: '',
    fetchProjects: vi.fn(),
    ...overrides,
    ...createSseSlice(set, get),
  }))
}

describe('sseSlice — _handleSSEEvent', () => {
  let store

  beforeEach(() => {
    store = createTestStore()
    vi.clearAllMocks()
  })

  it('logs every event', () => {
    store.getState()._handleSSEEvent({ type: 'sandbox_ready', data: {} })
    expect(store.getState().executionLogs).toHaveLength(1)
    expect(store.getState().executionLogs[0].type).toBe('sandbox_ready')
  })

  it('plan_ready clears planningProgress and updates tech_stack', () => {
    store = createTestStore({
      planningProgress: { step: 'foo', progress: 50, steps: [] },
    })
    store.getState()._handleSSEEvent({
      type: 'plan_ready',
      data: {
        tasks: [{ id: 't1', title: 'Task 1' }],
        tech_stack: ['Vue', 'Express'],
      },
    })
    const state = store.getState()
    expect(state.planningProgress).toBeNull()
    expect(state.executionTaskList).toHaveLength(1)
    const proj = state.projects.find(p => p.name === 'proj')
    expect(proj.tech_stack).toEqual(['Vue', 'Express'])
  })

  it('iteration_start adds to iterationHistory', () => {
    store.getState()._handleSSEEvent({
      type: 'iteration_start', data: { iteration: 1, phase: 'dev' },
    })
    expect(store.getState().iterationHistory).toHaveLength(1)
    expect(store.getState().iterationHistory[0].iteration).toBe(1)
  })

  it('iteration_done updates iteration entry with stats', () => {
    store.getState()._handleSSEEvent({
      type: 'iteration_start', data: { iteration: 1, phase: 'dev' },
    })
    store.getState()._handleSSEEvent({
      type: 'iteration_done', data: {
        iteration: 1, phase: 'dev', success: true,
        tokens_used: 1500, elapsed_seconds: 30,
      },
    })
    const iter = store.getState().iterationHistory[0]
    expect(iter.success).toBe(true)
    expect(iter.tokensUsed).toBe(1500)
  })

  it('file_created appends to newlyCreatedFiles', () => {
    store.getState()._handleSSEEvent({
      type: 'file_created', data: { file: 'index.js' },
    })
    expect(store.getState().newlyCreatedFiles).toContain('index.js')
  })

  it('token_session updates executionTokenRuns', () => {
    store.getState()._handleSSEEvent({
      type: 'token_session',
      data: { total_tokens: 3000, prompt_tokens: 1500, completion_tokens: 1500, agent_tokens: { pm: 1000, dev: 2000 } },
    })
    expect(store.getState().executionTokenRuns).toHaveLength(1)
    expect(store.getState().executionTokenRuns[0].total_tokens).toBe(3000)
  })

  it('preview_ready auto-switches to preview tab when available', () => {
    store.getState()._handleSSEEvent({
      type: 'preview_ready', data: { url: 'http://localhost:8888', available: true },
    })
    expect(store.getState().activeTab).toBe('preview')
    expect(store.getState().executionPreview).toMatchObject({ url: 'http://localhost:8888' })
  })

  it('refiner events accumulate in executionRefinerResult', () => {
    store.getState()._handleSSEEvent({
      type: 'refiner_quality', data: { level: 'medium', score: 60 },
    })
    store.getState()._handleSSEEvent({
      type: 'refiner_enhanced', data: { text: 'improved req' },
    })
    const result = store.getState().executionRefinerResult
    expect(result.quality).toEqual({ level: 'medium', score: 60 })
    expect(result.enhanced).toEqual({ text: 'improved req' })
  })

  it('done event finalizes execution', () => {
    store = createTestStore({
      isRunning: true,
      executionTaskList: [
        { id: 't1', status: 'in_progress', passes: false },
        { id: 't2', status: 'completed', passes: true },
      ],
    })

    store.getState()._handleSSEEvent({
      type: 'done', data: { success: true, total_tokens: 5000, elapsed_seconds: 120 },
    })

    const state = store.getState()
    expect(state.isRunning).toBe(false)
    expect(state.executionTaskList[0].status).toBe('completed')
    expect(state.executionStats.tokens).toBe(5000)
    expect(state.fetchProjects).toHaveBeenCalled()
  })

  it('quick_fix_start initializes fixProgress', () => {
    store.getState()._handleSSEEvent({
      type: 'quick_fix_start',
      data: { bug_count: 3, bugs: [{ id: 'b1', title: 'NPE' }] },
    })
    const fp = store.getState().fixProgress
    expect(fp.status).toBe('fixing')
    expect(fp.total).toBe(3)
    expect(fp.results).toHaveLength(1)
  })

  it('bug_fix_progress updates fix tracking', () => {
    store = createTestStore({
      fixProgress: {
        status: 'fixing', currentBug: null, current: 0, total: 2,
        results: [{ id: 'b1', title: 'NPE', status: 'pending' }],
        fixedCount: 0, elapsedSeconds: 0, verified: null,
      },
    })
    store.getState()._handleSSEEvent({
      type: 'bug_fix_progress',
      data: { bug_id: 'b1', bug_title: 'NPE', status: 'fixed', current: 1, total: 2 },
    })
    const fp = store.getState().fixProgress
    expect(fp.currentBug.id).toBe('b1')
    expect(fp.results[0].status).toBe('fixed')
  })

  it('thinking_content stores agent thinking', () => {
    store.getState()._handleSSEEvent({
      type: 'thinking_content',
      agent: 'planner',
      data: { content: '正在分析依赖关系...', iteration: 1 },
    })
    expect(store.getState().agentThinking.content).toBe('正在分析依赖关系...')
  })
})

describe('sseSlice — _handleSSEDisconnect', () => {
  it('sets failure state and cleans up in-progress tasks', () => {
    const store = createTestStore({
      isRunning: true,
      executionTaskList: [{ id: 't1', status: 'in_progress' }],
    })

    store.getState()._handleSSEDisconnect()

    const state = store.getState()
    expect(state.isRunning).toBe(false)
    expect(state.executionFailure.reason).toBe('与后端的连接中断')
    expect(state.executionTaskList[0].status).toBe('failed')
    expect(state.fetchProjects).toHaveBeenCalled()
  })
})
