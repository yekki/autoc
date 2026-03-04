import { describe, it, expect, vi, beforeEach } from 'vitest'
import { create } from 'zustand'
import { createProjectSlice } from '../../stores/slices/projectSlice'
import { buildResetState, EMPTY_STATS } from '../../stores/helpers/constants'

vi.mock('../../services/api', () => ({
  fetchProjects: vi.fn(),
  fetchProject: vi.fn(),
  createProject: vi.fn(),
  deleteProject: vi.fn(),
  batchDeleteProjects: vi.fn(),
  updateProject: vi.fn(),
  fetchConfig: vi.fn(),
  fetchModelConfig: vi.fn(),
}))

vi.mock('../../stores/slices/historySlice', () => ({
  invalidateHistoryLoad: vi.fn(),
}))

const api = await import('../../services/api')

function createTestStore(initialState = {}) {
  return create((set, get) => ({
    projects: [],
    selectedProjectName: null,
    viewMode: 'welcome',
    activeTab: 'overview',
    sseConnection: null,
    executionTaskList: [],
    executionStats: { ...EMPTY_STATS },
    ...initialState,
    ...createProjectSlice(set, get),
    loadProjectHistory: vi.fn(),
  }))
}

describe('projectSlice', () => {
  let store

  beforeEach(() => {
    store = createTestStore()
    vi.clearAllMocks()
    localStorage.clear()
  })

  describe('fetchProjects', () => {
    it('loads projects into store', async () => {
      const projects = [
        { name: 'proj-a', folder: 'proj-a' },
        { name: 'proj-b', folder: 'proj-b' },
      ]
      api.fetchProjects.mockResolvedValue(projects)

      const result = await store.getState().fetchProjects()
      expect(result).toEqual(projects)
      expect(store.getState().projects).toEqual(projects)
    })

    it('clears selectedProjectName when project no longer exists', async () => {
      store = createTestStore({ selectedProjectName: 'deleted-proj' })
      api.fetchProjects.mockResolvedValue([{ name: 'other', folder: 'other' }])

      await store.getState().fetchProjects()
      expect(store.getState().selectedProjectName).toBeNull()
      expect(store.getState().viewMode).toBe('welcome')
    })

    it('returns empty array on API error', async () => {
      api.fetchProjects.mockRejectedValue(new Error('Network error'))
      const result = await store.getState().fetchProjects()
      expect(result).toEqual([])
    })

    it('迁移兼容：localStorage 存的是显示名时自动规范化为 folder', async () => {
      // 旧版本 localStorage 存储中文显示名
      store = createTestStore({ selectedProjectName: '你好世界' })
      api.fetchProjects.mockResolvedValue([
        { name: '你好世界', folder: 'ni-hao-shi-jie' },
      ])

      await store.getState().fetchProjects()

      const state = store.getState()
      expect(state.selectedProjectName).toBe('ni-hao-shi-jie')
      expect(localStorage.getItem('autoc-selected-project')).toBe('ni-hao-shi-jie')
    })

    it('项目无 folder 字段时不写入 undefined', async () => {
      store = createTestStore({ selectedProjectName: '无folder项目' })
      api.fetchProjects.mockResolvedValue([
        { name: '无folder项目' }, // 没有 folder 字段
      ])

      await store.getState().fetchProjects()

      const state = store.getState()
      // selectedProjectName 应维持原值不变（validateSelectedProject 允许通过，但不迁移）
      expect(state.selectedProjectName).toBe('无folder项目')
      expect(localStorage.getItem('autoc-selected-project')).not.toBe('undefined')
    })

    it('name 与 folder 相同时不做多余更新', async () => {
      store = createTestStore({ selectedProjectName: 'my-app' })
      api.fetchProjects.mockResolvedValue([
        { name: 'my-app', folder: 'my-app' },
      ])

      await store.getState().fetchProjects()
      expect(store.getState().selectedProjectName).toBe('my-app')
    })
  })

  describe('createProject', () => {
    it('creates project, selects it, switches to workspace', async () => {
      api.createProject.mockResolvedValue({ name: 'new-proj' })
      api.fetchProjects.mockResolvedValue([{ name: 'new-proj', folder: 'new-proj' }])

      await store.getState().createProject({ name: 'new-proj', folder: 'new-proj' })

      const state = store.getState()
      expect(state.selectedProjectName).toBe('new-proj')
      expect(state.viewMode).toBe('workspace')
      expect(state.activeTab).toBe('overview')
      expect(state.createProjectOpen).toBe(false)
      expect(localStorage.getItem('autoc-selected-project')).toBe('new-proj')
      expect(localStorage.getItem('autoc-view-mode')).toBe('workspace')
    })

    it('resets execution state on create', async () => {
      store = createTestStore({
        executionTaskList: [{ id: 'old' }],
        isRunning: true,
      })
      api.createProject.mockResolvedValue({})
      api.fetchProjects.mockResolvedValue([])

      await store.getState().createProject({ name: 'x' })
      expect(store.getState().executionTaskList).toEqual([])
    })
  })

  describe('deleteProject', () => {
    it('deletes project and returns to welcome if currently selected', async () => {
      store = createTestStore({
        selectedProjectName: 'doomed',
        viewMode: 'workspace',
        projects: [{ name: 'doomed', folder: 'doomed' }],
      })
      api.deleteProject.mockResolvedValue({})
      api.fetchProjects.mockResolvedValue([])

      await store.getState().deleteProject('doomed')
      expect(store.getState().selectedProjectName).toBeNull()
      expect(store.getState().viewMode).toBe('welcome')
    })

    it('keeps selection if deleting a different project', async () => {
      store = createTestStore({
        selectedProjectName: 'keep-me',
        projects: [
          { name: 'keep-me', folder: 'keep-me' },
          { name: 'remove', folder: 'remove' },
        ],
      })
      api.deleteProject.mockResolvedValue({})
      api.fetchProjects.mockResolvedValue([{ name: 'keep-me', folder: 'keep-me' }])

      await store.getState().deleteProject('remove')
      expect(store.getState().selectedProjectName).toBe('keep-me')
    })
  })

  describe('batchDeleteProjects', () => {
    it('batch deletes and clears selection if included', async () => {
      store = createTestStore({
        selectedProjectName: 'a',
        projects: [{ name: 'a', folder: 'a' }, { name: 'b', folder: 'b' }],
      })
      api.batchDeleteProjects.mockResolvedValue({ deleted_count: 2 })
      api.fetchProjects.mockResolvedValue([])

      await store.getState().batchDeleteProjects(['a', 'b'])
      expect(store.getState().selectedProjectName).toBeNull()
    })
  })

  describe('selectProject', () => {
    it('switches to workspace and loads history', () => {
      store = createTestStore({
        projects: [{ name: 'my-proj', folder: 'my-proj' }],
      })

      store.getState().selectProject('my-proj')

      const state = store.getState()
      expect(state.selectedProjectName).toBe('my-proj')
      expect(state.viewMode).toBe('workspace')
      expect(state.activeTab).toBe('overview')
      expect(state.loadProjectHistory).toHaveBeenCalledWith('my-proj')
    })

    it('is a no-op if already selected and in workspace', () => {
      store = createTestStore({
        selectedProjectName: 'x',
        viewMode: 'workspace',
      })

      store.getState().selectProject('x')
      expect(store.getState().loadProjectHistory).not.toHaveBeenCalled()
    })
  })

  describe('backToAllProjects', () => {
    it('clears selection and switches to welcome', () => {
      store = createTestStore({
        selectedProjectName: 'proj',
        viewMode: 'workspace',
      })

      store.getState().backToAllProjects()

      expect(store.getState().selectedProjectName).toBeNull()
      expect(store.getState().viewMode).toBe('welcome')
      expect(localStorage.getItem('autoc-selected-project')).toBeNull()
    })
  })

  describe('getSelectedProject', () => {
    it('returns the matching project object', () => {
      const proj = { name: 'found', folder: 'found', description: 'desc' }
      store = createTestStore({
        projects: [proj],
        selectedProjectName: 'found',
      })
      expect(store.getState().getSelectedProject()).toEqual(proj)
    })

    it('returns null when no match', () => {
      store = createTestStore({ selectedProjectName: 'ghost' })
      expect(store.getState().getSelectedProject()).toBeNull()
    })

    it('name ≠ folder 时按 folder 匹配', () => {
      const proj = { name: '你好世界', folder: 'ni-hao-shi-jie', description: '中文项目' }
      store = createTestStore({
        projects: [proj],
        selectedProjectName: 'ni-hao-shi-jie',
      })
      expect(store.getState().getSelectedProject()).toEqual(proj)
    })
  })

  describe('name ≠ folder 场景（中文项目名）', () => {
    const cnProject = { name: '你好世界', folder: 'ni-hao-shi-jie', path: '/ws/ni-hao-shi-jie' }

    it('selectProject 按 folder 切换', () => {
      store = createTestStore({ projects: [cnProject] })
      store.getState().selectProject('ni-hao-shi-jie')

      const state = store.getState()
      expect(state.selectedProjectName).toBe('ni-hao-shi-jie')
      expect(localStorage.getItem('autoc-selected-project')).toBe('ni-hao-shi-jie')
      expect(state.loadProjectHistory).toHaveBeenCalledWith('ni-hao-shi-jie')
    })

    it('deleteProject 按 folder 删除，选中状态正确清理', async () => {
      store = createTestStore({
        selectedProjectName: 'ni-hao-shi-jie',
        projects: [cnProject],
      })
      api.deleteProject.mockResolvedValue({})
      api.fetchProjects.mockResolvedValue([])

      await store.getState().deleteProject('ni-hao-shi-jie')
      expect(store.getState().selectedProjectName).toBeNull()
    })

    it('createProject 返回 folder 时使用 folder 而非 name', async () => {
      api.createProject.mockResolvedValue({ project: { name: '你好世界', folder: 'ni-hao-shi-jie' } })
      api.fetchProjects.mockResolvedValue([cnProject])

      await store.getState().createProject({ name: '你好世界', folder: 'ni-hao-shi-jie' })

      const state = store.getState()
      expect(state.selectedProjectName).toBe('ni-hao-shi-jie')
      expect(localStorage.getItem('autoc-selected-project')).toBe('ni-hao-shi-jie')
    })
  })
})
