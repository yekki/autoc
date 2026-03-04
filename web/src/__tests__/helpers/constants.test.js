import { describe, it, expect } from 'vitest'
import { EMPTY_STATS, buildResetState } from '../../stores/helpers/constants'

describe('EMPTY_STATS', () => {
  it('has correct shape', () => {
    expect(EMPTY_STATS).toEqual({
      tasks: { completed: 0, total: 0, verified: 0 },
      tests: { passed: 0, total: 0 },
      bugs: 0,
      files: 0,
      tokens: 0,
      elapsed: 0,
    })
  })
})

describe('buildResetState', () => {
  it('returns all execution fields reset to defaults', () => {
    const state = buildResetState()
    expect(state.isRunning).toBe(false)
    expect(state.sessionId).toBeNull()
    expect(state.executionTaskList).toEqual([])
    expect(state.executionStats).toEqual(EMPTY_STATS)
    expect(state.executionBugsList).toEqual([])
    expect(state.executionFiles).toEqual([])
    expect(state.newlyCreatedFiles).toEqual([])
    expect(state.executionFailure).toBeNull()
    expect(state.currentPhase).toBe('')
    expect(state.sandboxStatus).toEqual({ step: '', message: '', progress: 0, ready: false })
    expect(state.fixProgress.status).toBe('idle')
  })

  it('applies overrides on top of defaults', () => {
    const state = buildResetState({ isRunning: true, activeTab: 'code' })
    expect(state.isRunning).toBe(true)
    expect(state.activeTab).toBe('code')
    expect(state.executionTaskList).toEqual([])
  })

  it('returns fresh object each time (no shared references)', () => {
    const a = buildResetState()
    const b = buildResetState()
    expect(a).not.toBe(b)
    expect(a.executionStats).not.toBe(b.executionStats)
    a.executionTaskList.push('x')
    expect(b.executionTaskList).toEqual([])
  })
})
