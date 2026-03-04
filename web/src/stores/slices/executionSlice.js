import * as api from '../../services/api'
import { SSEConnection } from '../../services/sse'
import { buildResetState } from '../helpers/constants'

export const createExecutionSlice = (set, get) => ({
  _updateProjectStatus: (projectFolder, status) => {
    const projects = get().projects.map(p =>
      p.folder === projectFolder ? { ...p, status } : p
    )
    set({ projects })
  },

  // S-001: 首屏一步启动 — 创建项目并立即执行，不需要先选中项目
  quickStart: async ({ projectName, displayName = '', requirement }) => {
    if (!projectName?.trim()) throw new Error('项目名称不能为空')
    if (!requirement?.trim()) throw new Error('请输入需求描述')

    get().sseConnection?.close()
    // 先切换到工作区并设置 selectedProject，再触发 run
    localStorage.setItem('autoc-selected-project', projectName)
    localStorage.setItem('autoc-view-mode', 'workspace')
    set(buildResetState({
      sseConnection: null,
      isRunning: true,
      selectedProjectName: projectName,
      viewMode: 'workspace',
      activeTab: 'overview',
      executionRequirement: requirement,
    }))

    const result = await api.quickStart({ project_name: projectName, display_name: displayName || projectName, requirement })
    const sessionId = result.session_id

    if (!get().isRunning) {
      api.stopRun(sessionId).catch(() => {})
      return result
    }

    set({ sessionId })

    const sse = new SSEConnection(sessionId, {
      onEvent: (event) => get()._handleSSEEvent(event),
      onError: () => get()._handleSSEDisconnect(),
    })
    sse.connect()
    set({ sseConnection: sse })

    // 后台刷新项目列表，使新项目出现在列表中
    api.fetchProjects().then(projects => set({ projects })).catch(() => {})

    return result
  },

  startExecution: async (requirement) => {
    const { selectedProjectName } = get()
    if (!selectedProjectName) throw new Error('请先选择项目')

    get().sseConnection?.close()
    set(buildResetState({
      sseConnection: null,
      isRunning: true,
      executionRequirement: requirement,
      viewMode: 'workspace',
      activeTab: 'overview',
    }))
    get()._updateProjectStatus(selectedProjectName, 'planning')

    const result = await api.startRun({
      requirement,
      project_name: selectedProjectName,
    })

    const sessionId = result.session_id
    if (!get().isRunning) {
      api.stopRun(sessionId).catch(() => {})
      return result
    }

    set({ sessionId })

    const sse = new SSEConnection(sessionId, {
      onEvent: (event) => get()._handleSSEEvent(event),
      onError: () => get()._handleSSEDisconnect(),
    })
    sse.connect()
    set({ sseConnection: sse })

    return result
  },

  retryExecution: async (options = {}) => {
    const requirement = get().executionRequirement
    if (!requirement) throw new Error('没有可重试的需求')
    const { selectedProjectName } = get()
    if (!selectedProjectName) throw new Error('请先选择项目')

    get().sseConnection?.close()
    set(buildResetState({
      sseConnection: null,
      isRunning: true,
      viewMode: 'workspace',
      activeTab: 'overview',
      executionRequirement: requirement,
    }))

    const result = await api.startRun({
      requirement,
      project_name: selectedProjectName,
      clean: options.clean || false,
    })

    const sessionId = result.session_id
    if (!get().isRunning) {
      api.stopRun(sessionId).catch(() => {})
      return result
    }

    set({ sessionId })

    const sse = new SSEConnection(sessionId, {
      onEvent: (event) => get()._handleSSEEvent(event),
      onError: () => get()._handleSSEDisconnect(),
    })
    sse.connect()
    set({ sseConnection: sse })

    return result
  },

  stopExecution: async () => {
    const { sessionId, sseConnection } = get()
    // 先关闭 SSE 连接，防止 done 事件与后续状态更新竞态
    sseConnection?.close()
    set({ sseConnection: null })
    if (sessionId) {
      await api.stopRun(sessionId).catch(() => {})
    }
    const state = get()
    const cleanedTaskList = state.executionTaskList.map((t) =>
      t.status === 'in_progress' ? { ...t, status: 'failed' } : t
    )

    const patch = {
      isRunning: false,
      sseConnection: null,
      executionTaskList: cleanedTaskList,
      currentPhase: '',
      planningProgress: null,
      agentThinking: null,
    }

    // 保存部分 Token 记录，避免手动停止后成本数据丢失
    const partialTokens = state.executionStats?.tokens || 0
    if (sessionId && partialTokens > 0) {
      const entry = {
        session_id: sessionId,
        total_tokens: partialTokens,
        prompt_tokens: state.executionAgentTokens?._prompt_tokens || 0,
        completion_tokens: state.executionAgentTokens?._completion_tokens || 0,
        cached_tokens: state.executionAgentTokens?._cached_tokens || 0,
        elapsed_seconds: state.executionStats?.elapsed || 0,
        success: false,
        timestamp: new Date().toISOString(),
        agent_tokens: state.executionAgentTokens || null,
        requirement: state.executionRequirement || '',
        status: 'aborted',
      }
      const existing = state.executionTokenRuns.filter(r => r.session_id !== sessionId)
      patch.executionTokenRuns = [entry, ...existing]
    }

    set(patch)
  },

  resumeProject: async (projectName) => {
    const state = get()
    state.sseConnection?.close()

    const archivedHistory = get()._archiveCurrentLogs('resume_prev')

    set({
      executionLogs: [],
      executionBugsList: [],
      executionSummary: null,
      executionPreview: null,
      executionFailure: null,
      executionAgentTokens: null,
      executionTaskList: [],
      isRunning: true,
      viewMode: 'workspace',
      activeTab: 'overview',
      selectedProjectName: projectName,
      executionHistory: archivedHistory,
      currentPhase: '',
      executionStats: { ...state.executionStats, elapsed: 0, tokens: 0 },
      iterationHistory: [],
      selectedIteration: null,
      sandboxStatus: { step: '', message: '', progress: 0, ready: false },
      planningProgress: null,
    })
    get()._updateProjectStatus(projectName, 'developing')

    const result = await api.resumeProject(projectName)
    const sessionId = result.session_id
    if (!get().isRunning) {
      api.stopRun(sessionId).catch(() => {})
      return result
    }

    set({ sessionId })

    const sse = new SSEConnection(sessionId, {
      onEvent: (event) => get()._handleSSEEvent(event),
      onError: () => get()._handleSSEDisconnect(),
    })
    sse.connect()
    set({ sseConnection: sse })

    return result
  },

  quickFixBugs: async (projectName, { bugIds, bugTitles } = {}) => {
    const state = get()
    state.sseConnection?.close()

    const allBugs = state.executionBugsList || []
    let bugsPayload
    if (bugTitles?.length) {
      const titleSet = new Set(bugTitles)
      bugsPayload = allBugs.filter((b) => titleSet.has(b.title))
    } else if (!bugIds?.length) {
      bugsPayload = allBugs
    }

    const archivedHistory = get()._archiveCurrentLogs('quick_fix_prev')

    const targetBugs = bugsPayload || allBugs
    set({
      executionLogs: [],
      executionPreview: null,
      executionFailure: null,
      executionAgentTokens: null,
      isRunning: true,
      viewMode: 'workspace',
      activeTab: 'overview',
      selectedProjectName: projectName,
      executionHistory: archivedHistory,
      currentPhase: '',
      executionStats: { ...state.executionStats, elapsed: 0, tokens: 0 },
      iterationHistory: [],
      selectedIteration: null,
      sandboxStatus: { step: '', message: '', progress: 0, ready: false },
      planningProgress: null,
      fixProgress: {
        status: 'fixing',
        currentBug: null,
        current: 0,
        total: targetBugs.length,
        results: targetBugs.map((b) => ({ id: b.id || b.title, title: b.title, status: 'pending' })),
        fixedCount: 0,
        elapsedSeconds: 0,
        verified: null,
      },
    })

    const result = await api.quickFixBugs(projectName, {
      bugIds,
      bugTitles,
      bugs: bugsPayload?.length ? bugsPayload : undefined,
    })
    const sessionId = result.session_id
    if (!get().isRunning) {
      api.stopRun(sessionId).catch(() => {})
      return result
    }

    set({ sessionId })

    const sse = new SSEConnection(sessionId, {
      onEvent: (event) => get()._handleSSEEvent(event),
      onError: () => get()._handleSSEDisconnect(),
    })
    sse.connect()
    set({ sseConnection: sse })

    return result
  },

  _archiveCurrentLogs: (archiveType) => {
    const state = get()
    const history = [...state.executionHistory]
    if (state.executionLogs.length > 0) {
      const prevIndex = history.length + 1
      const firstLog = state.executionLogs[0]
      const lastTokenRun = state.executionTokenRuns[0]
      // archiveType 由调用方传入（如 'resume_prev'/'quick_fix_prev'），
      // 回退到从 firstLog.type 推断，再回退到 'run'
      const logType = archiveType || (
        firstLog?.type === 'resume_start' ? 'resume'
            : firstLog?.type === 'quick_fix_start' ? 'quick_fix'
            : 'run'
      )
      history.unshift({
        index: prevIndex,
        type: logType,
        startedAt: firstLog?.timestamp || '',
        tokens: lastTokenRun?.total_tokens || 0,
        success: state.executionSummary?.success ?? null,
        summary: state.executionSummary,
        logs: state.executionLogs,
        isLatest: false,
      })
    }
    return history
  },

  redefineProject: async (projectName, requirement) => {
    const state = get()
    state.sseConnection?.close()

    set(buildResetState({
      isRunning: true,
      viewMode: 'workspace',
      activeTab: 'overview',
      selectedProjectName: projectName,
      executionRequirement: requirement,
    }))
    get()._updateProjectStatus(projectName, 'planning')

    const result = await api.redefineProject(projectName, { requirement })
    const sessionId = result.session_id
    if (!get().isRunning) {
      api.stopRun(sessionId).catch(() => {})
      return result
    }

    set({ sessionId })
    const sse = new SSEConnection(sessionId, {
      onEvent: (event) => get()._handleSSEEvent(event),
      onError: () => get()._handleSSEDisconnect(),
    })
    sse.connect()
    set({ sseConnection: sse })
    return result
  },

  addFeature: async (projectName, requirement) => {
    const state = get()
    state.sseConnection?.close()

    const archivedHistory = get()._archiveCurrentLogs('add_feature_prev')

    set({
      executionLogs: [],
      executionBugsList: [],
      executionSummary: null,
      executionPreview: null,
      executionFailure: null,
      executionAgentTokens: null,
      executionTaskList: [],
      executionPlan: null,
      executionPlanMd: '',
      newlyCreatedFiles: [],
      agentThinking: null,
      isRunning: true,
      viewMode: 'workspace',
      activeTab: 'overview',
      selectedProjectName: projectName,
      executionHistory: archivedHistory,
      currentPhase: '',
      executionStats: { ...state.executionStats, elapsed: 0, tokens: 0 },
      iterationHistory: [],
      selectedIteration: null,
      sandboxStatus: { step: '', message: '', progress: 0, ready: false },
      planningProgress: null,
    })
    get()._updateProjectStatus(projectName, 'planning')

    const result = await api.addFeature(projectName, { requirement })
    const sessionId = result.session_id
    if (!get().isRunning) {
      api.stopRun(sessionId).catch(() => {})
      return result
    }

    set({ sessionId })
    const sse = new SSEConnection(sessionId, {
      onEvent: (event) => get()._handleSSEEvent(event),
      onError: () => get()._handleSSEDisconnect(),
    })
    sse.connect()
    set({ sseConnection: sse })
    return result
  },

})
