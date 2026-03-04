import * as api from '../../services/api'

async function _consumeSSE(res, set, get) {
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          const event = JSON.parse(line.slice(6))
          if (event.type === 'heartbeat') continue
          set((s) => {
            const prevEvents = s.benchmarkRunProgress?.events || []
            // 保留最近 500 条，防止长时间运行导致内存无限增长
            const nextEvents = prevEvents.length >= 500
              ? [...prevEvents.slice(-499), event]
              : [...prevEvents, event]
            return {
              benchmarkRunProgress: {
                ...s.benchmarkRunProgress,
                status: event.type,
                events: nextEvents,
                lastEvent: event,
              },
            }
          })
        } catch { /* skip malformed */ }
      }
    }
  }
}

export const createBenchmarkSlice = (set, get) => ({
  benchmarkHistory: [],
  benchmarkDetail: null,
  benchmarkCompare: null,
  benchmarkCases: [],
  // 是否正在跟踪某个 benchmark（CLI 或 Web 发起均适用）
  benchmarkRunning: false,
  benchmarkRunProgress: null,
  benchmarkTrackedTag: null,
  _benchmarkFailedTag: null,
  // 刚完成的 tag + 时间戳，防止 writer.finish() 删文件前被误判为新运行再次订阅
  _benchmarkCompletedTag: null,
  // 控制进度抽屉开关（slice 可主动打开，供自动订阅场景使用）
  benchmarkDrawerOpen: false,
  benchmarkActiveTab: 'dashboard',
  benchmarkSelectedTags: [],
  // 轮询到的运行中列表（用于 Dashboard 展示）
  benchmarkRunningRuns: [],

  setBenchmarkActiveTab: (tab) => set({ benchmarkActiveTab: tab }),
  setBenchmarkDrawerOpen: (v) => set({ benchmarkDrawerOpen: v }),

  navigateToBenchmark: () => {
    localStorage.setItem('autoc-view-mode', 'benchmark')
    set({ viewMode: 'benchmark' })
  },

  backFromBenchmark: () => {
    localStorage.setItem('autoc-view-mode', 'welcome')
    set({ viewMode: 'welcome', benchmarkDetail: null, benchmarkCompare: null })
  },

  fetchBenchmarkHistory: async () => {
    try {
      const data = await api.fetchBenchmarkHistory()
      set({ benchmarkHistory: data.runs || [] })
    } catch (e) {
      console.error('[Benchmark] fetch history failed:', e)
    }
  },

  fetchBenchmarkDetail: async (tag) => {
    try {
      const data = await api.fetchBenchmarkRun(tag)
      set({ benchmarkDetail: data, benchmarkActiveTab: 'detail' })
    } catch (e) {
      console.error('[Benchmark] fetch detail failed:', e)
    }
  },

  fetchBenchmarkCompare: async (tagA, tagB) => {
    try {
      const data = await api.fetchBenchmarkCompare(tagA, tagB)
      set({ benchmarkCompare: data, benchmarkActiveTab: 'compare' })
    } catch (e) {
      console.error('[Benchmark] fetch compare failed:', e)
    }
  },

  fetchBenchmarkCases: async () => {
    try {
      const data = await api.fetchBenchmarkCases()
      set({ benchmarkCases: data.cases || [] })
      return data
    } catch (e) {
      console.error('[Benchmark] fetch cases failed:', e)
    }
  },

  createBenchmarkCase: async (caseData) => {
    const res = await api.createBenchmarkCase(caseData)
    await get().fetchBenchmarkCases()
    return res
  },

  updateBenchmarkCase: async (name, caseData) => {
    const res = await api.updateBenchmarkCase(name, caseData)
    await get().fetchBenchmarkCases()
    return res
  },

  deleteBenchmarkCase: async (name) => {
    const res = await api.deleteBenchmarkCase(name)
    await get().fetchBenchmarkCases()
    return res
  },

  deleteBenchmarkRun: async (tag) => {
    await api.deleteBenchmarkRun(tag)
    set((s) => ({
      benchmarkHistory: s.benchmarkHistory.filter((r) => r.tag !== tag),
      benchmarkDetail: s.benchmarkDetail?.tag === tag ? null : s.benchmarkDetail,
    }))
  },

  // Web 发起：POST 启动后走统一的 live/{tag} 订阅路径（与 CLI 发起完全一致）
  startBenchmarkRun: async (config) => {
    try {
      const { tag } = await api.startBenchmarkRun(config)
      // 统一走 subscribeLiveBenchmark，与 CLI 发起路径相同
      await get().subscribeLiveBenchmark(tag)
    } catch (e) {
      // 启动失败（如 tag 已存在 409）
      set({
        benchmarkRunning: false,
        benchmarkRunProgress: { status: 'error', error: e.message, events: [] },
        benchmarkTrackedTag: null,
      })
      throw e
    }
  },

  fetchRunningBenchmarks: async () => {
    try {
      const data = await api.fetchRunningBenchmarks()
      const running = data.running || []
      set({ benchmarkRunningRuns: running })

      // 自动感知：发现未跟踪的运行中 benchmark → 自动订阅，无需用户操作
      const { benchmarkRunning, benchmarkTrackedTag, _benchmarkFailedTag, _benchmarkCompletedTag } = get()
      if (!benchmarkRunning && running.length > 0) {
        const now = Date.now()
        const untracked = running.filter((r) => {
          if (r.tag === benchmarkTrackedTag) return false
          // 刚完成的 tag 静默 10s，等后台线程 writer.finish() 删干净文件
          if (_benchmarkCompletedTag && _benchmarkCompletedTag.tag === r.tag
              && now - _benchmarkCompletedTag.at < 10_000) return false
          // 30 秒内订阅失败过的 tag 不重试，防止无限循环
          if (_benchmarkFailedTag && _benchmarkFailedTag.tag === r.tag
              && now - _benchmarkFailedTag.at < 30_000) return false
          return true
        })
        if (untracked.length > 0) {
          // 加 .catch() 防止 unhandled promise rejection
          get().subscribeLiveBenchmark(untracked[0].tag).catch(() => {})
        }
      }

      return running
    } catch (e) {
      console.error('[Benchmark] fetch running failed:', e)
      return []
    }
  },

  // 统一订阅入口：CLI 和 Web 发起的 benchmark 都走这里
  subscribeLiveBenchmark: async (tag) => {
    // 防止重复订阅同一个 tag
    if (get().benchmarkTrackedTag === tag && get().benchmarkRunning) return

    set({
      benchmarkRunning: true,
      benchmarkTrackedTag: tag,
      benchmarkRunProgress: { status: 'starting', events: [], tag },
      benchmarkDrawerOpen: true,
    })
    try {
      const res = await api.subscribeLiveBenchmark(tag)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      await _consumeSSE(res, set, get)
      set({
        benchmarkRunning: false,
        benchmarkTrackedTag: null,
        // 记录刚完成的 tag，防止 writer.finish() 删文件前被误判为新运行
        _benchmarkCompletedTag: { tag, at: Date.now() },
      })
      // 运行结束后自动刷新历史和 running 列表
      await get().fetchRunningBenchmarks()
      await get().fetchBenchmarkHistory()
    } catch (e) {
      const prev = get().benchmarkRunProgress
      const hadProgress = prev?.events?.length > 0
      if (hadProgress) {
        set({
          benchmarkRunning: false,
          benchmarkTrackedTag: null,
          benchmarkRunProgress: { ...prev, status: 'disconnected', disconnectError: e.message },
        })
      } else {
        set({
          benchmarkRunning: false,
          benchmarkTrackedTag: null,
          benchmarkRunProgress: { status: 'error', error: e.message, events: [] },
          _benchmarkFailedTag: { tag, at: Date.now() },
        })
      }
    }
  },

  toggleBenchmarkSelect: (tag) => {
    set((s) => {
      const tags = [...s.benchmarkSelectedTags]
      const idx = tags.indexOf(tag)
      if (idx >= 0) tags.splice(idx, 1)
      else if (tags.length < 2) tags.push(tag)
      return { benchmarkSelectedTags: tags }
    })
  },

  clearBenchmarkSelect: () => set({ benchmarkSelectedTags: [] }),

  setBenchmarkProgress: (progress) => set({ benchmarkRunProgress: progress }),
})
