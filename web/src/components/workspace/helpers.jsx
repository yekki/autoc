import {
  FolderOutlined, FileOutlined,
  BugOutlined, ExperimentOutlined, ScissorOutlined,
  BulbOutlined, PlayCircleOutlined, SettingOutlined,
} from '@ant-design/icons'

/**
 * 从文件路径列表构建 Ant Design Tree 所需的树形数据结构
 */
export function buildFileTree(files) {
  const root = { children: {} }
  for (const fp of files) {
    const parts = fp.split('/')
    let node = root
    for (let i = 0; i < parts.length; i++) {
      const p = parts[i]
      if (!node.children[p]) {
        node.children[p] = {
          children: {},
          isFile: i === parts.length - 1,
          path: parts.slice(0, i + 1).join('/'),
        }
      }
      node = node.children[p]
    }
  }
  function toAntData(map) {
    return Object.entries(map)
      .map(([name, n]) => ({
        title: name,
        key: n.path,
        icon: n.isFile ? <FileOutlined /> : <FolderOutlined />,
        isLeaf: n.isFile,
        children: Object.keys(n.children).length ? toAntData(n.children) : undefined,
      }))
      .sort((a, b) => (a.isLeaf === b.isLeaf ? a.title.localeCompare(b.title) : a.isLeaf ? 1 : -1))
  }
  return toAntData(root.children)
}

/**
 * 格式化 token 数量：超过 1000 显示 K，超过 1M 显示 M
 */
export function formatTokenCount(n) {
  if (!n) return '0'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return n.toLocaleString()
}

/**
 * 根据执行结果分析失败原因并给出操作建议
 * 返回 { tips, actions, tasksCompleted, tasksTotal, failedIters, totalIters }
 */
export function analyzeFailure(executionSummary, executionTaskList, executionBugsList, iterationHistory) {
  const summary = executionSummary || {}
  const tasksTotal = summary.tasks_total || executionTaskList.length || 0
  const tasksCompleted = summary.tasks_completed || executionTaskList.filter(t => t.status === 'completed' || t.status === 'verified').length
  const tasksVerified = summary.tasks_verified || executionTaskList.filter(t => t.passes).length
  const tasksBlocked = summary.tasks_blocked || 0
  const bugsOpen = summary.bugs_open || executionBugsList.length || 0
  const totalTokens = summary.total_tokens || 0

  const failedIters = (iterationHistory || []).filter(i => i.success === false)
  const totalIters = (iterationHistory || []).length

  const tips = []
  const actions = []

  if (tasksCompleted === 0) {
    actions.push('retry')
    if (tasksTotal >= 3) {
      tips.push({ icon: <ScissorOutlined />, text: '需求涉及多个任务且全部未完成，建议拆分为更小的需求分步实现' })
    }
    if (tasksTotal === 0) {
      tips.push({ icon: <PlayCircleOutlined />, text: '执行在启动阶段失败，点击「重试」再试一次' })
    } else {
      tips.push({ icon: <ExperimentOutlined />, text: '尝试使用更强的模型（如 Claude / GPT-4），可在设置中切换' })
      tips.push({ icon: <BulbOutlined />, text: '在左侧需求框中简化描述，聚焦核心功能后重新运行' })
    }
    actions.push('settings')
  } else if (tasksCompleted > 0 && tasksCompleted < tasksTotal) {
    tips.push({ icon: <BulbOutlined />, text: `${tasksCompleted}/${tasksTotal} 任务已完成，可针对未完成部分单独提需求` })
    if (bugsOpen > 0) {
      tips.push({ icon: <BugOutlined />, text: `有 ${bugsOpen} 个未修复缺陷，尝试「全部修复」让 AI 自动处理` })
      actions.push('fix')
    }
    actions.push('resume')
    actions.push('retry')
    actions.push('cleanRetry')
  }

  if (bugsOpen > 0 && !actions.includes('fix')) {
    tips.push({ icon: <BugOutlined />, text: `有 ${bugsOpen} 个未修复缺陷，建议先修复再重跑测试` })
    actions.push('fix')
  }

  if (tasksBlocked > 0) {
    tips.push({ icon: <SettingOutlined />, text: `${tasksBlocked} 个任务被阻塞，可能是环境问题，检查终端页中的容器状态` })
    actions.push('terminal')
  }

  if (failedIters.length > 0 && totalIters > 0) {
    const devFailed = failedIters.filter(i => i.phase === 'dev').length
    if (devFailed > 0 && devFailed === failedIters.length) {
      tips.push({ icon: <ExperimentOutlined />, text: '多次迭代均在代码生成阶段失败，重跑测试不会有效，建议调整需求或模型' })
    }
  }

  if (totalTokens > 200_000 && tasksVerified === 0) {
    tips.push({ icon: <BulbOutlined />, text: '消耗较高但无有效产出，建议简化需求降低复杂度' })
  }

  if (tips.length === 0) {
    tips.push({ icon: <BulbOutlined />, text: '可以在左侧调整需求描述后重新运行，或尝试不同的模型配置' })
    actions.push('retry')
  }

  if (!actions.includes('retry')) actions.push('retry')
  if (!actions.includes('settings')) actions.push('settings')
  if (!actions.includes('history')) actions.push('history')

  return { tips, actions, tasksCompleted, tasksTotal, failedIters: failedIters.length, totalIters }
}
