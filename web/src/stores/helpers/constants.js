export const EMPTY_STATS = {
  tasks: { completed: 0, total: 0, verified: 0 },
  tests: { passed: 0, total: 0 },
  bugs: 0,
  files: 0,
  tokens: 0,
  elapsed: 0,
}

/** 执行状态重置模板（供 createProject / selectProject / startExecution 等复用）
 *  注意：executionTokenRuns 是项目级历史累积数据，不在此处清空。
 *  切换项目时由 selectProject 显式传入 executionTokenRuns: [] 清空。 */
export function buildResetState(overrides = {}) {
  return {
    executionTaskList: [],
    executionStats: { ...EMPTY_STATS },
    executionAgentTokens: null,
    executionBugsList: [],
    executionSummary: null,
    executionPlan: null,
    executionPlanMd: '',
    executionFiles: [],
    newlyCreatedFiles: [],
    executionFailure: null,
    executionRefinerResult: null,
    executionPreview: null,
    executionLogs: [],
    executionHistory: [],
    executionRequirement: '',
    currentPhase: '',
    pipelineStage: '',
    currentIteration: { round: 0, maxRounds: 0, iteration: 0, maxIterations: 0 },
    iterationHistory: [],
    selectedIteration: null,
    sandboxStatus: { step: '', message: '', progress: 0, ready: false },
    planningProgress: null,
    agentThinking: null,
    isRunning: false,
    sessionId: null,
    executionComplexity: '',
    lastDevSelfTest: null,
    smokeCheckIssues: [],
    deployGateStatus: null,
    lastFailureAnalysis: null,
    lastReflection: null,
    planningAcceptanceResult: null,
    lastPmDecision: null,
    planApprovalPending: false,
    previewErrors: [],
    executionExpectedVersion: '',
    fixProgress: {
      status: 'idle', currentBug: null, current: 0, total: 0,
      results: [], fixedCount: 0, elapsedSeconds: 0, verified: null,
    },
    ...overrides,
  }
}
