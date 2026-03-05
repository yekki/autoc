import { Card, Row, Col, Statistic, Empty, Tag, Tooltip } from 'antd'
import { ThunderboltOutlined, SaveOutlined } from '@ant-design/icons'
import useStore from '../../stores/useStore'
import { formatTokenCount } from './helpers'
import { findModelPrice, estimateCostDetailed, computeRunCost } from '../../constants/modelPricing'

/* ---- 口径标签 ---- */

const SCOPE_MAP = {
  current: { color: 'blue', text: '本次' },
  cumulative: { color: 'default', text: '累计' },
  'non-exec': { color: 'purple', text: '非执行' },
}

function ScopeTag({ type }) {
  const cfg = SCOPE_MAP[type]
  if (!cfg) return null
  return <Tag color={cfg.color} style={{ fontSize: 10, margin: '0 0 0 6px', padding: '0 4px', lineHeight: '16px' }}>{cfg.text}</Tag>
}

/* ---- 百分比分配（largest remainder，保证加和 100%） ---- */

function roundPercents(values) {
  const total = values.reduce((s, v) => s + v, 0)
  if (total <= 0) return values.map(() => 0)
  const exact = values.map(v => (v / total) * 100)
  const floored = exact.map(v => Math.floor(v))
  let rem = 100 - floored.reduce((s, v) => s + v, 0)
  const order = [...exact.keys()].sort((a, b) => (exact[b] - floored[b]) - (exact[a] - floored[a]))
  for (let i = 0; i < rem; i++) floored[order[i]]++
  return floored
}

/* ---- 缓存节省卡片 ---- */

function CacheSavingsCard({ promptTokens, cachedTokens, model, isDark }) {
  if (!cachedTokens || cachedTokens <= 0) return null

  const price = findModelPrice(model)
  const cacheHitPct = promptTokens > 0 ? Math.min(100, Math.round(cachedTokens / promptTokens * 100)) : 0
  const savings = price && !price.free
    ? (cachedTokens / 1_000_000) * (price.input - (price.cache_read || 0))
    : 0

  return (
    <Card
      size="small"
      title={
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          <SaveOutlined style={{ color: '#3fb950' }} />
          Prompt Caching 节省
          <ScopeTag type="current" />
          <Tag color="green" style={{ fontSize: 10, margin: 0, padding: '0 4px', lineHeight: '16px' }}>
            命中 {cacheHitPct}%
          </Tag>
        </span>
      }
      style={{ marginTop: 16 }}
    >
      <Row gutter={[8, 12]}>
        <Col span={8}>
          <Statistic
            title={<span style={{ fontSize: 11 }}>缓存命中</span>}
            value={formatTokenCount(cachedTokens)}
            valueStyle={{ fontSize: 18, color: '#3fb950' }}
          />
        </Col>
        <Col span={8}>
          <Statistic
            title={<span style={{ fontSize: 11 }}>新输入</span>}
            value={formatTokenCount(Math.max(0, promptTokens - cachedTokens))}
            valueStyle={{ fontSize: 18 }}
          />
        </Col>
        <Col span={8}>
          <Statistic
            title={<span style={{ fontSize: 11 }}>节省费用</span>}
            value={savings > 0 ? `$${savings.toFixed(4)}` : '-'}
            valueStyle={{ fontSize: 18, color: '#3fb950' }}
          />
        </Col>
      </Row>
      <div style={{
        marginTop: 10, height: 8, borderRadius: 4, overflow: 'hidden',
        display: 'flex', gap: 1, background: isDark ? '#21262d' : '#e8e8e8',
      }}>
        <Tooltip title={`缓存命中: ${formatTokenCount(cachedTokens)} (${cacheHitPct}%)`}>
          <div style={{
            flex: cachedTokens, background: '#3fb950', borderRadius: '4px 0 0 4px',
            transition: 'flex 0.3s',
          }} />
        </Tooltip>
        <Tooltip title={`新输入: ${formatTokenCount(Math.max(0, promptTokens - cachedTokens))}`}>
          <div style={{
            flex: Math.max(0, promptTokens - cachedTokens), background: '#58a6ff',
            borderRadius: '0 4px 4px 0', transition: 'flex 0.3s',
          }} />
        </Tooltip>
      </div>
      <div style={{ marginTop: 6, fontSize: 11, color: isDark ? '#6e7681' : '#8c959f' }}>
        GLM Prompt Caching: 缓存命中的 Token 仅收取约 20% 的输入价格
      </div>
    </Card>
  )
}

/* ---- 模型单价与估算卡片 ---- */

function ModelPricingCard({ agentTokens, helperTokens, devTokens, testTokens, promptTokens, completionTokens, cachedTokens, isDark }) {
  const modelConfig = useStore(s => s.modelConfig)
  const active = modelConfig?.active || {}

  const effectiveHelper = agentTokens?.helper || helperTokens || 0
  const hasImplementer = (agentTokens?.implementer || 0) > 0
  const effectiveDev = hasImplementer ? (agentTokens?.implementer || 0) : (agentTokens?.coder || devTokens || 0)
  const effectiveTest = hasImplementer ? 0 : (agentTokens?.critique || testTokens || 0)
  const totalAgentTokens = effectiveHelper + effectiveDev + effectiveTest

  const agents = [
    { key: 'helper', label: '辅助 AI', model: active.helper?.model, tokens: effectiveHelper, color: '#58a6ff' },
    { key: 'coder', label: hasImplementer ? '实现' : 'Coder AI', model: active.coder?.model, tokens: effectiveDev, color: '#3fb950' },
    ...(!hasImplementer ? [{ key: 'critique', label: 'Critique AI', model: active.critique?.model, tokens: effectiveTest, color: '#d29922' }] : []),
  ]

  const hasIo = promptTokens > 0 && completionTokens > 0

  const rows = agents.map(a => {
    const price = findModelPrice(a.model)
    let cost = null
    if (hasIo && totalAgentTokens > 0 && a.tokens > 0) {
      const share = a.tokens / totalAgentTokens
      const d = estimateCostDetailed(
        Math.round(promptTokens * share),
        Math.round(completionTokens * share),
        price,
        Math.round(cachedTokens * share),
      )
      cost = d?.total ?? null
    } else if (a.tokens > 0) {
      const d = estimateCostDetailed(
        Math.round(a.tokens * 0.9),
        Math.round(a.tokens * 0.1),
        price,
      )
      cost = d?.total ?? null
    }
    return { ...a, price, cost }
  })

  const totalCost = rows.reduce((sum, r) => sum + (r.cost || 0), 0)
  const borderColor = isDark ? '#21262d' : '#e8e8e8'

  return (
    <Card size="small" title={<span>模型单价与估算 <ScopeTag type="current" /></span>} style={{ marginTop: 16 }}>
      <div style={{ fontSize: 12 }}>
        <div style={{
          display: 'grid', gridTemplateColumns: '80px 1fr 120px 80px 80px',
          gap: 0, fontWeight: 600, color: isDark ? '#8b949e' : '#656d76',
          borderBottom: `1px solid ${borderColor}`, padding: '4px 0 6px',
        }}>
          <span>智能体</span><span>模型</span><span>单价 ($/M Token)</span><span>消耗</span><span>估算费用</span>
        </div>
        {rows.map(r => (
          <div key={r.key} style={{
            display: 'grid', gridTemplateColumns: '80px 1fr 120px 80px 80px',
            gap: 0, padding: '6px 0', borderBottom: `1px solid ${borderColor}`,
            color: isDark ? '#c9d1d9' : '#1f2328',
          }}>
            <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: r.color, display: 'inline-block' }} />
              {r.label}
            </span>
            <span style={{ fontFamily: 'monospace', fontSize: 11 }}>
              {r.model || '-'}
              {r.price?.free && <Tag color="green" style={{ fontSize: 9, margin: '0 0 0 4px', padding: '0 3px', lineHeight: '14px' }}>免费</Tag>}
              {r.price?.note && <Tag color="orange" style={{ fontSize: 9, margin: '0 0 0 4px', padding: '0 3px', lineHeight: '14px' }}>{r.price.note}</Tag>}
            </span>
            <Tooltip title={r.price && !r.price.free ? `输入 $${r.price.input} / 缓存 $${r.price.cache_read} / 输出 $${r.price.output}` : ''}>
              <span style={{ color: isDark ? '#8b949e' : '#656d76', fontSize: 11, cursor: 'default' }}>
                {r.price ? (r.price.free ? '免费' : `$${r.price.input} / $${r.price.output}`) : '-'}
              </span>
            </Tooltip>
            <span style={{ fontVariantNumeric: 'tabular-nums', fontSize: 11 }}>
              {r.tokens > 0 ? `${(r.tokens / 1000).toFixed(1)}k` : '-'}
            </span>
            <span style={{ fontVariantNumeric: 'tabular-nums', fontSize: 11, color: r.price?.free ? '#3fb950' : undefined }}>
              {r.price?.free ? '$0' : r.cost != null ? `$${r.cost.toFixed(4)}` : '-'}
            </span>
          </div>
        ))}
        {totalCost > 0 && (
          <div style={{ display: 'flex', justifyContent: 'flex-end', padding: '8px 0 2px', fontWeight: 600, fontSize: 13 }}>
            估算总计: ${totalCost.toFixed(4)}
          </div>
        )}
      </div>
    </Card>
  )
}

/* ---- CostTab 主体 ---- */

const ACTION_LABELS = { polish: '描述润色', recommend_tech: '技术栈推荐', both: '综合辅助' }

export default function CostTab() {
  const theme = useStore(s => s.theme)
  const isDark = theme === 'dark'
  const isRunning = useStore(s => s.isRunning)
  const stats = useStore(s => s.executionStats)
  const tokenRuns = useStore(s => s.executionTokenRuns)
  const sessionId = useStore(s => s.sessionId)
  const agentTokens = useStore(s => s.executionAgentTokens)
  const aiAssist = useStore(s => s.aiAssistTokens)
  const modelConfig = useStore(s => s.modelConfig)
  const iterationHistory = useStore(s => s.iterationHistory)

  const activeModel = modelConfig?.active?.coder?.model || modelConfig?.active?.helper?.model || ''

  /* ---- 累计数据 ---- */
  const runsTotal = tokenRuns.reduce((sum, r) => sum + (r.total_tokens || 0), 0)
  const currentInRuns = sessionId && tokenRuns.some(r => r.session_id === sessionId)
  const liveExtra = (isRunning && !currentInRuns && (stats.tokens || 0)) || 0
  const totalTokens = (runsTotal + liveExtra) || 0

  const cumuPrompt = tokenRuns.reduce((sum, r) => sum + (r.prompt_tokens || 0), 0)
  const cumuCompletion = tokenRuns.reduce((sum, r) => sum + (r.completion_tokens || 0), 0)
  const cumulativeCost = tokenRuns.reduce((sum, run) => sum + computeRunCost(run, modelConfig), 0)
    + (liveExtra > 0 ? computeRunCost({ total_tokens: liveExtra }, modelConfig) : 0)

  /* ---- 本次执行数据 ---- */
  const latestRun = tokenRuns[0] || {}
  const promptTokens = latestRun.prompt_tokens || agentTokens?._prompt_tokens || 0
  const completionTokens = latestRun.completion_tokens || agentTokens?._completion_tokens || 0
  const cachedTokens = latestRun.cached_tokens || agentTokens?._cached_tokens || 0
  const hasIoSplit = promptTokens > 0 || completionTokens > 0
  const currentTokens = latestRun.total_tokens || (isRunning ? stats.tokens : 0) || 0

  const currentCostVal = computeRunCost({
    total_tokens: currentTokens,
    prompt_tokens: promptTokens,
    completion_tokens: completionTokens,
    cached_tokens: cachedTokens,
    agent_tokens: agentTokens,
  }, modelConfig)

  /* ---- Agent 分布（本次） ---- */
  let helperTokens = agentTokens?.helper || 0
  let implTokens = agentTokens?.implementer || 0
  let devTokens = agentTokens?.coder || agentTokens?.dev || agentTokens?.developer || 0
  let testTokens = agentTokens?.critique || agentTokens?.test || agentTokens?.tester || 0
  const hasImplementer = implTokens > 0
  if (hasImplementer) { devTokens = implTokens; testTokens = 0 }

  if (helperTokens === 0 && devTokens === 0 && testTokens === 0 && iterationHistory?.length > 0) {
    for (const iter of iterationHistory) {
      const t = iter.tokensUsed || 0
      const p = (iter.phase || '').toLowerCase()
      if (p === 'refine') helperTokens += t
      else if (p.includes('test')) testTokens += t
      else devTokens += t
    }
  }

  const agentTotal = helperTokens + devTokens + testTokens
  const agentValues = hasImplementer ? [helperTokens, devTokens] : [helperTokens, devTokens, testTokens]
  const pcts = roundPercents(agentValues)
  const pctHelper = pcts[0]
  const pctDev = pcts[1]
  const pctTest = hasImplementer ? 0 : (pcts[2] || 0)

  if (totalTokens === 0 && tokenRuns.length === 0 && aiAssist.total === 0) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
        <Empty description="暂无成本数据，运行项目后将在此展示消耗分析" />
      </div>
    )
  }

  const muted = isDark ? '#8b949e' : '#656d76'
  const mutedLight = isDark ? '#6e7681' : '#8c959f'
  const dividerColor = isDark ? '#21262d' : '#e8e8e8'
  const avgCost = tokenRuns.length > 0 ? cumulativeCost / tokenRuns.length : 0

  return (
    <div style={{ padding: 16, overflow: 'auto', height: '100%' }}>

      {/* ======== 核心指标条 ======== */}
      <div style={{
        display: 'flex', gap: 0, marginBottom: 16, borderRadius: 8, overflow: 'hidden',
        border: `1px solid ${dividerColor}`,
      }}>
        <div style={{
          flex: 1, padding: '14px 20px',
          background: isDark ? '#0d1117' : '#f6f8fa',
          borderRight: `1px solid ${dividerColor}`,
        }}>
          <div style={{ fontSize: 11, color: muted, marginBottom: 6, display: 'flex', alignItems: 'center', gap: 4 }}>
            {isRunning ? '本次执行' : '最近一次'}
            {isRunning && (
              <Tag color="processing" style={{ fontSize: 9, margin: 0, padding: '0 3px', lineHeight: '14px' }}>执行中</Tag>
            )}
          </div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
            <span style={{ fontSize: 22, fontWeight: 700, color: isDark ? '#c9d1d9' : '#1f2328', fontVariantNumeric: 'tabular-nums' }}>
              {formatTokenCount(currentTokens)}
            </span>
            {currentCostVal > 0 && (
              <span style={{ fontSize: 13, color: '#58a6ff', fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>
                ~${currentCostVal.toFixed(4)}
              </span>
            )}
          </div>
          {hasIoSplit && promptTokens > 0 && (
            <div style={{ fontSize: 10, color: mutedLight, marginTop: 2 }}>
              输出/输入比 {(completionTokens / promptTokens).toFixed(2)}x
            </div>
          )}
        </div>

        <div style={{ flex: 1, padding: '14px 20px', background: isDark ? '#0d1117' : '#f6f8fa' }}>
          <div style={{ fontSize: 11, color: muted, marginBottom: 6 }}>项目累计</div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
            <span style={{ fontSize: 22, fontWeight: 700, color: isDark ? '#c9d1d9' : '#1f2328', fontVariantNumeric: 'tabular-nums' }}>
              {formatTokenCount(totalTokens)}
            </span>
            {cumulativeCost > 0 && (
              <span style={{ fontSize: 13, color: muted, fontVariantNumeric: 'tabular-nums' }}>
                ~${cumulativeCost.toFixed(4)}
              </span>
            )}
          </div>
          <div style={{ fontSize: 10, color: mutedLight, marginTop: 2 }}>
            {tokenRuns.length} 次执行
            {cumuPrompt > 0 ? ` · 输出/输入比 ${(cumuCompletion / cumuPrompt).toFixed(2)}x` : ''}
          </div>
        </div>
      </div>

      {/* ======== 本次 Agent 分布 | 项目累计统计 ======== */}
      <Row gutter={[16, 16]}>
        <Col span={12}>
          <Card size="small" title={<span>智能体消耗分布 <ScopeTag type="current" /></span>}>
            {agentTotal > 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                {[
                  { label: '辅助 AI', tokens: helperTokens, pct: pctHelper, color: '#58a6ff' },
                  { label: hasImplementer ? '实现' : 'Coder AI', tokens: devTokens, pct: pctDev, color: '#3fb950' },
                  ...(!hasImplementer ? [{ label: 'Critique AI', tokens: testTokens, pct: pctTest, color: '#d29922' }] : []),
                ].map(a => (
                  <div key={a.label}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 4 }}>
                      <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <span style={{ width: 8, height: 8, borderRadius: '50%', background: a.color, display: 'inline-block' }} />
                        {a.label}
                      </span>
                      <span style={{ color: muted }}>
                        {a.tokens.toLocaleString()} ({a.pct}%)
                      </span>
                    </div>
                    <div style={{ height: 6, borderRadius: 3, background: dividerColor }}>
                      <div style={{ height: '100%', borderRadius: 3, background: a.color, width: `${a.pct}%`, transition: 'width 0.3s' }} />
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <Empty description="等待执行完成..." image={Empty.PRESENTED_IMAGE_SIMPLE} />
            )}
          </Card>
        </Col>

        <Col span={12}>
          <Card size="small" title={<span>项目统计 <ScopeTag type="cumulative" /></span>}>
            <Row gutter={[8, 16]}>
              <Col span={12}>
                <Statistic title={<span style={{ fontSize: 11 }}>总消耗</span>} value={totalTokens.toLocaleString()} valueStyle={{ fontSize: 20 }} />
              </Col>
              <Col span={12}>
                <Statistic title={<span style={{ fontSize: 11 }}>执行次数</span>} value={tokenRuns.length} valueStyle={{ fontSize: 20 }} />
              </Col>
              <Col span={12}>
                <Statistic title={<span style={{ fontSize: 11 }}>平均每次</span>}
                  value={tokenRuns.length > 0 ? Math.round(totalTokens / tokenRuns.length).toLocaleString() : '-'}
                  valueStyle={{ fontSize: 20 }}
                />
              </Col>
              <Col span={12}>
                <Statistic
                  title={<span style={{ fontSize: 11 }}>平均费用/次</span>}
                  value={avgCost > 0 ? `$${avgCost.toFixed(4)}` : '-'}
                  valueStyle={{ fontSize: 20 }}
                />
              </Col>
            </Row>
          </Card>
        </Col>
      </Row>

      {/* ======== 执行中实时（无 I/O 明细时） ======== */}
      {isRunning && !hasIoSplit && stats.tokens > 0 && (
        <Card size="small" title={<span>实时消耗 <ScopeTag type="current" /></span>} style={{ marginTop: 16 }}>
          <Row gutter={[8, 12]}>
            <Col span={8}>
              <Statistic
                title={<span style={{ fontSize: 11 }}>已消耗</span>}
                value={stats.tokens.toLocaleString()}
                valueStyle={{ fontSize: 18, color: '#58a6ff' }}
                suffix="Token"
              />
            </Col>
            <Col span={8}>
              <Statistic
                title={<span style={{ fontSize: 11 }}>迭代轮次</span>}
                value={iterationHistory?.length || 0}
                valueStyle={{ fontSize: 18 }}
              />
            </Col>
            <Col span={8}>
              <Statistic
                title={<span style={{ fontSize: 11 }}>耗时</span>}
                value={stats.elapsed > 0 ? `${stats.elapsed.toFixed(0)}s` : '-'}
                valueStyle={{ fontSize: 18 }}
              />
            </Col>
          </Row>
          <div style={{ marginTop: 8, fontSize: 11, color: mutedLight }}>
            详细分布（输入/输出/缓存）将在执行完成后显示
          </div>
        </Card>
      )}

      {/* ======== 本次 Token I/O 分布 ======== */}
      {hasIoSplit && (
        <Card size="small" title={<span>Token 分布 <ScopeTag type="current" /></span>} style={{ marginTop: 16 }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {[
              { label: '新输入 Token', tokens: Math.max(0, promptTokens - cachedTokens), color: '#58a6ff', note: '首次发送的上下文' },
              ...(cachedTokens > 0 ? [{ label: '缓存命中 Token', tokens: cachedTokens, color: '#3fb950', note: '仅收取约 20% 输入价格' }] : []),
              { label: '输出 Token', tokens: completionTokens, color: '#d29922', note: '模型生成内容，单价约为输入的 3-4 倍' },
            ].map(item => {
              const total = promptTokens + completionTokens
              const pct = total > 0 ? Math.round(item.tokens / total * 100) : 0
              return (
                <div key={item.label}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 4 }}>
                    <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <span style={{ width: 8, height: 8, borderRadius: '50%', background: item.color, display: 'inline-block' }} />
                      <span>{item.label}</span>
                      <span style={{ fontSize: 10, color: mutedLight }}>{item.note}</span>
                    </span>
                    <span style={{ color: muted }}>
                      {formatTokenCount(item.tokens)} ({pct}%)
                    </span>
                  </div>
                  <div style={{ height: 6, borderRadius: 3, background: dividerColor }}>
                    <div style={{ height: '100%', borderRadius: 3, background: item.color, width: `${pct}%`, transition: 'width 0.3s' }} />
                  </div>
                </div>
              )
            })}
          </div>
        </Card>
      )}

      <CacheSavingsCard promptTokens={promptTokens} cachedTokens={cachedTokens} model={activeModel} isDark={isDark} />

      {/* ======== 执行历史消耗 ======== */}
      {tokenRuns.length > 0 && (
        <Card size="small" title={<span>执行历史消耗 <ScopeTag type="cumulative" /></span>} style={{ marginTop: 16 }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {tokenRuns.map((run, idx) => {
              const ts = run.timestamp
                ? new Date(run.timestamp).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
                : ''
              const pct = totalTokens > 0 ? Math.round((run.total_tokens || 0) / totalTokens * 100) : 0
              const runCost = computeRunCost(run, modelConfig)
              const cacheRate = run.prompt_tokens > 0 && run.cached_tokens > 0
                ? Math.round(run.cached_tokens / run.prompt_tokens * 100)
                : null
              return (
                <div key={idx} style={{
                  display: 'flex', alignItems: 'center', gap: 8, padding: '6px 0',
                  borderBottom: `1px solid ${isDark ? '#161b22' : '#f6f8fa'}`, fontSize: 12,
                }}>
                  <span style={{ width: 24, textAlign: 'center', color: mutedLight }}>#{tokenRuns.length - idx}</span>
                  <span style={{ width: 90, color: muted }}>{ts}</span>
                  <Tag color={run.isRunning ? 'processing' : run.success ? 'success' : 'error'} style={{ margin: 0 }}>
                    {run.isRunning ? '运行中' : run.success ? '成功' : '失败'}
                  </Tag>
                  {run.prompt_tokens > 0 ? (
                    <span style={{ flex: 1, display: 'flex', gap: 1, height: 4, borderRadius: 2, overflow: 'hidden' }}>
                      <span style={{ flex: Math.max(0, (run.prompt_tokens || 0) - (run.cached_tokens || 0)), background: '#58a6ff' }} />
                      {(run.cached_tokens || 0) > 0 && <span style={{ flex: run.cached_tokens, background: '#3fb950' }} />}
                      <span style={{ flex: run.completion_tokens || 0, background: '#d29922' }} />
                    </span>
                  ) : (
                    <span style={{ flex: 1 }}>
                      <div style={{ height: 4, borderRadius: 2, background: dividerColor }}>
                        <div style={{ height: '100%', borderRadius: 2, background: run.success ? '#3fb950' : '#f85149', width: `${pct}%` }} />
                      </div>
                    </span>
                  )}
                  <span style={{ width: 70, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                    {(run.total_tokens || 0).toLocaleString()}
                  </span>
                  {runCost > 0 ? (
                    <Tooltip title="估算费用">
                      <span style={{ width: 60, textAlign: 'right', fontVariantNumeric: 'tabular-nums', color: '#58a6ff', fontSize: 11 }}>
                        ${runCost.toFixed(4)}
                      </span>
                    </Tooltip>
                  ) : (
                    <span style={{ width: 60 }} />
                  )}
                  {cacheRate !== null ? (
                    <Tooltip title="Prompt Cache 命中率">
                      <Tag color="green" style={{ margin: 0, fontSize: 10, padding: '0 3px', lineHeight: '14px', width: 52, textAlign: 'center' }}>
                        缓存{cacheRate}%
                      </Tag>
                    </Tooltip>
                  ) : (
                    <span style={{ width: 52 }} />
                  )}
                  <span style={{ width: 50, textAlign: 'right', color: isDark ? '#484f58' : '#bbb', fontSize: 11 }}>
                    {run.elapsed_seconds > 0 ? `${run.elapsed_seconds.toFixed(1)}s` : ''}
                  </span>
                </div>
              )
            })}
          </div>
        </Card>
      )}

      {/* ======== AI 辅助消耗 ======== */}
      {aiAssist.total > 0 && (
        <Card
          size="small"
          title={
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <ThunderboltOutlined style={{ color: '#a371f7' }} />
              AI 辅助消耗
              <ScopeTag type="non-exec" />
            </span>
          }
          style={{ marginTop: 16 }}
        >
          <Row gutter={[8, 12]}>
            <Col span={8}>
              <Statistic
                title={<span style={{ fontSize: 11 }}>总消耗</span>}
                value={aiAssist.total.toLocaleString()}
                valueStyle={{ fontSize: 18, color: '#a371f7' }}
              />
            </Col>
            <Col span={8}>
              <Statistic
                title={<span style={{ fontSize: 11 }}>调用次数</span>}
                value={aiAssist.calls}
                valueStyle={{ fontSize: 18 }}
              />
            </Col>
            <Col span={8}>
              <Statistic
                title={<span style={{ fontSize: 11 }}>平均每次</span>}
                value={aiAssist.calls > 0 ? Math.round(aiAssist.total / aiAssist.calls).toLocaleString() : '-'}
                valueStyle={{ fontSize: 18 }}
              />
            </Col>
          </Row>
          {aiAssist.records.length > 0 && (
            <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 3 }}>
              {aiAssist.records.slice(0, 10).map((r, idx) => {
                const ts = r.timestamp
                  ? new Date(r.timestamp).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
                  : ''
                return (
                  <div key={idx} style={{
                    display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0',
                    borderBottom: `1px solid ${isDark ? '#161b22' : '#f6f8fa'}`, fontSize: 12,
                  }}>
                    <Tag color="purple" style={{ margin: 0, fontSize: 10, padding: '0 4px', lineHeight: '16px' }}>
                      {ACTION_LABELS[r.action] || r.action}
                    </Tag>
                    <span style={{ flex: 1, color: muted }}>{ts}</span>
                    <span style={{ fontVariantNumeric: 'tabular-nums' }}>
                      {(r.total_tokens || 0).toLocaleString()}
                    </span>
                  </div>
                )
              })}
            </div>
          )}
        </Card>
      )}

      <ModelPricingCard
        agentTokens={agentTokens}
        helperTokens={helperTokens}
        devTokens={devTokens}
        testTokens={testTokens}
        promptTokens={promptTokens}
        completionTokens={completionTokens}
        cachedTokens={cachedTokens}
        isDark={isDark}
      />
    </div>
  )
}
