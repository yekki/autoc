/**
 * GLM 模型定价表（USD / 百万 token）
 * 数据来源: https://zhipu-32152247.mintlify.app/guides/overview/pricing
 * 三维定价: input（常规输入）/ cache_read（缓存命中输入）/ output（输出）
 */
export const MODEL_PRICES = {
  'glm-5':        { input: 1.00, cache_read: 0.20, output: 3.20, currency: '$' },
  'glm-5-code':   { input: 1.20, cache_read: 0.30, output: 5.00, currency: '$' },
  'glm-4.7':      { input: 0.60, cache_read: 0.11, output: 2.20, currency: '$' },
  'glm-4.6':      { input: 0.60, cache_read: 0.11, output: 2.20, currency: '$' },
  'glm-4.5':      { input: 0.60, cache_read: 0.11, output: 2.20, currency: '$' },
  'glm-4.5-air':  { input: 0.20, cache_read: 0.03, output: 1.10, currency: '$' },
  'glm-4.7-flash': { input: 0, cache_read: 0, output: 0, currency: '$', free: true },
  'glm-4.5-flash': { input: 0, cache_read: 0, output: 0, currency: '$', free: true },
  'codegeex-4':   { input: 0, cache_read: 0, output: 0, currency: '$', free: true },
}

/**
 * 根据模型名（模糊匹配）查找单价，未知模型返回 fallback
 */
export function findModelPrice(modelName) {
  if (!modelName) return null
  const key = modelName.toLowerCase()
  if (MODEL_PRICES[key]) return { ...MODEL_PRICES[key], model: key }
  const match = Object.keys(MODEL_PRICES).find(k => key.includes(k) || k.includes(key))
  if (match) return { ...MODEL_PRICES[match], model: match }
  return { input: 0.60, cache_read: 0.11, output: 2.20, currency: '$', model: key, note: '默认' }
}

/**
 * 粗略费用估算（仅有 total tokens 时，按 90:10 I/O 比加权）
 */
export function estimateCost(tokens, price) {
  if (!price || !tokens) return null
  if (price.free) return 0
  const estInput = tokens * 0.9
  const estOutput = tokens * 0.1
  return (estInput / 1_000_000) * price.input + (estOutput / 1_000_000) * price.output
}

/**
 * 精确费用计算（含缓存感知）
 * @param {number} promptTokens - 总 prompt tokens（含缓存命中部分）
 * @param {number} completionTokens - completion tokens
 * @param {object} price - 定价对象
 * @param {number} cachedTokens - 缓存命中的 prompt tokens（可选）
 */
export function estimateCostDetailed(promptTokens, completionTokens, price, cachedTokens = 0) {
  if (!price) return null
  if (price.free) return { input: 0, cache: 0, output: 0, total: 0, savings: 0 }

  const uncachedInput = Math.max(0, promptTokens - cachedTokens)
  const inputCost = (uncachedInput / 1_000_000) * price.input
  const cacheCost = (cachedTokens / 1_000_000) * (price.cache_read || price.input)
  const outputCost = (completionTokens / 1_000_000) * price.output
  const savings = cachedTokens > 0
    ? (cachedTokens / 1_000_000) * (price.input - (price.cache_read || price.input))
    : 0

  return {
    input: inputCost,
    cache: cacheCost,
    output: outputCost,
    total: inputCost + cacheCost + outputCost,
    savings,
  }
}

/**
 * 按 Agent 分布精确计算单次执行费用
 * 优先使用 per-agent 模型定价 + I/O 分离数据；兜底用单一模型粗略估算
 * @param {object} run - { total_tokens, prompt_tokens?, completion_tokens?, cached_tokens?, agent_tokens? }
 * @param {object} modelConfig - { active: { helper: {model}, coder: {model}, critique: {model} } }
 */
export function computeRunCost(run, modelConfig) {
  if (!run || !(run.total_tokens > 0)) return 0

  const active = modelConfig?.active || {}
  const agentTk = run.agent_tokens

  if (agentTk) {
    const hasImpl = (agentTk.implementer || 0) > 0
    const agents = [
      { tokens: agentTk.helper || 0, model: active.helper?.model },
      { tokens: hasImpl ? (agentTk.implementer || 0) : (agentTk.coder || agentTk.dev || agentTk.developer || 0), model: active.coder?.model },
      ...(!hasImpl ? [{ tokens: agentTk.critique || agentTk.test || agentTk.tester || 0, model: active.critique?.model }] : []),
    ]
    const totalAg = agents.reduce((s, a) => s + a.tokens, 0)

    if (totalAg > 0) {
      const hasIo = (run.prompt_tokens || 0) > 0
      let total = 0
      for (const a of agents) {
        if (a.tokens <= 0) continue
        const p = findModelPrice(a.model)
        if (!p || p.free) continue
        if (hasIo) {
          const share = a.tokens / totalAg
          const d = estimateCostDetailed(
            Math.round((run.prompt_tokens || 0) * share),
            Math.round((run.completion_tokens || 0) * share),
            p,
            Math.round((run.cached_tokens || 0) * share),
          )
          total += d?.total || 0
        } else {
          total += estimateCost(a.tokens, p) || 0
        }
      }
      if (total > 0) return total
    }
  }

  const primaryModel = active.coder?.model || active.helper?.model || ''
  const price = findModelPrice(primaryModel)
  if (!price || price.free) return 0
  if ((run.prompt_tokens || 0) > 0) {
    return estimateCostDetailed(run.prompt_tokens, run.completion_tokens || 0, price, run.cached_tokens || 0)?.total || 0
  }
  return estimateCost(run.total_tokens || 0, price) || 0
}
