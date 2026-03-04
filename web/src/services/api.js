const BASE = '/api/v1'

async function request(url, options = {}) {
  const res = await fetch(`${BASE}${url}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || err.error || `HTTP ${res.status}`)
  }
  return res.json()
}

// 项目
export const fetchProjects = () => request('/projects?detail=true')
export const fetchProject = (name) => request(`/projects/${encodeURIComponent(name)}`)
export const fetchProjectVersions = (name) => request(`/projects/${encodeURIComponent(name)}/versions`)
export const createProject = (data) =>
  request('/projects', { method: 'POST', body: JSON.stringify(data) })
export const updateProject = (name, data) =>
  request(`/projects/${encodeURIComponent(name)}`, { method: 'PATCH', body: JSON.stringify(data) })
export const deleteProject = (name) =>
  request(`/projects/${encodeURIComponent(name)}`, { method: 'DELETE' })
export const batchDeleteProjects = (names) =>
  request('/projects/batch-delete', { method: 'POST', body: JSON.stringify({ names }) })
// 项目操作（二层架构：直接操作项目，不再有 requirement ID）
export const resumeProject = (projectName) =>
  request(`/projects/${encodeURIComponent(projectName)}/resume`, { method: 'POST' })
export const quickFixBugs = (projectName, { bugIds, bugTitles, bugs } = {}) =>
  request(`/projects/${encodeURIComponent(projectName)}/quick-fix`, {
    method: 'POST',
    body: JSON.stringify({
      ...(bugIds ? { bug_ids: bugIds } : {}),
      ...(bugTitles ? { bug_titles: bugTitles } : {}),
      ...(bugs ? { bugs } : {}),
    }),
  })
export const redefineProject = (projectName, { requirement } = {}) =>
  request(`/projects/${encodeURIComponent(projectName)}/redefine`, {
    method: 'POST',
    body: JSON.stringify({ requirement }),
  })
export const addFeature = (projectName, { requirement } = {}) =>
  request(`/projects/${encodeURIComponent(projectName)}/add-feature`, {
    method: 'POST',
    body: JSON.stringify({ requirement }),
  })
// 会话
export const fetchSessions = () => request('/sessions')
export const fetchSessionEvents = (sessionId) => request(`/sessions/${sessionId}/events`)
export const clearSessions = (onlyFinished = true) =>
  request('/sessions', { method: 'DELETE', body: JSON.stringify({ only_finished: onlyFinished }) })
export const deleteSession = (sessionId) =>
  request(`/sessions/${sessionId}`, { method: 'DELETE' })

// 执行
export const startRun = (data) =>
  request('/run', { method: 'POST', body: JSON.stringify(data) })
export const stopRun = (sessionId) =>
  request(`/stop/${sessionId}`, { method: 'POST' })

// S-001: 首屏一步启动（创建项目 + 立即执行）
export const quickStart = (data) =>
  request('/quick-start', { method: 'POST', body: JSON.stringify(data) })

// S-002: Planning 确认门
export const approvePlan = (sessionId, { approved, feedback = '' } = {}) =>
  request(`/sessions/${encodeURIComponent(sessionId)}/approve-plan`, {
    method: 'POST',
    body: JSON.stringify({ approved, feedback }),
  })

// 文件
export const fetchFile = (sessionId, path) =>
  request(`/file/${sessionId}?path=${encodeURIComponent(path)}`)
export const fetchProjectFile = (projectName, path) =>
  request(`/projects/${encodeURIComponent(projectName)}/file?path=${encodeURIComponent(path)}`)
export const saveProjectFile = (projectName, path, content) =>
  request(`/projects/${encodeURIComponent(projectName)}/file`, {
    method: 'PUT',
    body: JSON.stringify({ path, content }),
  })

// 需求评估
export const refineRequirement = (data) =>
  request('/refine', { method: 'POST', body: JSON.stringify(data) })

// AI 辅助（描述润色 / 技术栈推荐）
export const aiAssist = (data) =>
  request('/ai-assist', { method: 'POST', body: JSON.stringify(data) })

// 里程碑
export const addMilestone = (projectName, data) =>
  request(`/projects/${encodeURIComponent(projectName)}/milestone`, {
    method: 'POST', body: JSON.stringify(data),
  })

// 预览
export const detectPreviewType = (projectName) =>
  request(`/projects/${encodeURIComponent(projectName)}/preview/detect`)
export const startPreview = (projectName) =>
  request(`/projects/${encodeURIComponent(projectName)}/preview/start`, { method: 'POST' })
export const stopPreview = (projectName) =>
  request(`/projects/${encodeURIComponent(projectName)}/preview/stop`, { method: 'POST' })
export const restartPreview = (projectName) =>
  request(`/projects/${encodeURIComponent(projectName)}/preview/restart`, { method: 'POST' })

// 项目环境变量
export const fetchProjectEnv = (projectName) =>
  request(`/projects/${encodeURIComponent(projectName)}/env`)
export const saveProjectEnv = (projectName, envVars) =>
  request(`/projects/${encodeURIComponent(projectName)}/env`, {
    method: 'PUT', body: JSON.stringify({ env_vars: envVars }),
  })

// 沙箱
export const fetchSandboxStatus = () => request('/sandbox/status')
export const stopSandbox = (name) =>
  request(`/sandbox/${encodeURIComponent(name)}/stop`, { method: 'POST' })

// 工具
export const deployProject = (projectName, opts = {}) =>
  request(`/projects/${encodeURIComponent(projectName)}/deploy`, {
    method: 'POST', body: JSON.stringify(opts),
  })
export const generateDocs = (projectName) =>
  request(`/projects/${encodeURIComponent(projectName)}/docs`, { method: 'POST' })
export const fetchInsights = (requirement = '') =>
  request(`/insights${requirement ? `?requirement=${encodeURIComponent(requirement)}` : ''}`)
export const importPRD = (data) =>
  request('/import-prd', { method: 'POST', body: JSON.stringify(data) })

// Benchmark
export const fetchBenchmarkHistory = () => request('/benchmark/history')
export const fetchBenchmarkRun = (tag) => request(`/benchmark/runs/${encodeURIComponent(tag)}`)
export const fetchBenchmarkCompare = (tagA, tagB) =>
  request(`/benchmark/compare/${encodeURIComponent(tagA)}/${encodeURIComponent(tagB)}`)
export const fetchBenchmarkCases = () => request('/benchmark/cases')
export const createBenchmarkCase = (data) =>
  request('/benchmark/cases', { method: 'POST', body: JSON.stringify(data) })
export const updateBenchmarkCase = (name, data) =>
  request(`/benchmark/cases/${encodeURIComponent(name)}`, { method: 'PUT', body: JSON.stringify(data) })
export const deleteBenchmarkCase = (name) =>
  request(`/benchmark/cases/${encodeURIComponent(name)}`, { method: 'DELETE' })
export const deleteBenchmarkRun = (tag) =>
  request(`/benchmark/runs/${encodeURIComponent(tag)}`, { method: 'DELETE' })
export const startBenchmarkRun = (config) => {
  const params = new URLSearchParams()
  params.set('tag', config.tag)
  if (config.cases) params.set('cases', config.cases)
  if (config.description) params.set('description', config.description)
  if (config.critique) params.set('critique', 'true')
  if (config.timeout) params.set('timeout', String(config.timeout))
  if (config.repeat) params.set('repeat', String(config.repeat))
  if (config.force) params.set('force', 'true')
  if (config.workers && config.workers > 1) params.set('workers', String(config.workers))
  return request(`/benchmark/run?${params}`, { method: 'POST' })
}
export const fetchRunningBenchmarks = () => request('/benchmark/running')
export const subscribeLiveBenchmark = (tag) =>
  fetch(`${BASE}/benchmark/live/${encodeURIComponent(tag)}`)

// 系统
export const fetchConfig = () => request('/config')
export const fetchCapabilities = () => request('/capabilities')

// 设置
export const fetchProviders = () => request('/providers')
export const fetchModelConfig = () => request('/model-config')
export const saveModelConfig = (data) =>
  request('/model-config', { method: 'PUT', body: JSON.stringify(data) })
export const testModel = (data) =>
  request('/test-model', { method: 'POST', body: JSON.stringify(data) })
