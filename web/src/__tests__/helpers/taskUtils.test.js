import { describe, it, expect } from 'vitest'
import { normalizeTaskId, findTask, validateSelectedProject } from '../../stores/helpers/taskUtils'

describe('normalizeTaskId', () => {
  it('extracts id from "[task-1] 标题" format', () => {
    expect(normalizeTaskId('[task-1] 实现登录')).toBe('task-1')
  })

  it('returns raw id when no brackets', () => {
    expect(normalizeTaskId('task-2')).toBe('task-2')
  })

  it('returns empty string for falsy input', () => {
    expect(normalizeTaskId(null)).toBe('')
    expect(normalizeTaskId(undefined)).toBe('')
    expect(normalizeTaskId('')).toBe('')
  })

  it('handles nested brackets by matching first pair', () => {
    expect(normalizeTaskId('[a-1] [extra] stuff')).toBe('a-1')
  })
})

describe('findTask', () => {
  const tasks = [
    { id: 'task-1', title: 'First' },
    { id: 'task-2', title: 'Second' },
  ]

  it('finds by normalized id', () => {
    expect(findTask(tasks, '[task-1] 实现登录')).toBe(tasks[0])
  })

  it('finds by raw id', () => {
    expect(findTask(tasks, 'task-2')).toBe(tasks[1])
  })

  it('returns undefined when not found', () => {
    expect(findTask(tasks, 'task-99')).toBeUndefined()
  })

  it('returns undefined for empty list', () => {
    expect(findTask([], 'task-1')).toBeUndefined()
  })
})

describe('validateSelectedProject', () => {
  const projects = [
    { name: 'proj-a', folder: 'proj-a' },
    { name: 'proj-b', folder: 'folder-b' },
  ]

  it('returns project name when it exists by name', () => {
    expect(validateSelectedProject('proj-a', projects)).toBe('proj-a')
  })

  it('returns project name when it exists by folder', () => {
    expect(validateSelectedProject('folder-b', projects)).toBe('folder-b')
  })

  it('returns null and clears localStorage for non-existent project', () => {
    localStorage.setItem('autoc-selected-project', 'ghost')
    const result = validateSelectedProject('ghost', projects)
    expect(result).toBeNull()
    expect(localStorage.getItem('autoc-selected-project')).toBeNull()
  })

  it('returns null for falsy input', () => {
    expect(validateSelectedProject(null, projects)).toBeNull()
    expect(validateSelectedProject('', projects)).toBeNull()
  })
})
