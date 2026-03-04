import * as api from '../../services/api'
import { buildResetState } from '../helpers/constants'
import { validateSelectedProject } from '../helpers/taskUtils'
import { invalidateHistoryLoad } from './historySlice'

/** 关闭旧 SSE 连接，防止切换项目后旧事件污染新项目状态 */
function _closeStaleSSE(get) {
  const conn = get().sseConnection
  if (conn) {
    conn.close()
    return { sseConnection: null }
  }
  return {}
}

export const createProjectSlice = (set, get) => ({
  fetchSystemStatus: async () => {
    try {
      const [config, modelCfg] = await Promise.all([
        api.fetchConfig().catch(() => null),
        api.fetchModelConfig().catch(() => null),
      ])
      set({ systemConfig: config, modelConfig: modelCfg })
    } catch (e) {
      console.debug('fetchSystemStatus error:', e)
    }
  },

  fetchProjects: async () => {
    try {
      const projects = await api.fetchProjects()
      const { selectedProjectName } = get()
      const validatedName = validateSelectedProject(selectedProjectName, projects)
      const updates = { projects }
      if (validatedName === null) {
        updates.selectedProjectName = null
        updates.viewMode = 'welcome'
        localStorage.setItem('autoc-view-mode', 'welcome')
      } else {
        // 升级兼容：localStorage 旧存的是显示名（如中文），自动迁移为 folder
        const proj = projects.find(p => p.folder === validatedName || p.name === validatedName)
        if (proj?.folder && proj.folder !== validatedName) {
          updates.selectedProjectName = proj.folder
          localStorage.setItem('autoc-selected-project', proj.folder)
        }
      }
      set(updates)
      return projects
    } catch (e) {
      console.error('fetchProjects error:', e)
      return []
    }
  },

  createProject: async (data) => {
    const result = await api.createProject(data)
    await get().fetchProjects()
    invalidateHistoryLoad()
    const sseCleanup = _closeStaleSSE(get)
    const projectFolder = result?.project?.folder || data.folder || data.name
    localStorage.setItem('autoc-selected-project', projectFolder)
    localStorage.setItem('autoc-view-mode', 'workspace')
    localStorage.setItem('autoc-active-tab', 'overview')
    set(buildResetState({
      ...sseCleanup,
      selectedProjectName: projectFolder,
      viewMode: 'workspace',
      activeTab: 'overview',
      createProjectOpen: false,
      executionTokenRuns: [],
    }))
    return result
  },

  deleteProject: async (name) => {
    await api.deleteProject(name)
    const { selectedProjectName } = get()
    await get().fetchProjects()
    if (selectedProjectName === name) {
      invalidateHistoryLoad()
      const sseCleanup = _closeStaleSSE(get)
      localStorage.removeItem('autoc-selected-project')
      localStorage.setItem('autoc-view-mode', 'welcome')
      set({ ...sseCleanup, selectedProjectName: null, viewMode: 'welcome' })
    }
  },

  batchDeleteProjects: async (names) => {
    const result = await api.batchDeleteProjects(names)
    const { selectedProjectName } = get()
    await get().fetchProjects()
    if (names.includes(selectedProjectName)) {
      invalidateHistoryLoad()
      const sseCleanup = _closeStaleSSE(get)
      localStorage.removeItem('autoc-selected-project')
      localStorage.setItem('autoc-view-mode', 'welcome')
      set({ ...sseCleanup, selectedProjectName: null, viewMode: 'welcome' })
    }
    return result
  },

  editProject: async (projectFolder, data) => {
    const result = await api.updateProject(projectFolder, data)
    await get().fetchProjects()
    set({ editProjectOpen: false, editProjectTarget: null })
  },

  backToAllProjects: () => {
    invalidateHistoryLoad()
    const sseCleanup = _closeStaleSSE(get)
    localStorage.removeItem('autoc-selected-project')
    localStorage.setItem('autoc-view-mode', 'welcome')
    set({ ...sseCleanup, selectedProjectName: null, viewMode: 'welcome' })
  },

  selectProject: (name) => {
    const { selectedProjectName, viewMode } = get()
    if (name === selectedProjectName && viewMode === 'workspace') return
    const sseCleanup = _closeStaleSSE(get)
    localStorage.setItem('autoc-selected-project', name)
    localStorage.setItem('autoc-view-mode', 'workspace')
    localStorage.setItem('autoc-active-tab', 'overview')
    set(buildResetState({
      ...sseCleanup,
      selectedProjectName: name,
      viewMode: 'workspace',
      activeTab: 'overview',
      executionTokenRuns: [],
    }))
    get().loadProjectHistory(name)
  },

  getSelectedProject: () => {
    const { projects, selectedProjectName } = get()
    return projects.find((p) => p.folder === selectedProjectName) || null
  },
})
