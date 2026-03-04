import { describe, it, expect } from 'vitest'
import {
  applyEvent, buildEventContext, buildTaskEntry,
  resolvePhase, KNOWN_PHASES,
} from '../../stores/helpers/eventProcessor'
import { EMPTY_STATS } from '../../stores/helpers/constants'

function freshCtx(overrides = {}) {
  return buildEventContext({
    executionTaskList: [],
    executionStats: { ...EMPTY_STATS },
    executionFiles: [],
    ...overrides,
  })
}

// ─── buildTaskEntry ────────────────────────────────

describe('buildTaskEntry', () => {
  it('creates a properly shaped task from plan data', () => {
    const entry = buildTaskEntry({
      id: 'task-1', title: 'Build UI', description: 'Create components',
      feature_tag: 'frontend', files: ['a.jsx'], verification_steps: ['check render'],
    })
    expect(entry).toMatchObject({
      id: 'task-1', title: 'Build UI', status: 'pending',
      passes: false, feature_tag: 'frontend',
    })
  })

  it('defaults missing fields', () => {
    const entry = buildTaskEntry({ id: 'x' })
    expect(entry.title).toBe('x')
    expect(entry.description).toBe('')
    expect(entry.files).toEqual([])
    expect(entry.verification_steps).toEqual([])
  })
})

// ─── resolvePhase ──────────────────────────────────

describe('resolvePhase', () => {
  it('returns known phases as-is', () => {
    for (const p of KNOWN_PHASES) {
      expect(resolvePhase(p)).toBe(p)
    }
  })

  it('normalizes Chinese phase names', () => {
    expect(resolvePhase('代码开发阶段')).toBe('dev')
    expect(resolvePhase('测试验证阶段')).toBe('test')
    expect(resolvePhase('需求分析阶段')).toBe('planning')
    expect(resolvePhase('规划阶段')).toBe('plan')
    expect(resolvePhase('修复阶段')).toBe('fix')
  })

  it('strips "Phase N:" prefixes', () => {
    expect(resolvePhase('Phase 1: dev')).toBe('dev')
    expect(resolvePhase('Phase 2 - test')).toBe('test')
  })

  it('returns empty string for falsy input', () => {
    expect(resolvePhase('')).toBe('')
    expect(resolvePhase(null)).toBe('')
  })
})

// ─── applyEvent: sandbox ───────────────────────────

describe('applyEvent — sandbox events', () => {
  it('sandbox_preparing sets status with progress', () => {
    const u = applyEvent('sandbox_preparing', {
      step: 'pull_image', message: '拉取镜像...', progress: 40,
    }, freshCtx())
    expect(u.sandboxStatus).toEqual({
      step: 'pull_image', message: '拉取镜像...', progress: 40, ready: false,
    })
  })

  it('sandbox_ready marks ready with 100% progress', () => {
    const u = applyEvent('sandbox_ready', { message: '就绪' }, freshCtx())
    expect(u.sandboxStatus.ready).toBe(true)
    expect(u.sandboxStatus.progress).toBe(100)
  })
})

// ─── applyEvent: planning ──────────────────────────

describe('applyEvent — planning events', () => {
  it('planning_progress accumulates steps and avoids duplicates', () => {
    let ctx = freshCtx()

    const u1 = applyEvent('planning_progress', {
      step: 'analyze', message: '分析需求', progress: 30,
    }, ctx)
    expect(u1.planningProgress.steps).toHaveLength(1)

    ctx = freshCtx({ planningProgress: u1.planningProgress })
    const u2 = applyEvent('planning_progress', {
      step: 'design', message: '设计架构', progress: 60,
    }, ctx)
    expect(u2.planningProgress.steps).toHaveLength(2)
    expect(u2.planningProgress.steps[0].completed).toBe(true)
    expect(u2.planningProgress.steps[1].completed).toBe(false)
  })

  it('planning_progress "complete" marks all steps done', () => {
    const ctx = freshCtx({
      planningProgress: { steps: [{ step: 'a', message: 'x', completed: false }] },
    })
    const u = applyEvent('planning_progress', { step: 'complete', message: 'Done' }, ctx)
    expect(u.planningProgress.steps.every(s => s.completed)).toBe(true)
  })
})

// ─── applyEvent: plan_ready ────────────────────────

describe('applyEvent — plan_ready', () => {
  it('builds executionTaskList from plan tasks', () => {
    const u = applyEvent('plan_ready', {
      tasks: [
        { id: 'task-1', title: 'Build API', description: 'REST API' },
        { id: 'task-2', title: 'Build UI' },
      ],
    }, freshCtx())

    expect(u.executionTaskList).toHaveLength(2)
    expect(u.executionTaskList[0].status).toBe('pending')
    expect(u.executionStats.tasks.total).toBe(2)
  })
})

// ─── applyEvent: task lifecycle ────────────────────

describe('applyEvent — task lifecycle', () => {
  const planTasks = [
    { id: 'task-1', title: 'A', description: '', status: 'pending', passes: false, files: [], verification_steps: [], error_info: null },
    { id: 'task-2', title: 'B', description: '', status: 'pending', passes: false, files: [], verification_steps: [], error_info: null },
  ]

  it('task_start moves task to in_progress', () => {
    const ctx = freshCtx({ executionTaskList: planTasks })
    const u = applyEvent('task_start', { task_id: 'task-1' }, ctx)
    expect(u.executionTaskList.find(t => t.id === 'task-1').status).toBe('in_progress')
  })

  it('task_start creates task if not in list', () => {
    const ctx = freshCtx({ executionTaskList: [] })
    const u = applyEvent('task_start', { task_id: 'task-new', task_title: 'New Task' }, ctx)
    expect(u.executionTaskList).toHaveLength(1)
    expect(u.executionTaskList[0].id).toBe('task-new')
    expect(u.executionTaskList[0].status).toBe('in_progress')
  })

  it('task_complete marks task as completed', () => {
    const tasks = [{ ...planTasks[0], status: 'in_progress' }, { ...planTasks[1] }]
    const ctx = freshCtx({ executionTaskList: tasks })
    const u = applyEvent('task_complete', { task_id: 'task-1' }, ctx)
    expect(u.executionTaskList.find(t => t.id === 'task-1').status).toBe('completed')
    expect(u.executionStats.tasks.completed).toBe(1)
  })

  it('task_complete marks as failed on success=false', () => {
    const tasks = [{ ...planTasks[0], status: 'in_progress' }]
    const ctx = freshCtx({ executionTaskList: tasks })
    const u = applyEvent('task_complete', {
      task_id: 'task-1', success: false, error: 'timeout',
    }, ctx)
    const t = u.executionTaskList.find(t => t.id === 'task-1')
    expect(t.status).toBe('failed')
    expect(t.error_info.message).toBe('timeout')
  })

  it('task_verified sets passes and status=verified', () => {
    const tasks = [{ ...planTasks[0], status: 'completed' }]
    const ctx = freshCtx({ executionTaskList: tasks })
    const u = applyEvent('task_verified', { task_id: 'task-1', passes: true }, ctx)
    const t = u.executionTaskList.find(t => t.id === 'task-1')
    expect(t.passes).toBe(true)
    expect(t.status).toBe('verified')
    expect(u.executionStats.tasks.verified).toBe(1)
  })

  it('task_verified with passes=false marks as failed', () => {
    const tasks = [{ ...planTasks[0], status: 'completed' }]
    const ctx = freshCtx({ executionTaskList: tasks })
    const u = applyEvent('task_verified', { task_id: 'task-1', passes: false }, ctx)
    const t = u.executionTaskList.find(t => t.id === 'task-1')
    expect(t.passes).toBe(false)
    expect(t.status).toBe('failed')
  })

  it('task_regression resets passes and reverts to completed', () => {
    const tasks = [{ ...planTasks[0], status: 'verified', passes: true }]
    const ctx = freshCtx({ executionTaskList: tasks })
    const u = applyEvent('task_regression', { task_id: 'task-1', reason: '共享文件变更' }, ctx)
    const t = u.executionTaskList.find(t => t.id === 'task-1')
    expect(t.passes).toBe(false)
    expect(t.status).toBe('completed')
  })
})

// ─── applyEvent: file_created ──────────────────────

describe('applyEvent — file_created', () => {
  it('adds file to list and updates count', () => {
    const ctx = freshCtx({ executionFiles: ['a.js'] })
    const u = applyEvent('file_created', { file: 'b.js' }, ctx)
    expect(u.executionFiles).toEqual(['a.js', 'b.js'])
    expect(u.executionStats.files).toBe(2)
  })

  it('deduplicates files', () => {
    const ctx = freshCtx({ executionFiles: ['a.js'] })
    const u = applyEvent('file_created', { file: 'a.js' }, ctx)
    expect(u.executionFiles).toEqual(['a.js'])
  })

  it('handles "path" field name', () => {
    const ctx = freshCtx()
    const u = applyEvent('file_created', { path: 'c.py' }, ctx)
    expect(u.executionFiles).toEqual(['c.py'])
  })
})

// ─── applyEvent: test_result ───────────────────────

describe('applyEvent — test_result', () => {
  it('updates test stats and bugs', () => {
    const u = applyEvent('test_result', {
      tests_passed: 3, tests_total: 5, bug_count: 2,
      bugs: [{ id: 'bug-1', title: 'NPE' }],
    }, freshCtx())
    expect(u.executionStats.tests).toEqual({ passed: 3, total: 5 })
    expect(u.executionStats.bugs).toBe(2)
    expect(u.executionBugsList).toHaveLength(1)
  })
})

// ─── applyEvent: preview_ready ─────────────────────

describe('applyEvent — preview_ready', () => {
  it('sets preview data', () => {
    const u = applyEvent('preview_ready', {
      url: 'http://localhost:8888', available: true,
    }, freshCtx())
    expect(u.executionPreview).toEqual({ url: 'http://localhost:8888', available: true })
  })
})

// ─── applyEvent: execution_failed ──────────────────

describe('applyEvent — execution_failed', () => {
  it('sets failure reason and suggestions', () => {
    const u = applyEvent('execution_failed', {
      user_message: '沙箱超时', recovery_suggestions: ['重试'],
    }, freshCtx())
    expect(u.executionFailure).toEqual({
      reason: '沙箱超时', suggestions: ['重试'],
    })
  })
})

// ─── applyEvent: token_session ─────────────────────

describe('applyEvent — token_session', () => {
  it('updates agent tokens', () => {
    const u = applyEvent('token_session', {
      agent_tokens: { pm: 500, dev: 2000, test: 800 },
    }, freshCtx())
    expect(u.executionAgentTokens).toEqual({ pm: 500, dev: 2000, test: 800 })
  })
})

// ─── applyEvent: summary ───────────────────────────

describe('applyEvent — summary', () => {
  it('merges summary stats into executionStats', () => {
    const ctx = freshCtx({ executionFiles: ['a.js'] })
    const u = applyEvent('summary', {
      tasks_completed: 3, tasks_total: 5, tasks_verified: 2,
      tests_passed: 10, tests_total: 12,
      bugs_open: 1, total_tokens: 5000, elapsed_seconds: 120,
      files: ['a.js', 'b.js'],
    }, ctx)
    expect(u.executionStats.tasks).toEqual({ completed: 3, total: 5, verified: 2 })
    expect(u.executionStats.tests).toEqual({ passed: 10, total: 12 })
    expect(u.executionStats.tokens).toBe(5000)
    expect(u.executionFiles).toEqual(['a.js', 'b.js'])
  })
})

// ─── applyEvent: done ──────────────────────────────

describe('applyEvent — done', () => {
  it('cleans up in-progress tasks on success', () => {
    const tasks = [
      { id: 't1', status: 'in_progress', passes: false },
      { id: 't2', status: 'completed', passes: true },
    ]
    const ctx = freshCtx({ executionTaskList: tasks })
    const u = applyEvent('done', { success: true }, ctx)
    expect(u.executionTaskList[0].status).toBe('completed')
    expect(u.executionTaskList[1].status).toBe('completed')
  })

  it('marks in-progress tasks as failed on failure', () => {
    const tasks = [{ id: 't1', status: 'in_progress', passes: false }]
    const ctx = freshCtx({ executionTaskList: tasks })
    const u = applyEvent('done', { success: false }, ctx)
    expect(u.executionTaskList[0].status).toBe('failed')
  })

  it('sets executionFailure from failure_reason', () => {
    const u = applyEvent('done', {
      failure_reason: 'Out of memory',
      recovery_suggestions: ['增加内存'],
    }, freshCtx())
    expect(u.executionFailure.reason).toBe('Out of memory')
  })

  it('uses _lastErrorMessage as fallback for failure', () => {
    const ctx = freshCtx({ _lastErrorMessage: 'API key 无效' })
    const u = applyEvent('done', { success: false }, ctx)
    expect(u.executionFailure.reason).toBe('API key 无效')
  })
})

// ─── applyEvent: miscellaneous ─────────────────────

describe('applyEvent — miscellaneous events', () => {
  it('complexity_assessed updates executionComplexity', () => {
    const u = applyEvent('complexity_assessed', { complexity: 'high' }, freshCtx())
    expect(u.executionComplexity).toBe('high')
  })

  it('dev_self_test stores test results', () => {
    const u = applyEvent('dev_self_test', {
      task_id: 't1', passed: true, results: [{ ok: true }],
    }, freshCtx())
    expect(u.lastDevSelfTest.passed).toBe(true)
  })

  it('unknown event type returns empty updates', () => {
    const u = applyEvent('unknown_event', { foo: 1 }, freshCtx())
    expect(Object.keys(u)).toHaveLength(0)
  })
})
