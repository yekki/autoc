/**
 * 共享事件处理器 — SSE 实时处理和历史事件回放共用的事件→状态映射逻辑。
 * 消除 _handleSSEEvent 与 loadProjectHistory 之间的大量重复代码。
 */
import { normalizeTaskId, findTask } from './taskUtils'

/** 将原始技术错误转为用户可读的一句话摘要 */
export function summarizeError(raw) {
  return _summarizeError(raw)
}
function _summarizeError(raw) {
  if (!raw) return ''
  if (raw.includes('Planning 失败') || raw.includes('planning')) return '规划失败'
  if (raw.includes('Docker') || raw.includes('docker') || raw.includes('container')) return '容器启动失败'
  if (raw.includes('timeout') || raw.includes('Timeout')) return '执行超时'
  if (raw.includes('API') || raw.includes('api_key') || raw.includes('APIError')) return 'API 调用失败'
  if (raw.includes('rate_limit') || raw.includes('RateLimitError')) return '请求频率超限'
  if (raw.length > 80) return raw.slice(0, 60).replace(/[\[{(].*$/, '').trim() + '…'
  return raw
}

/** 从 plan 数据构建标准化任务条目 */
export function buildTaskEntry(t) {
  return {
    id: t.id,
    title: t.title || t.id,
    description: t.description || '',
    status: 'pending',
    passes: false,
    feature_tag: t.feature_tag || '',
    files: t.files || [],
    verification_steps: t.verification_steps || [],
    priority: t.priority ?? null,
    verification_notes: '',
    error_info: null,
  }
}

export const KNOWN_PHASES = new Set(['refine', 'planning', 'plan', 'dev', 'test', 'fix'])

/** Phase 名归一化（中文/英文/带前缀格式统一映射） */
export function resolvePhase(raw) {
  if (!raw) return ''
  const s = raw.toLowerCase().trim()
  if (KNOWN_PHASES.has(s)) return s
  const stripped = s.replace(/^phase\s*\d+\s*[-:.]*\s*/i, '').trim()
  if (stripped) {
    const mapped = stripped
      .replace(/需求分析.*/, 'planning').replace(/需求优化.*/, 'refine')
      .replace(/代码开发.*/, 'dev').replace(/测试验证.*/, 'test')
      .replace(/修复.*/, 'fix').replace(/规划.*/, 'plan')
    if (KNOWN_PHASES.has(mapped)) return mapped
  }
  return s
}

/** Phase → Agent 名映射（用于从 agent_tokens 回填迭代级 token 数据） */
export const PHASE_AGENT_MAP = {
  refine: 'helper', planning: 'coder', plan: 'coder',
  dev: ['coder', 'implementer'], test: ['critique', 'implementer'], fix: ['coder', 'implementer'],
  critique: 'critique', rule_review: 'coder',
}

/**
 * 从任意 state-like 对象中提取 applyEvent 所需的上下文字段。
 * 可传入 Zustand store state 或 loadProjectHistory 的累积 updates 对象。
 */
export function buildEventContext(source) {
  return {
    executionTaskList: source.executionTaskList || [],
    executionStats: source.executionStats || {
      tasks: { completed: 0, total: 0, verified: 0 },
      tests: { passed: 0, total: 0 },
      bugs: 0, files: 0, tokens: 0, elapsed: 0,
    },
    executionFiles: source.executionFiles || [],
    planningProgress: source.planningProgress || null,
    executionFailure: source.executionFailure || null,
    executionSummary: source.executionSummary || null,
    _lastErrorMessage: source._lastErrorMessage || '',
  }
}

/**
 * 处理单个事件，返回需要合并到 state 的 partial updates。
 * 涵盖 SSE 实时处理和历史回放中完全相同的事件类型。
 *
 * @param {string} type  事件类型
 * @param {object} data  事件数据
 * @param {object} ctx   由 buildEventContext 构建的上下文
 * @returns {object}     partial state updates
 */
export function applyEvent(type, data, ctx) {
  const updates = {}

  switch (type) {
    case 'sandbox_preparing':
      updates.pipelineStage = 'sandbox'
      updates.sandboxStatus = {
        step: data?.step || '', message: data?.message || '',
        progress: data?.progress || 0, ready: false,
      }
      break

    case 'sandbox_ready':
      updates.sandboxStatus = {
        step: 'ready', message: data?.message || '沙箱环境已就绪',
        progress: 100, ready: true,
      }
      updates.pipelineStage = 'sandbox'
      break

    case 'planning_analyzing':
      updates.currentPhase = data?.message || '正在分析需求...'
      updates.pipelineStage = 'planning'
      break

    case 'planning_progress': {
      const step = data?.step || ''
      const message = data?.message || ''
      const prevSteps = ctx.planningProgress?.steps || []
      const newSteps = step === 'prepare' ? [] : [...prevSteps]
      if (message && !newSteps.some(s => s.step === step)) {
        newSteps.push({ step, message, completed: false })
      }
      newSteps.forEach(s => { s.completed = s.step !== step })
      if (step === 'complete') {
        newSteps.forEach(s => { s.completed = true })
      }
      updates.planningProgress = { step, progress: data?.progress ?? 0, message, steps: newSteps }
      updates.currentPhase = message
      break
    }

    case 'phase_start':
      updates.currentPhase = data?.title || data?.phase || ''
      break

    case 'plan_ready':
      updates.executionPlan = data
      if (data?.plan_md) {
        updates.executionPlanMd = data.plan_md
      }
      if (data?.tasks) {
        updates.executionTaskList = data.tasks.map(buildTaskEntry)
        updates.executionStats = {
          ...ctx.executionStats,
          tasks: { ...ctx.executionStats.tasks, total: data.tasks.length },
        }
      }
      break

    case 'task_start': {
      const rawId = data?.task_id
      if (rawId) {
        const taskList = [...ctx.executionTaskList]
        const nid = normalizeTaskId(rawId)
        for (const t of taskList) {
          if (t.status === 'in_progress' && t.id !== nid) {
            t.status = t.passes ? 'verified' : 'failed'
          }
        }
        const existing = findTask(taskList, rawId)
        if (existing) {
          existing.status = 'in_progress'
          existing.error_info = null
        } else {
          taskList.push({
            id: nid,
            title: data?.task_title || data?.title || nid,
            description: data?.description || '',
            status: 'in_progress',
            passes: false,
            files: data?.files || [],
            verification_steps: data?.verification_steps || [],
            error_info: null,
          })
        }
        updates.executionTaskList = taskList
        updates.executionStats = {
          ...ctx.executionStats,
          tasks: {
            ...ctx.executionStats.tasks,
            total: Math.max(ctx.executionStats.tasks.total, taskList.length),
          },
        }
      }
      break
    }

    case 'task_complete': {
      if (data?.task_id) {
        const taskList = [...ctx.executionTaskList]
        const t = findTask(taskList, data.task_id)
        if (t) {
          const failed = data?.success === false
          t.status = failed ? 'failed' : 'completed'
          if (data?.tokens_used) t.tokens_used = data.tokens_used
          if (data?.elapsed_seconds) t.elapsed_seconds = data.elapsed_seconds
          if (failed && (data?.user_message || data?.error)) {
            t.error_info = {
              message: data.user_message || data.error,
              suggestion: data.suggestion || '',
            }
          }
        }
        updates.executionTaskList = taskList
        updates.executionStats = {
          ...ctx.executionStats,
          tasks: {
            ...ctx.executionStats.tasks,
            completed: taskList.filter(t => t.status === 'completed' || t.status === 'verified').length,
          },
        }
      }
      break
    }

    case 'task_verified': {
      if (data?.task_id) {
        const taskList = [...ctx.executionTaskList]
        const t = findTask(taskList, data.task_id)
        if (t) {
          t.passes = data?.passes || false
          if (data?.passes) {
            t.status = 'verified'
            t.error_info = null
          } else if (t.status !== 'in_progress') {
            t.status = 'failed'
          }
          if (data?.details) t.verification_notes = data.details
          else if (!data?.passes) t.verification_notes = '验证未通过，等待修复'
        }
        updates.executionTaskList = taskList
        updates.executionStats = {
          ...ctx.executionStats,
          tasks: {
            ...ctx.executionStats.tasks,
            verified: taskList.filter(t => t.passes).length,
          },
        }
      }
      break
    }

    case 'task_regression': {
      if (data?.task_id) {
        const taskList = [...ctx.executionTaskList]
        const t = findTask(taskList, data.task_id)
        if (t) {
          t.passes = false
          t.status = 'completed'
          t.verification_notes = data?.reason || '共享文件被修改，需重新验证'
        }
        updates.executionTaskList = taskList
        updates.executionStats = {
          ...ctx.executionStats,
          tasks: {
            ...ctx.executionStats.tasks,
            verified: taskList.filter(t => t.passes).length,
          },
        }
      }
      break
    }

    case 'file_created': {
      const fp = data?.file || data?.path
      if (fp) {
        const files = [...ctx.executionFiles]
        if (!files.includes(fp)) files.push(fp)
        updates.executionFiles = files
        updates.executionStats = { ...ctx.executionStats, files: files.length }
      }
      break
    }

    case 'test_result':
      updates.executionStats = {
        ...ctx.executionStats,
        tests: {
          passed: data?.tests_passed ?? 0,
          total: data?.tests_total ?? 0,
        },
        bugs: data?.bug_count ?? ctx.executionStats.bugs ?? 0,
      }
      if (data?.bugs?.length) {
        updates.executionBugsList = data.bugs
      }
      break

    case 'preview_ready':
      updates.executionPreview = data || null
      break

    case 'execution_failed':
      if (data?.failure_reason || data?.user_message) {
        updates.executionFailure = {
          reason: data.user_message || data.failure_reason,
          suggestions: data.recovery_suggestions || [],
        }
      }
      break

    case 'token_session':
      if (data?.agent_tokens) {
        updates.executionAgentTokens = data.agent_tokens
      }
      break

    case 'summary':
      updates.pipelineStage = 'finalize'
      updates.executionSummary = data
      updates.executionStats = {
        ...ctx.executionStats,
        tasks: {
          completed: data?.tasks_completed ?? ctx.executionStats.tasks?.completed ?? 0,
          total: data?.tasks_total ?? ctx.executionStats.tasks?.total ?? 0,
          verified: data?.tasks_verified ?? ctx.executionStats.tasks?.verified ?? 0,
        },
        tests: {
          passed: data?.tests_passed ?? ctx.executionStats.tests?.passed ?? 0,
          total: data?.tests_total ?? ctx.executionStats.tests?.total ?? 0,
        },
        bugs: data?.bugs_open ?? ctx.executionStats.bugs ?? 0,
        tokens: data?.total_tokens ?? ctx.executionStats.tokens ?? 0,
        elapsed: data?.elapsed_seconds || ctx.executionStats.elapsed,
        files: (data?.files || ctx.executionFiles || []).length,
      }
      if (data?.files?.length) {
        updates.executionFiles = [...new Set([...(ctx.executionFiles || []), ...data.files])]
      }
      if (data?.agent_tokens) {
        updates.executionAgentTokens = data.agent_tokens
      }
      break

    case 'complexity_assessed':
      updates.executionComplexity = data?.complexity || 'medium'
      break

    case 'dev_self_test':
      updates.lastDevSelfTest = {
        taskId: data?.task_id || '',
        passed: !!data?.passed,
        results: data?.results || [],
      }
      break

    case 'smoke_check_failed':
      updates.smokeCheckIssues = data?.issues || []
      break

    case 'deploy_gate':
      updates.deployGateStatus = {
        status: data?.status || '',
        url: data?.url || '',
        message: data?.message || '',
        projectType: data?.project_type || '',
      }
      break

    case 'failure_analysis':
      updates.lastFailureAnalysis = {
        mode: data?.mode || '',
        strategy: data?.strategy || '',
        shouldRollback: !!data?.should_rollback,
        userMessage: data?.user_message || '',
      }
      break

    case 'bug_fix_start':
      updates.currentPhase = data?.user_message || `正在修复 ${data?.count || 0} 个 Bug`
      break

    case 'reflection':
      updates.lastReflection = {
        round: data?.round || 0,
        content: data?.content || '',
      }
      break

    case 'planning_review':
      updates.currentPhase = data?.user_message || '正在验收...'
      break

    case 'planning_acceptance':
      updates.planningAcceptanceResult = {
        passed: !!data?.passed,
        answer: data?.answer || '',
        score: data?.score || '',
        userMessage: data?.user_message || '',
      }
      break

    case 'planning_decision':
      updates.lastPlanningDecision = {
        action: data?.action || '',
        taskId: data?.task_id || '',
        reason: data?.reason || '',
        userMessage: data?.user_message || '',
      }
      break

    case 'redefine_start': {
      if (data?.new_version) {
        updates.executionExpectedVersion = data.new_version
      }
      updates.executionTaskList = []
      updates.executionSummary = null
      updates.executionStats = {
        tasks: { completed: 0, total: 0, verified: 0 },
        tests: { passed: 0, total: 0 },
        bugs: 0, files: 0, tokens: 0, elapsed: 0,
      }
      break
    }

    case 'add_feature_start': {
      if (data?.new_version) {
        updates.executionExpectedVersion = data.new_version
      }
      break
    }

    case 'error':
      if (data?.message) {
        updates._lastErrorMessage = data.message
      }
      break

    case 'done': {
      if (data?.success === false) {
        const rawErr = ctx._lastErrorMessage || data?.failure_reason || ''
        const friendly = data?.user_message || ''
        const reason = friendly || _summarizeError(rawErr) || '执行失败'
        updates.executionFailure = {
          reason,
          detail: rawErr,
          suggestions: data?.recovery_suggestions || [],
        }
      }
      if (!ctx.executionSummary) {
        updates.executionSummary = data
      } else if (data?.tasks_total != null || data?.tasks_verified != null) {
        updates.executionSummary = { ...ctx.executionSummary, ...data }
      } else if (data?.success != null) {
        updates.executionSummary = { ...ctx.executionSummary, success: data.success }
      }
      if (data?.total_tokens && !ctx.executionStats?.tokens) {
        updates.executionStats = { ...ctx.executionStats, tokens: data.total_tokens }
      }
      const isSuccess = data?.success ?? false

      if (ctx.executionTaskList.length === 0 && data?.tasks?.length > 0) {
        // SSE 中间事件丢失时，从 done 事件恢复完整任务列表
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
        const cleaned = ctx.executionTaskList.map(t =>
          t.status === 'in_progress' ? { ...t, status: isSuccess ? 'completed' : 'failed' } : t
        )
        if (cleaned.some((t, i) => t !== ctx.executionTaskList[i])) {
          updates.executionTaskList = cleaned
        }
      }
      break
    }
  }

  return updates
}
