import { describe, it, expect, vi, beforeEach } from 'vitest'
import { create } from 'zustand'
import { createExecutionSlice } from '../../stores/slices/executionSlice'
import { EMPTY_STATS } from '../../stores/helpers/constants'

vi.mock('../../services/api', () => ({
  startRun: vi.fn(),
  stopRun: vi.fn().mockResolvedValue({}),
  resumeProject: vi.fn(),
  quickFixBugs: vi.fn(),
  redefineProject: vi.fn(),
  addFeature: vi.fn(),
}))

vi.mock('../../services/sse', () => ({
  SSEConnection: class {
    constructor() { this.connect = vi.fn(); this.close = vi.fn() }
  },
}))

const api = await import('../../services/api')

function createTestStore(overrides = {}) {
  return create((set, get) => ({
    projects: [],
    selectedProjectName: 'test-proj',
    viewMode: 'workspace',
    activeTab: 'overview',
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
    fixProgress: { status: 'idle', currentBug: null, current: 0, total: 0, results: [], fixedCount: 0, elapsedSeconds: 0, verified: null },
    _handleSSEEvent: vi.fn(),
    _handleSSEDisconnect: vi.fn(),
    _archiveCurrentLogs: vi.fn().mockReturnValue([]),
    ...overrides,
    ...createExecutionSlice(set, get),
  }))
}

describe('executionSlice', () => {
  let store

  beforeEach(() => {
    store = createTestStore()
    vi.clearAllMocks()
  })

  describe('startExecution', () => {
    it('throws if no project selected', async () => {
      store = createTestStore({ selectedProjectName: null })
      await expect(store.getState().startExecution('Build a todo app'))
        .rejects.toThrow('请先选择项目')
    })

    it('resets state, calls API, sets sessionId and SSE', async () => {
      api.startRun.mockResolvedValue({ session_id: 'sess-123' })

      await store.getState().startExecution('Build a todo app')

      const state = store.getState()
      expect(state.isRunning).toBe(true)
      expect(state.sessionId).toBe('sess-123')
      expect(state.executionRequirement).toBe('Build a todo app')
      expect(api.startRun).toHaveBeenCalledWith({
        requirement: 'Build a todo app',
        project_name: 'test-proj',
        tech_stack: undefined,
      })
    })

    it('passes tech_stack from project metadata', async () => {
      store = createTestStore({
        projects: [{ name: 'test-proj', folder: 'test-proj', tech_stack: ['React', 'Node.js'] }],
      })
      api.startRun.mockResolvedValue({ session_id: 'sess-1' })

      await store.getState().startExecution('req')

      expect(api.startRun).toHaveBeenCalledWith(
        expect.objectContaining({ tech_stack: ['React', 'Node.js'] })
      )
    })

    it('stops run if execution was cancelled before SSE setup', async () => {
      api.stopRun.mockResolvedValue({})
      api.startRun.mockImplementation(async () => {
        store.setState({ isRunning: false })
        return { session_id: 'cancelled' }
      })

      await store.getState().startExecution('req')
      expect(api.stopRun).toHaveBeenCalledWith('cancelled')
    })
  })

  describe('stopExecution', () => {
    it('stops API, closes SSE, marks in-progress tasks as failed', async () => {
      const mockSSE = { close: vi.fn() }
      store = createTestStore({
        sessionId: 'sess-1',
        sseConnection: mockSSE,
        isRunning: true,
        executionTaskList: [
          { id: 't1', status: 'in_progress' },
          { id: 't2', status: 'completed' },
        ],
        executionStats: { ...EMPTY_STATS, tokens: 100 },
        executionAgentTokens: { _prompt_tokens: 50, _completion_tokens: 50 },
      })

      await store.getState().stopExecution()

      const state = store.getState()
      expect(state.isRunning).toBe(false)
      expect(state.sseConnection).toBeNull()
      expect(mockSSE.close).toHaveBeenCalled()
      expect(api.stopRun).toHaveBeenCalledWith('sess-1')
      expect(state.executionTaskList[0].status).toBe('failed')
      expect(state.executionTaskList[1].status).toBe('completed')
    })

    it('saves partial token record on stop', async () => {
      store = createTestStore({
        sessionId: 'sess-1',
        isRunning: true,
        executionStats: { ...EMPTY_STATS, tokens: 500, elapsed: 30 },
        executionAgentTokens: { _prompt_tokens: 200, _completion_tokens: 300, _cached_tokens: 0 },
        executionTokenRuns: [],
        executionRequirement: 'some req',
        executionTaskList: [],
      })

      await store.getState().stopExecution()

      const runs = store.getState().executionTokenRuns
      expect(runs).toHaveLength(1)
      expect(runs[0].status).toBe('aborted')
      expect(runs[0].total_tokens).toBe(500)
    })
  })

  describe('retryExecution', () => {
    it('throws if no requirement to retry', async () => {
      store = createTestStore({ executionRequirement: '' })
      await expect(store.getState().retryExecution())
        .rejects.toThrow('没有可重试的需求')
    })

    it('retries with previous requirement', async () => {
      store = createTestStore({ executionRequirement: 'old req' })
      api.startRun.mockResolvedValue({ session_id: 'retry-1' })

      await store.getState().retryExecution()

      expect(api.startRun).toHaveBeenCalledWith(
        expect.objectContaining({ requirement: 'old req' })
      )
      expect(store.getState().sessionId).toBe('retry-1')
    })
  })

  describe('reviseProject (backward compat)', () => {
    it('calls redefineProject with cleanWorkspace=true', async () => {
      api.redefineProject.mockResolvedValue({ session_id: 'r-1' })
      await store.getState().reviseProject('test-proj', 'new req', { cleanWorkspace: true })
      expect(api.redefineProject).toHaveBeenCalled()
    })

    it('calls addFeature with cleanWorkspace=false', async () => {
      api.addFeature.mockResolvedValue({ session_id: 'a-1' })
      await store.getState().reviseProject('test-proj', 'tweaked req', { cleanWorkspace: false })
      expect(api.addFeature).toHaveBeenCalled()
    })
  })
})
