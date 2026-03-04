import { applyEvent, buildEventContext, summarizeError as _summarizeError } from '../helpers/eventProcessor'

export const createSseSlice = (set, get) => ({
  _handleSSEDisconnect: () => {
    const state = get()
    const cleanedTasks = state.executionTaskList.map((t) =>
      t.status === 'in_progress' ? { ...t, status: 'failed' } : t
    )
    set({
      isRunning: false, sseConnection: null,
      executionTaskList: cleanedTasks,
      currentPhase: '',
      executionFailure: state.executionFailure || {
        reason: '与后端的连接中断',
        suggestions: ['检查后端服务是否运行中', '刷新页面后点击「继续执行」恢复'],
      },
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
    })
    get().fetchProjects()
  },

  _handleSSEEvent: (event) => {
    const { type, data } = event
    const state = get()

    // --- 日志条目 ---
    const log = {
      id: Date.now() + Math.random(),
      type,
      agent: event.agent || 'system',
      data: data || {},
      timestamp: new Date().toLocaleTimeString(),
    }
    const logs = [...state.executionLogs, log]
    const updates = { executionLogs: logs }

    // --- 执行历史条目管理（使用不可变更新，避免直接变异浅拷贝数组中的对象引用）---
    const history = [...state.executionHistory]
    const isNewOp = type === 'quick_fix_start' || type === 'revise_start' || type === 'resume_start'
    const isFirstPhase = type === 'phase_start' && history.length === 0 && state.executionLogs.length <= 1
    if (isNewOp || isFirstPhase) {
      const opType = type === 'resume_start' ? 'resume'
        : type === 'quick_fix_start' ? 'quick_fix'
        : type === 'revise_start' ? 'revise'
        : 'run'
      if (history.length > 0) history[0] = { ...history[0], isLatest: false }
      history.unshift({
        index: history.length + 1, type: opType,
        startedAt: log.timestamp, tokens: 0, success: null,
        summary: null, logs: [log], isLatest: true,
      })
      updates.executionHistory = history
    } else if (history.length > 0) {
      history[0] = { ...history[0], logs: [...history[0].logs, log] }
      updates.executionHistory = history
    }

    // --- 共享事件处理（done 事件由 SSE 独立处理，不走 common） ---
    if (type !== 'done') {
      const ctx = buildEventContext(state)
      const commonUpdates = applyEvent(type, data, ctx)
      Object.assign(updates, commonUpdates)
    }

    // --- SSE 专有事件处理 ---
    switch (type) {
      case 'plan_ready':
        updates.planningProgress = null
        updates.planApprovalPending = false  // 计划重生成时重置审批状态
        if (data?.plan_md) {
          updates.executionPlanMd = data.plan_md
        }
        if (data?.tech_stack?.length && state.selectedProjectName) {
          updates.projects = state.projects.map((p) =>
            p.folder === state.selectedProjectName
              ? { ...p, tech_stack: data.tech_stack }
              : p
          )
        }
        break

      // S-004: 规划阶段子步骤进度（需求分析→架构设计→任务拆解）
      case 'planning_substep': {
        const step = data?.step || 0
        const label = data?.label || ''
        const status = data?.status || 'running' // 'running' | 'done'
        const prevProgress = state.planningProgress || { steps: [], progress: 0 }
        const steps = [...(prevProgress.steps || [])]
        const idx = steps.findIndex(s => s.step === step)
        const stepObj = { step, message: label, completed: status === 'done' }
        if (idx >= 0) steps[idx] = stepObj
        else steps.push(stepObj)
        const doneCount = steps.filter(s => s.completed).length
        const progress = Math.round((doneCount / Math.max(steps.length, 3)) * 100)
        updates.planningProgress = { ...prevProgress, steps, progress }
        break
      }

      // S-002: Planning 审批门 — 切换到概览 Tab 并标记等待审批
      case 'plan_approval_required':
        updates.planApprovalPending = true
        updates.activeTab = 'overview'
        if (data?.plan_md) {
          updates.executionPlanMd = data.plan_md
        }
        break

      case 'execution_start':
        updates.pipelineStage = 'dev'
        if (data?.task_count) {
          const base = updates.executionStats || state.executionStats
          updates.executionStats = {
            ...base,
            tasks: { ...base.tasks, total: data.task_count },
          }
        }
        break

      case 'loop_start':
        updates.currentIteration = {
          ...state.currentIteration,
          maxIterations: data?.max_iterations || 0,
        }
        break

      case 'iteration_start': {
        const iterNum = data?.iteration || 0
        const iterHist = [...(state.iterationHistory || [])]
        if (iterHist.findIndex((i) => i.iteration === iterNum) < 0) {
          iterHist.push({
            iteration: iterNum, phase: data?.phase || 'dev',
            success: null, error: '', tokensUsed: 0, elapsedSeconds: 0,
            storyTitle: data?.story_title || '', storyId: data?.story_id || '',
          })
          updates.iterationHistory = iterHist
        }
        break
      }

      case 'iteration_done': {
        const phase = data?.phase || ''
        if (phase === 'critique' || phase === 'rule_review') {
          updates.pipelineStage = 'critique'
        }
        updates.currentIteration = {
          ...state.currentIteration,
          iteration: data?.iteration || 0,
          round: data?.round ?? state.currentIteration.round,
        }
        const iterNum = data?.iteration || 0
        const iterHistory = [...(state.iterationHistory || [])]
        const existingIdx = iterHistory.findIndex((i) => i.iteration === iterNum)
        const iterEntry = {
          iteration: iterNum,
          phase: data?.phase || (state.currentPhase || 'dev').toLowerCase(),
          success: data?.success ?? null,
          error: data?.error || '',
          tokensUsed: data?.tokens_used || data?.total_tokens || 0,
          elapsedSeconds: data?.elapsed_seconds || 0,
          storyTitle: data?.story_title || data?.task_title || '',
          storyId: data?.story_id || data?.task_id || '',
          filesChanged: data?.files || [],
          bugs: data?.bugs || [],
        }
        if (existingIdx >= 0) {
          iterHistory[existingIdx] = { ...iterHistory[existingIdx], ...iterEntry }
        } else {
          iterHistory.push(iterEntry)
        }
        updates.iterationHistory = iterHistory

        const iterTokens = data?.tokens_used || data?.total_tokens || 0
        if (iterTokens > 0) {
          const curStats = updates.executionStats || state.executionStats
          updates.executionStats = {
            ...curStats,
            tokens: (curStats.tokens || 0) + iterTokens,
          }
        }
        break
      }

      case 'test_result':
        // verify Tab 不存在，Bug 信息在 Overview BugSection 中展示
        break

      case 'resume_start':
      case 'quick_fix_start':
        updates.isRunning = true
        updates.executionFailure = null
        updates.fixProgress = {
          status: 'fixing', currentBug: null, current: 0,
          total: data?.bug_count || 0,
          results: (data?.bugs || []).map((b) => ({ id: b.id, title: b.title, status: 'pending' })),
          fixedCount: 0, elapsedSeconds: 0, verified: null,
        }
        break

      case 'revise_start':
      case 'redefine_start':
        updates.isRunning = true
        updates.executionFailure = null
        if (data?.new_version) {
          updates.executionExpectedVersion = data.new_version
        }
        break

      case 'add_feature_start':
        updates.isRunning = true
        updates.executionFailure = null
        if (data?.new_version) {
          updates.executionExpectedVersion = data.new_version
        }
        break

      case 'bug_fix_progress': {
        const fp = { ...state.fixProgress }
        fp.currentBug = { id: data?.bug_id, title: data?.bug_title }
        fp.current = data?.current || fp.current
        fp.total = data?.total || fp.total
        const bugStatus = data?.status
        if (data?.bug_id && bugStatus) {
          const idx = fp.results.findIndex((r) => r.id === data.bug_id)
          if (idx >= 0) {
            fp.results = [...fp.results]
            fp.results[idx] = { ...fp.results[idx], status: bugStatus }
          } else {
            fp.results = [...fp.results, { id: data.bug_id, title: data.bug_title, status: bugStatus }]
          }
        }
        updates.fixProgress = fp
        break
      }

      case 'bug_fix_done':
        if (data?.bugs_remaining != null) {
          const curStats = updates.executionStats || state.executionStats
          updates.executionStats = { ...curStats, bugs: data.bugs_remaining }
        }
        break

      case 'quick_fix_done': {
        if (data?.files?.length) {
          const merged = [...new Set([...(state.executionFiles || []), ...data.files])]
          updates.executionFiles = merged
          updates.executionStats = { ...(updates.executionStats || state.executionStats), files: merged.length }
        }
        const finalResults = data?.bug_results || state.fixProgress.results
        updates.fixProgress = {
          ...state.fixProgress,
          status: 'done', currentBug: null,
          fixedCount: data?.fixed || 0,
          elapsedSeconds: data?.elapsed_seconds || 0,
          verified: data?.verified ?? null,
          results: finalResults.map((r) => ({ id: r.id, title: r.title, status: r.status })),
        }
        if (data?.remaining_bugs) {
          updates.executionBugsList = data.remaining_bugs
          updates.executionStats = {
            ...(updates.executionStats || state.executionStats),
            bugs: data.remaining_bugs.length,
          }
        }
        break
      }

      case 'token_session': {
        const session = {
          session_id: state.sessionId || '',
          total_tokens: data?.total_tokens || 0,
          prompt_tokens: data?.prompt_tokens || 0,
          completion_tokens: data?.completion_tokens || 0,
          cached_tokens: data?.cached_tokens || 0,
          elapsed_seconds: data?.elapsed_seconds || 0,
          success: data?.success ?? true,
          timestamp: data?.timestamp || new Date().toISOString(),
          agent_tokens: data?.agent_tokens || null,
          version: data?.version || '',
          requirement_type: data?.requirement_type || 'primary',
          requirement: data?.requirement || '',
        }
        const existingRuns = state.executionTokenRuns.filter(
          (r) => r.session_id !== session.session_id
        )
        updates.executionTokenRuns = [session, ...existingRuns]
        updates.executionStats = { ...(updates.executionStats || state.executionStats), tokens: session.total_tokens }
        if (history.length > 0) {
          history[0] = { ...history[0], tokens: session.total_tokens, agent_tokens: data?.agent_tokens || null }
          updates.executionHistory = history
        }
        break
      }

      case 'file_created': {
        const fp = data?.file || data?.path
        if (fp) {
          updates.newlyCreatedFiles = [...(state.newlyCreatedFiles || []), fp]
        }
        break
      }

      case 'refiner_quality':
      case 'refiner_enhanced':
      case 'refiner_warning': {
        const prev = state.executionRefinerResult || {}
        if (type === 'refiner_quality') {
          updates.executionRefinerResult = { ...prev, quality: data }
        } else if (type === 'refiner_enhanced') {
          updates.executionRefinerResult = { ...prev, enhanced: data }
        } else {
          updates.executionRefinerResult = { ...prev, warning: data }
        }
        break
      }

      case 'preview_ready':
        if (data?.available && data?.url) {
          updates.activeTab = 'preview'
        }
        break

      case 'preview_stopped':
        updates.executionPreview = { ...(state.executionPreview || {}), available: false, message: '预览已停止' }
        break

      case 'summary':
        if (history.length > 0) {
          history[0] = { ...history[0], summary: data, tokens: data?.total_tokens || 0, agent_tokens: data?.agent_tokens || null }
          updates.executionHistory = history
        }
        break

      case 'done': {
        updates.isRunning = false
        state.sseConnection?.close()
        updates.sseConnection = null
        updates.currentPhase = ''
        updates.pipelineStage = 'done'
        updates.planningProgress = null
        updates.agentThinking = null
        updates.executionComplexity = ''
        updates.lastDevSelfTest = null
        updates.smokeCheckIssues = []
        updates.deployGateStatus = null
        updates.lastFailureAnalysis = null
        updates.lastReflection = null
        updates.planningAcceptanceResult = null
        updates.lastPmDecision = null
        updates.planApprovalPending = false  // 清理审批门状态
        // R-016: 清理上轮预览错误
        updates.previewErrors = data?.preview_errors || []

        const hasPreview = state.executionPreview?.available && state.executionPreview?.url
        if (hasPreview && state.activeTab === 'overview') {
          updates.activeTab = 'preview'
        }

        const isSuccess = data?.success ?? false

        if (state.executionTaskList.length === 0 && data?.tasks?.length > 0) {
          updates.executionTaskList = data.tasks.map(t => ({
            id: t.id,
            title: t.title,
            status: t.passes ? 'verified' : (t.status || 'failed'),
            passes: !!t.passes,
            error: t.error || '',
            tokens_used: t.tokens_used || 0,
            elapsed_seconds: t.elapsed_seconds || 0,
          }))
        } else {
          updates.executionTaskList = state.executionTaskList.map((t) =>
            t.status === 'in_progress' ? { ...t, status: isSuccess ? 'completed' : 'failed' } : t
          )
        }

        if (data && typeof data === 'object') {
          if (!state.executionSummary && data.summary) {
            updates.executionSummary = data
          } else if (state.executionSummary) {
            const patch = {}
            if (data.success != null) patch.success = data.success
            if (data.partial_success != null) patch.partial_success = data.partial_success
            if (Object.keys(patch).length > 0) {
              updates.executionSummary = { ...state.executionSummary, ...patch }
            }
          }
          if (!updates.executionSummary && !state.executionSummary) {
            updates.executionSummary = data
          }

          const curStats = { ...state.executionStats }
          if (data.tasks_total != null) {
            curStats.tasks = {
              completed: data.tasks_completed ?? curStats.tasks?.completed ?? 0,
              total: data.tasks_total ?? curStats.tasks?.total ?? 0,
              verified: data.tasks_verified ?? curStats.tasks?.verified ?? 0,
            }
          }
          if (data.tests_total != null) {
            curStats.tests = {
              passed: data.tests_passed ?? curStats.tests?.passed ?? 0,
              total: data.tests_total ?? curStats.tests?.total ?? 0,
            }
          }
          if (data.bugs_open != null) curStats.bugs = data.bugs_open
          if (data.total_tokens != null) curStats.tokens = data.total_tokens
          if (data.elapsed_seconds) curStats.elapsed = data.elapsed_seconds
          if (data.files?.length) {
            const mergedDone = [...new Set([...(state.executionFiles || []), ...data.files])]
            updates.executionFiles = mergedDone
            curStats.files = mergedDone.length
          }
          updates.executionStats = curStats

          if (data.success === false) {
            const rawErr = state._lastErrorMessage || data.failure_reason || ''
            const friendly = data.user_message || ''
            const reason = friendly || _summarizeError(rawErr) || '执行失败'
            updates.executionFailure = {
              reason,
              detail: rawErr,
              suggestions: data.recovery_suggestions || [],
            }
          }
        }

        if (history.length > 0) {
          const latestSummary = history[0].summary || updates.executionSummary || state.executionSummary || null
          history[0] = { ...history[0], success: data?.success ?? null, summary: latestSummary }
          updates.executionHistory = history
        }

        get().fetchProjects()

        if (state.sessionId) {
          const finalStats = updates.executionStats || state.executionStats
          const doneEntry = {
            session_id: state.sessionId,
            requirement: state.executionRequirement || '',
            status: data?.success ? 'completed' : 'failed',
            success: data?.success ?? false,
            total_tokens: finalStats?.tokens || data?.total_tokens || 0,
            prompt_tokens: state.executionAgentTokens?._prompt_tokens || data?.prompt_tokens || 0,
            completion_tokens: state.executionAgentTokens?._completion_tokens || data?.completion_tokens || 0,
            cached_tokens: state.executionAgentTokens?._cached_tokens || data?.cached_tokens || 0,
            elapsed_seconds: finalStats?.elapsed || data?.elapsed_seconds || 0,
            tasks_completed: finalStats?.tasks?.completed || 0,
            tasks_total: finalStats?.tasks?.total || 0,
            agent_tokens: updates.executionAgentTokens || state.executionAgentTokens || null,
            timestamp: new Date().toISOString(),
            started_at: Math.floor(Date.now() / 1000) - (finalStats?.elapsed || 0),
            has_events: true,
          }
          const existing = state.executionTokenRuns.filter(r => r.session_id !== state.sessionId)
          updates.executionTokenRuns = [doneEntry, ...existing]
        }

        if (history.length === 0) {
          const summary = updates.executionSummary || state.executionSummary
          history.unshift({
            index: 1, type: 'run',
            startedAt: new Date().toLocaleTimeString(),
            tokens: (updates.executionStats || state.executionStats)?.tokens || 0,
            success: data?.success ?? null,
            agent_tokens: state.executionAgentTokens || null,
            summary: summary || null,
            logs: state.executionLogs || [],
            isLatest: true,
          })
          updates.executionHistory = history
        }
        break
      }

      case 'thinking_content':
        if (data?.content) {
          updates.agentThinking = {
            agent: event.agent || 'system',
            content: data.content,
            iteration: data.iteration || 0,
            timestamp: Date.now(),
          }
        }
        break

      default:
        break
    }

    set(updates)
  },
})
