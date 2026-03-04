import { create } from 'zustand'
import { EMPTY_STATS } from './helpers/constants'
import { createProjectSlice } from './slices/projectSlice'
import { createExecutionSlice } from './slices/executionSlice'
import { createHistorySlice } from './slices/historySlice'
import { createSseSlice } from './slices/sseSlice'
import { createBenchmarkSlice } from './slices/benchmarkSlice'

// Vite HMR：读取上一轮模块销毁前保存的 store 快照
const _hmrPrevState = import.meta.hot?.data?.zustandState

const useStore = create((set, get) => ({
  // === 项目 ===
  projects: [],
  selectedProjectName: localStorage.getItem('autoc-selected-project') || null,

  // === 视图 === (welcome | workspace | benchmark)
  // S-001 v2.1: workspace 模式要求同时有 selectedProject，避免冷启动直接进空 workspace
  viewMode: (() => {
    const v = localStorage.getItem('autoc-view-mode')
    const hasProject = !!localStorage.getItem('autoc-selected-project')
    if (v === 'benchmark') return 'benchmark'
    if (v === 'workspace' && hasProject) return 'workspace'
    return 'welcome'
  })(),
  activeTab: localStorage.getItem('autoc-active-tab') || 'overview',

  // === 任务选中 ===
  selectedTaskId: null,

  // === 执行 ===
  sessionId: null,
  sseConnection: null,
  executionRequirement: '',
  executionLogs: [],
  executionHistory: [],
  executionStats: { ...EMPTY_STATS },
  executionPlan: null,
  executionPlanMd: '',
  executionFiles: [],
  newlyCreatedFiles: [],
  executionSummary: null,
  executionBugsList: [],
  executionTokenRuns: [],
  executionAgentTokens: null,
  executionTaskList: [],
  executionPreview: null,
  executionRefinerResult: null,
  isRunning: false,

  // 执行进度追踪
  currentPhase: '',
  currentIteration: { round: 0, maxRounds: 0, iteration: 0, maxIterations: 0 },
  iterationHistory: [],
  selectedIteration: null,

  // 沙箱 / PM / Agent 状态
  sandboxStatus: { step: '', message: '', progress: 0, ready: false },
  planningProgress: null,
  agentThinking: null,
  executionFailure: null,

  // 预期版本（redefine/add-feature 时由 SSE 事件设置，用于执行期间的版本显示）
  executionExpectedVersion: '',

  // SSE 新增状态：之前的"沉默事件"
  executionComplexity: '',
  lastDevSelfTest: null,
  smokeCheckIssues: [],
  deployGateStatus: null,
  lastFailureAnalysis: null,
  lastReflection: null,
  planningAcceptanceResult: null,
  lastPmDecision: null,

  // S-002: Planning 确认门状态
  planApprovalPending: false,

  // R-016: 预览健康检查 — 存储预览页检测到的 JS 运行时错误
  previewErrors: [],

  // P0-1: QuickStart 展开触发（由 Header + 按钮 set → WelcomePage 消费）
  quickStartExpanded: false,
  // Bug 修复进度
  fixProgress: {
    status: 'idle',
    currentBug: null,
    current: 0,
    total: 0,
    results: [],
    fixedCount: 0,
    elapsedSeconds: 0,
    verified: null,
  },

  // AI 辅助 token 追踪
  aiAssistTokens: { total: 0, calls: 0, records: [] },

  // === 设置 ===
  settingsOpen: false,
  theme: localStorage.getItem('autoc-theme') || 'dark',
  collapsedSections: JSON.parse(localStorage.getItem('autoc-collapsed-sections') || '{}'),
  isSectionCollapsed: (key, defaultValue = false) => {
    const val = get().collapsedSections[key]
    return val === undefined ? defaultValue : val
  },

  // === 弹窗 ===
  createProjectOpen: false,
  editProjectOpen: false,
  editProjectTarget: null,
  importPRDOpen: false,

  // === 系统状态 ===
  systemConfig: null,
  modelConfig: null,

  // === UI Actions ===

  setTheme: (theme) => {
    localStorage.setItem('autoc-theme', theme)
    set({ theme })
  },

  setSettingsOpen: (open) => set({ settingsOpen: open }),
  setExecutionPlanMd: (md) => set({ executionPlanMd: md }),
  setCreateProjectOpen: (open) => set({ createProjectOpen: open }),
  setImportPRDOpen: (open) => set({ importPRDOpen: open }),
  setActiveTab: (tab) => {
    localStorage.setItem('autoc-active-tab', tab)
    set({ activeTab: tab })
  },
  setSelectedTaskId: (id) => set({ selectedTaskId: id }),
  setSelectedIteration: (iter) => set({ selectedIteration: iter }),
  toggleSectionCollapsed: (key) => {
    const prev = get().collapsedSections
    const next = { ...prev, [key]: !prev[key] }
    localStorage.setItem('autoc-collapsed-sections', JSON.stringify(next))
    set({ collapsedSections: next })
  },
  setSectionCollapsed: (key, value) => {
    const prev = get().collapsedSections
    if (prev[key] === value) return
    const next = { ...prev, [key]: value }
    localStorage.setItem('autoc-collapsed-sections', JSON.stringify(next))
    set({ collapsedSections: next })
  },
  openEditProject: (project) => set({ editProjectOpen: true, editProjectTarget: project }),
  closeEditProject: () => set({ editProjectOpen: false, editProjectTarget: null }),

  recordAiAssistTokens: (tokensUsed, action) => {
    const prev = get().aiAssistTokens
    set({
      aiAssistTokens: {
        total: prev.total + (tokensUsed?.total_tokens || 0),
        calls: prev.calls + 1,
        records: [
          { action, ...tokensUsed, timestamp: new Date().toISOString() },
          ...prev.records,
        ].slice(0, 50),
      },
    })
  },

  // === Slices ===
  ...createProjectSlice(set, get),
  ...createExecutionSlice(set, get),
  ...createHistorySlice(set, get),
  ...createSseSlice(set, get),
  ...createBenchmarkSlice(set, get),
}))

// Vite HMR：模块热替换时保留 store 数据状态，避免页面"闪白"丢数据
if (import.meta.hot) {
  if (_hmrPrevState) {
    const restore = {}
    for (const [key, value] of Object.entries(_hmrPrevState)) {
      if (typeof value !== 'function' && key !== 'sseConnection') {
        restore[key] = value
      }
    }
    useStore.setState(restore)
  }
  import.meta.hot.accept()
  import.meta.hot.dispose((data) => {
    data.zustandState = useStore.getState()
  })
}

export default useStore
