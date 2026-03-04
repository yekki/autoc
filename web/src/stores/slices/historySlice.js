import * as api from '../../services/api'
import { SSEConnection } from '../../services/sse'
import { EMPTY_STATS } from '../helpers/constants'
import {
  applyEvent, buildEventContext,
  resolvePhase, KNOWN_PHASES, PHASE_AGENT_MAP,
} from '../helpers/eventProcessor'

const STATUS_NORMALIZE = {
  pending: 'pending', in_progress: 'in_progress',
  completed: 'completed', failed: 'failed', blocked: 'failed',
  done: 'completed', success: 'completed', verified: 'verified',
}

let _loadVersion = 0

export function invalidateHistoryLoad() { _loadVersion++ }

// ── 辅助函数（模块级，不依赖 Zustand store）────────────────────────────────

function _buildTaskList(tasks) {
  return tasks.map((t) => ({
    id: t.id,
    title: t.title || t.id,
    description: t.description || '',
    status: t.passes ? 'verified' : (STATUS_NORMALIZE[t.status] || 'pending'),
    feature_tag: t.feature_tag || '',
    files: t.files || [],
    verification_steps: t.verification_steps || [],
    passes: t.passes || false,
    priority: t.priority ?? null,
    verification_notes: t.verification_notes || '',
    assignee: t.assignee || '',
  }))
}

function _buildFilesFromDB(tasks) {
  const arr = []
  for (const t of tasks) {
    for (const f of (t.files || [])) {
      if (f && !arr.includes(f)) arr.push(f)
    }
  }
  return arr
}

function _buildDevSessionMap(dev_sessions) {
  const devSessionMap = new Map()
  const unmatchedDevSessions = []
  for (const ds of dev_sessions) {
    if (ds.session_id) devSessionMap.set(ds.session_id, ds)
    else unmatchedDevSessions.push(ds)
  }
  const sortedDevSessions = dev_sessions
    .sort((a, b) => (b.timestamp || '').localeCompare(a.timestamp || ''))
  return { devSessionMap, unmatchedDevSessions, sortedDevSessions, lastDevSession: sortedDevSessions[0] || null }
}

function _buildInitialUpdates({ tasks, filesFromDB, sortedDevSessions, lastDevSession, project_plan, plan_md, metadata, projectName, ai_assist_stats, isLive, getState }) {
  const totalTasks = tasks.length
  const completedTasks = tasks.filter((t) => t.passes || t.status === 'completed').length
  const taskList = _buildTaskList(tasks)
  const elapsed = lastDevSession?.elapsed_seconds || 0
  const tokens = lastDevSession?.total_tokens ?? 0

  const stats = {
    tasks: { total: totalTasks, completed: completedTasks, verified: completedTasks },
    tests: { passed: 0, total: 0 },
    bugs: 0, files: filesFromDB.length, tokens, elapsed,
  }

  const planResolved = project_plan || (tasks.length > 0 ? {
    project_name: projectName,
    architecture: metadata.tech_stack?.join(' + ') || '',
    tech_stack: metadata.tech_stack || [],
    tasks: tasks.map((t) => ({
      id: t.id, title: t.title || t.id, description: t.description || '',
      assignee: t.assignee || '', feature_tag: t.feature_tag || '',
      passes: t.passes, files: t.files || [],
      verification_steps: t.verification_steps || [],
    })),
  } : null)

  const summaryResolved = lastDevSession ? {
    success: !!lastDevSession.success,
    elapsed_seconds: lastDevSession.elapsed_seconds || 0,
    total_tokens: lastDevSession.total_tokens || tokens,
    tasks_completed: lastDevSession.tasks_completed || completedTasks,
    tasks_total: lastDevSession.tasks_total || totalTasks,
    files: filesFromDB,
  } : totalTasks > 0 ? {
    success: completedTasks === totalTasks && totalTasks > 0,
    elapsed_seconds: 0,
    total_tokens: tokens,
    tasks_completed: completedTasks,
    tasks_total: totalTasks,
    files: filesFromDB,
  } : null

  return {
    executionStats: isLive ? getState().executionStats : stats,
    executionTaskList: isLive ? getState().executionTaskList : taskList,
    executionPlan: isLive ? (getState().executionPlan || planResolved) : planResolved,
    executionFiles: isLive ? getState().executionFiles : filesFromDB,
    executionSummary: isLive ? getState().executionSummary : summaryResolved,
    executionLogs: isLive ? getState().executionLogs : [],
    executionHistory: isLive ? getState().executionHistory : [],
    executionBugsList: isLive ? getState().executionBugsList : [],
    executionTokenRuns: isLive ? getState().executionTokenRuns : sortedDevSessions,
    executionRequirement: metadata.description || lastDevSession?.requirement || '',
    executionAgentTokens: isLive ? getState().executionAgentTokens : (lastDevSession?.agent_tokens || null),
    executionPlanMd: isLive ? getState().executionPlanMd : (plan_md || ''),
    iterationHistory: isLive ? getState().iterationHistory : [],
    aiAssistTokens: ai_assist_stats
      ? { total: ai_assist_stats.total_tokens || 0, calls: ai_assist_stats.call_count || 0, records: ai_assist_stats.records || [] }
      : getState().aiAssistTokens,
  }
}

function _mergeGlobalSessions({ projectSessions, devSessionMap, unmatchedDevSessions, isLive, updates, projectName }) {
  if (projectSessions.length === 0) return

  const usedUnmatched = new Set()
  const mergedRuns = projectSessions.map((gs) => {
    let ds = devSessionMap.get(gs.session_id)
    if (!ds && unmatchedDevSessions.length > 0) {
      const gsTime = gs.started_at ? gs.started_at * 1000 : 0
      for (let i = 0; i < unmatchedDevSessions.length; i++) {
        if (usedUnmatched.has(i)) continue
        const uds = unmatchedDevSessions[i]
        const udsTime = uds.timestamp ? new Date(uds.timestamp).getTime() : 0
        const reqMatch = uds.requirement && gs.requirement
          && gs.requirement.includes(uds.requirement.replace(/^\[|\]$/g, ''))
        const timeClose = gsTime && udsTime && Math.abs(gsTime - udsTime) < 300_000
        if (reqMatch && timeClose) { ds = uds; usedUnmatched.add(i); break }
      }
    }
    return {
      session_id: gs.session_id,
      requirement: gs.requirement || '',
      status: gs.status,
      failure_reason: ds?.failure_reason || '',
      notes: ds?.notes || '',
      timestamp: gs.started_at ? new Date(gs.started_at * 1000).toISOString() : '',
      started_at: gs.started_at,
      ended_at: gs.ended_at,
      total_tokens: ds?.total_tokens || 0,
      prompt_tokens: ds?.prompt_tokens || ds?.agent_tokens?._prompt_tokens || 0,
      completion_tokens: ds?.completion_tokens || ds?.agent_tokens?._completion_tokens || 0,
      cached_tokens: ds?.cached_tokens || ds?.agent_tokens?._cached_tokens || 0,
      tasks_completed: ds?.tasks_completed || 0,
      tasks_total: ds?.tasks_total || 0,
      elapsed_seconds: ds?.elapsed_seconds
        || (gs.ended_at && gs.started_at ? gs.ended_at - gs.started_at : 0),
      success: ds ? !!ds.success : gs.status === 'completed',
      isRunning: gs.status === 'running',
      agent_tokens: ds?.agent_tokens || null,
      tech_stack: ds?.tech_stack || [],
      source: gs.source,
      event_count: gs.event_count || 0,
      has_events: gs.has_events,
    }
  })

  if (!isLive) updates.executionTokenRuns = mergedRuns

  const latestReq = projectSessions[0]?.requirement
  if (!updates.executionRequirement && latestReq) updates.executionRequirement = latestReq

  if (!isLive) {
    updates.executionHistory = mergedRuns.map((s, idx) => {
      const reqLabel = s.requirement || ''
      const opType = reqLabel.startsWith('[resume]') ? 'resume'
        : reqLabel.startsWith('[quick-fix]') ? 'quick_fix'
        : reqLabel.startsWith('[revise]') ? 'revise'
        : 'run'
      return {
        index: mergedRuns.length - idx, type: opType,
        startedAt: s.started_at ? new Date(s.started_at * 1000).toLocaleTimeString() : '',
        date: s.started_at ? new Date(s.started_at * 1000).toLocaleDateString() : '',
        tokens: s.total_tokens || 0, success: s.success, status: s.status,
        failure_reason: s.failure_reason || '',
        agent_tokens: s.agent_tokens || null,
        summary: {
          tasks_completed: s.tasks_completed || 0, tasks_total: s.tasks_total || 0,
          elapsed_seconds: s.elapsed_seconds || 0, total_tokens: s.total_tokens || 0,
          agent_tokens: s.agent_tokens || null,
        },
        logs: [], isLatest: idx === 0,
      }
    })
  }
}

function _collectEventActivities(currentIter, evt, currentAgent) {
  if (evt.type === 'tool_call') {
    currentIter.activities = currentIter.activities || []
    currentIter.activities.push({ type: 'tool_call', agent: currentAgent, tool: evt.data?.tool || '', args: evt.data?.args || {} })
  }
  if (evt.type === 'file_created') {
    currentIter.filesChanged = currentIter.filesChanged || []
    const fp = evt.data?.file || evt.data?.path || ''
    if (fp && !currentIter.filesChanged.includes(fp)) currentIter.filesChanged.push(fp)
  }
  if (evt.type === 'agent_log') {
    currentIter.agentLogs = currentIter.agentLogs || []
    currentIter.agentLogs.push({ agent: evt.agent || currentAgent, message: evt.data?.message || '' })
  }
  if (evt.type === 'task_verified') {
    currentIter.taskVerified = { taskId: evt.data?.task_id || '', passes: evt.data?.passes || false }
  }
  if (evt.type === 'task_regression') {
    currentIter.taskRegressions = currentIter.taskRegressions || []
    currentIter.taskRegressions.push({ taskId: evt.data?.task_id || '', reason: evt.data?.reason || '' })
  }
  if (evt.type === 'test_result') {
    currentIter.testResult = {
      passed: evt.data?.passed ?? 0,
      total: evt.data?.total ?? 0,
      bugs: evt.data?.bugs || [],
    }
  }
}

function _replayEventsToUpdates(events, updates) {
  const restoredIterations = []
  let currentIter = null
  let currentAgent = ''

  for (const evt of events) {
    const ctx = buildEventContext(updates)
    const eventUpdates = applyEvent(evt.type, evt.data, ctx)
    Object.assign(updates, eventUpdates)

    if (evt.agent) currentAgent = evt.agent
    if (currentIter) _collectEventActivities(currentIter, evt, currentAgent)

    if (evt.type === 'phase_start') {
      let phase = resolvePhase(evt.data?.phase)
      if (!KNOWN_PHASES.has(phase)) phase = resolvePhase(evt.data?.title) || phase || 'planning'
      currentIter = { iteration: restoredIterations.length + 1, phase, success: null, storyTitle: evt.data?.title || '', tokensUsed: 0 }
    }
    if (evt.type === 'iteration_done') {
      const iterPhase = evt.data?.phase?.toLowerCase?.() || ''
      if (!currentIter) currentIter = { iteration: restoredIterations.length + 1, phase: iterPhase || 'dev', success: null, storyTitle: '', tokensUsed: 0 }
      if (iterPhase) currentIter.phase = iterPhase
      currentIter.success = evt.data?.success ?? true
      currentIter.error = evt.data?.error || ''
      currentIter.tokensUsed = evt.data?.tokens_used || 0
      currentIter.elapsedSeconds = evt.data?.elapsed_seconds || 0
      currentIter.storyTitle = evt.data?.story_title || currentIter.storyTitle
      currentIter.storyId = evt.data?.story_id || ''
      currentIter.bugs = evt.data?.bugs || []
      restoredIterations.push(currentIter)
      currentIter = null
    }
  }
  if (currentIter) restoredIterations.push(currentIter)
  return restoredIterations
}

function _backfillIterationTokens(restoredIterations, updates) {
  const agentTokens = updates.executionSummary?.agent_tokens || updates.executionStats?.agent_tokens || null
  if (!agentTokens || restoredIterations.length === 0) return
  for (const iter of restoredIterations) {
    if (!iter.tokensUsed) {
      const mapping = PHASE_AGENT_MAP[iter.phase]
      const keys = Array.isArray(mapping) ? mapping : (mapping ? [mapping] : [])
      const matched = keys.find(k => agentTokens[k])
      if (matched) iter.tokensUsed = agentTokens[matched]
    }
  }
}

function _recalcStatsAfterReplay(updates) {
  const replayedTasks = updates.executionTaskList
  if (replayedTasks.length === 0) return
  const rCompleted = replayedTasks.filter((t) => t.status === 'completed' || t.status === 'verified').length
  const rVerified = replayedTasks.filter((t) => t.passes).length
  const rTotal = replayedTasks.length
  updates.executionStats = { ...updates.executionStats, tasks: { completed: rCompleted, total: rTotal, verified: rVerified } }
  if (!updates.executionSummary) {
    updates.executionSummary = {
      success: rVerified === rTotal && rTotal > 0,
      elapsed_seconds: updates.executionStats.elapsed || 0,
      total_tokens: updates.executionStats.tokens || 0,
      tasks_completed: rCompleted, tasks_total: rTotal,
      tasks_verified: rVerified,
      files: updates.executionFiles,
    }
  }
}

function _buildSyntheticIterations(lastDevSession, filesFromDB) {
  if (!lastDevSession?.agent_tokens) return []
  const at = lastDevSession.agent_tokens
  const atHelper = at?.helper || 0
  const atDev = at?.coder || 0
  const atTest = at?.critique || 0
  if (!(atHelper || atDev || atTest)) return []

  const sessionOk = !!lastDevSession.success
  const tc = lastDevSession.tasks_completed || 0
  const tt = lastDevSession.tasks_total || 0
  const dbReason = lastDevSession.failure_reason || ''
  const phases = [...(atHelper ? ['helper'] : []), ...(atDev ? ['dev'] : []), ...(atTest ? ['test'] : [])]
  const lastPhase = phases[phases.length - 1]

  const buildError = (phase, isLastPhase) => {
    if (sessionOk || !isLastPhase) return ''
    if (dbReason) return dbReason
    if (phase === 'plan') return '规划阶段异常终止'
    if (phase === 'dev') {
      if (tc === 0 && filesFromDB.length > 0) return `生成了 ${filesFromDB.length} 个文件，但 ${tt} 个任务均未完成（仍为 pending 状态）`
      if (tc === 0) return `${tt} 个任务均未完成`
      return `仅完成 ${tc}/${tt} 个任务`
    }
    if (phase === 'test') return `测试未通过（${tc}/${tt} 任务完成）`
    return '执行未通过'
  }

  const syntheticIters = []
  let iterNum = 1
  if (atHelper) syntheticIters.push({ iteration: iterNum++, phase: 'plan', success: lastPhase === 'helper' ? sessionOk : true, storyTitle: '', tokensUsed: atHelper, elapsedSeconds: 0, filesChanged: [], error: buildError('plan', lastPhase === 'helper') })
  if (atDev) syntheticIters.push({ iteration: iterNum++, phase: 'dev', success: lastPhase === 'dev' ? sessionOk : true, storyTitle: '', tokensUsed: atDev, elapsedSeconds: lastDevSession.elapsed_seconds || 0, filesChanged: filesFromDB, error: buildError('dev', lastPhase === 'dev') })
  if (atTest) syntheticIters.push({ iteration: iterNum++, phase: 'test', success: sessionOk, storyTitle: '', tokensUsed: atTest, elapsedSeconds: 0, filesChanged: [], error: buildError('test', true) })
  return syntheticIters
}

// ── Slice ─────────────────────────────────────────────────────────────────────

export const createHistorySlice = (set, get) => ({
  loadProjectHistory: async (projectName) => {
    const myVersion = ++_loadVersion
    try {
      const project = await api.fetchProject(projectName)
      if (!project || _loadVersion !== myVersion) return

      const { tasks = [], metadata = {}, dev_sessions = [], project_plan = null, plan_md = '', ai_assist_stats = null } = project

      const filesFromDB = _buildFilesFromDB(tasks)
      const { devSessionMap, unmatchedDevSessions, sortedDevSessions, lastDevSession } = _buildDevSessionMap(dev_sessions)

      const isLive = get().isRunning && get().selectedProjectName === projectName
      const updates = _buildInitialUpdates({
        tasks, filesFromDB, sortedDevSessions, lastDevSession,
        project_plan, plan_md, metadata, projectName, ai_assist_stats,
        isLive, getState: get,
      })

      // ── run_sessions 作为历史主数据源 ──
      try {
        const sessionList = await api.fetchSessions()
        if (_loadVersion !== myVersion) return
        const storeProject = get().projects?.find(p => p.folder === projectName)
        const projectPath = storeProject?.path || ''
        const projectDisplayName = storeProject?.name || ''
        const projectSessions = sessionList
          .filter((s) =>
            s.project_name === projectName ||
            (projectDisplayName && s.project_name === projectDisplayName) ||
            (projectPath && s.workspace_dir === projectPath)
          )
          .sort((a, b) => (b.started_at || 0) - (a.started_at || 0))

        _mergeGlobalSessions({ projectSessions, devSessionMap, unmatchedDevSessions, isLive, updates, projectName })

        // ── 事件回放：用共享处理器 + 迭代构建 ──
        const matchingSession = !isLive && projectSessions.find((s) => s.has_events)
        if (matchingSession) {
          const { events } = await api.fetchSessionEvents(matchingSession.session_id)
          if (_loadVersion !== myVersion) return

          if (events?.length > 0) {
            const logEntries = events
              .filter((e) => e.type !== 'heartbeat')
              .map((e, idx) => ({
                id: idx + Math.random(), type: e.type,
                agent: e.agent || 'system', data: e.data || {},
                timestamp: e.started_at ? new Date(e.started_at * 1000).toLocaleTimeString() : '',
              }))
            updates.executionLogs = logEntries

            if (updates.executionHistory?.length > 0) {
              updates.executionHistory = updates.executionHistory.map((h, i) =>
                i === 0 ? { ...h, logs: logEntries } : h
              )
            }

            const restoredIterations = _replayEventsToUpdates(events, updates)
            _backfillIterationTokens(restoredIterations, updates)

            // token 统计更新
            if (restoredIterations.length > 0) {
              updates.iterationHistory = restoredIterations
              const iterTokenSum = restoredIterations.reduce((s, i) => s + (i.tokensUsed || 0), 0)
              if (iterTokenSum > 0) {
                const curTokens = updates.executionStats?.tokens || 0
                const isRunning = matchingSession?.status === 'running'
                updates.executionStats = {
                  ...updates.executionStats,
                  tokens: isRunning ? iterTokenSum : Math.max(curTokens, iterTokenSum),
                }
              }
            }

            _recalcStatsAfterReplay(updates)

            // 恢复运行中会话：重建 SSE 连接
            if (matchingSession.status === 'running') {
              updates.sessionId = matchingSession.session_id
              updates.isRunning = true
              const resumeEventCount = events?.length || 0
              const capturedVersion = myVersion
              setTimeout(() => {
                if (_loadVersion !== capturedVersion) return
                const sse = new SSEConnection(matchingSession.session_id, {
                  onEvent: (event) => get()._handleSSEEvent(event),
                  onError: () => get()._handleSSEDisconnect(),
                })
                sse._eventCount = resumeEventCount
                sse.connect()
                set({ sseConnection: sse })
              }, 100)
            }

            updates.executionStats = { ...updates.executionStats, files: updates.executionFiles.length }
          }
        }
      } catch (e) {
        console.debug('Session events not available:', e.message)
      }

      // ── 兜底：从 agent_tokens 生成合成迭代 ──
      if (!updates.iterationHistory || updates.iterationHistory.length === 0) {
        const syntheticIters = _buildSyntheticIterations(lastDevSession, filesFromDB)
        if (syntheticIters.length > 0) updates.iterationHistory = syntheticIters
      }

      if (_loadVersion !== myVersion) return
      set(updates)
    } catch (e) {
      console.error('loadProjectHistory error:', e)
    }
  },
})
