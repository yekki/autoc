/**
 * 从 SSE 事件的 task_id 提取纯 ID（处理 "[task-1] 标题" 格式）
 */
export function normalizeTaskId(raw) {
  if (!raw) return ''
  const m = raw.match(/^\[([^\]]+)\]/)
  return m ? m[1] : raw
}

export function findTask(taskList, rawId) {
  const id = normalizeTaskId(rawId)
  return taskList.find((t) => t.id === id || t.id === rawId)
}

/**
 * 验证 localStorage 中的选中项目是否仍存在于后端项目列表中，
 * 防止删除项目后出现"幽灵项目"。
 */
export function validateSelectedProject(projectName, projects) {
  if (!projectName) return null
  const exists = projects.some(p => p.name === projectName || p.folder === projectName)
  if (!exists) {
    localStorage.removeItem('autoc-selected-project')
    return null
  }
  return projectName
}
