import { Card, Row, Col, Statistic, Empty, Tag, Tooltip } from 'antd'
import { ThunderboltOutlined, SaveOutlined } from '@ant-design/icons'
import useStore from '../../stores/useStore'
import { formatTokenCount } from './helpers'
import { findModelPrice, estimateCostDetailed, estimateCost } from '../../constants/modelPricing'

/* ---- 缓存节省卡片 ---- */

function CacheSavingsCard({ promptTokens, cachedTokens, model, isDark }) {
  if (!cachedTokens || cachedTokens <= 0) return null

  const price = findModelPrice(model)
  const effectivePrompt = Math.max(promptTokens, cachedTokens)
  const cacheHitPct = effectivePrompt > 0 ? Math.min(100, Math.round(cachedTokens / effectivePrompt * 100)) : 0
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

function ModelPricingCard({ agentTokens, promptTokens, completionTokens, cachedTokens, isDark }) {
  const modelConfig = useStore(s => s.modelConfig)
  const active = modelConfig?.active || {}

  const agents = [
    { key: 'pm', label: 'PM（规划）', model: active.pm?.model, tokens: agentTokens?.pm || 0, color: '#58a6ff' },
    { key: 'dev', label: '开发', model: active.developer?.model, tokens: agentTokens?.dev || agentTokens?.developer || 0, color: '#3fb950' },
    { key: 'test', label: '测试', model: active.tester?.model, tokens: agentTokens?.test || agentTokens?.tester || 0, color: '#d29922' },
  ]

  const hasDetail = promptTokens > 0 || completionTokens > 0
  const rows = agents.map(a => {
    const price = findModelPrice(a.model)
    const cost = hasDetail
      ? estimateCostDetailed(promptTokens, completionTokens, price, cachedTokens)
      : { total: estimateCost(a.tokens, price) }
    return { ...a, price, cost: cost?.total ?? null }
  })

  const totalCost = rows.reduce((sum, r) => sum + (r.cost || 0), 0)

  const borderColor = isDark ? '#21262d' : '#e8e8e8'

  return (
    <Card size="small" title="模型单价与估算" style={{ marginTop: 16 }}>
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
  const stats = useStore(s => s.executionStats)
  const tokenRuns = useStore(s => s.executionTokenRuns)
  const agentTokens = useStore(s => s.executionAgentTokens)
  const aiAssist = useStore(s => s.aiAssistTokens)
  const modelConfig = useStore(s => s.modelConfig)
  const iterationHistory = useStore(s => s.iterationHistory)

  const projectTokens = tokenRuns.reduce((sum, r) => sum + (r.total_tokens || 0), 0)
  const totalTokens = projectTokens || stats.tokens || 0

  let pmTokens = agentTokens?.pm || 0
  let devTokens = agentTokens?.dev || agentTokens?.developer || 0
  let testTokens = agentTokens?.test || agentTokens?.tester || 0

  if (pmTokens === 0 && devTokens === 0 && testTokens === 0 && iterationHistory?.length > 0) {
    for (const iter of iterationHistory) {
      const t = iter.tokensUsed || 0
      const p = (iter.phase || '').toLowerCase()
      if (p.includes('pm') || p === 'refine') pmTokens += t
      else if (p.includes('test') || p.includes('fix')) testTokens += t
      else devTokens += t
    }
  }

  const agentTotal = pmTokens + devTokens + testTokens

  const latestRun = tokenRuns[0] || {}
  const promptTokens = latestRun.prompt_tokens || 0
  const completionTokens = latestRun.completion_tokens || 0
  const cachedTokens = latestRun.cached_tokens || agentTokens?._cached_tokens || 0
  const hasIoSplit = promptTokens > 0 || completionTokens > 0

  const pctPm = agentTotal > 0 ? Math.round(pmTokens / agentTotal * 100) : 0
  const pctDev = agentTotal > 0 ? Math.round(devTokens / agentTotal * 100) : 0
  const pctTest = agentTotal > 0 ? Math.round(testTokens / agentTotal * 100) : 0

  const activeModel = modelConfig?.active?.developer?.model || modelConfig?.active?.pm?.model || ''

  if (totalTokens === 0 && tokenRuns.length === 0 && aiAssist.total === 0) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
        <Empty description="暂无成本数据，运行项目后将在此展示消耗分析" />
      </div>
    )
  }

  return (
    <div style={{ padding: 16, overflow: 'auto', height: '100%' }}>
      <Row gutter={[16, 16]}>
        {/* 智能体分布 */}
        <Col span={12}>
          <Card size="small" title="智能体消耗分布">
            {agentTotal > 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                {[
                  { label: 'PM（规划）', tokens: pmTokens, pct: pctPm, color: '#58a6ff' },
                  { label: '开发', tokens: devTokens, pct: pctDev, color: '#3fb950' },
                  { label: '测试', tokens: testTokens, pct: pctTest, color: '#d29922' },
                ].map(a => (
                  <div key={a.label}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 4 }}>
                      <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <span style={{ width: 8, height: 8, borderRadius: '50%', background: a.color, display: 'inline-block' }} />
                        {a.label}
                      </span>
                      <span style={{ color: isDark ? '#8b949e' : '#656d76' }}>
                        {a.tokens.toLocaleString()} ({a.pct}%)
                      </span>
                    </div>
                    <div style={{ height: 6, borderRadius: 3, background: isDark ? '#21262d' : '#e8e8e8' }}>
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

        {/* 项目累计 */}
        <Col span={12}>
          <Card size="small" title="项目累计">
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
                  title={<span style={{ fontSize: 11 }}>输出/输入比</span>}
                  value={hasIoSplit && promptTokens > 0 ? `${(completionTokens / promptTokens).toFixed(2)}x` : '-'}
                  valueStyle={{ fontSize: 20 }}
                />
              </Col>
            </Row>
          </Card>
        </Col>
      </Row>

      {/* 输入/输出/缓存 Token 三段分布 */}
      {hasIoSplit && (
        <Card size="small" title="本次执行 Token 分布" style={{ marginTop: 16 }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {[
              { label: '新输入 Token', tokens: Math.max(0, promptTokens - cachedTokens), color: '#58a6ff', note: '首次发送的上下文' },
              ...(cachedTokens > 0 ? [{ label: '缓存命中 Token', tokens: cachedTokens, color: '#3fb950', note: '仅收取约 20% 输入价格' }] : []),
              { label: '输出 Token', tokens: completionTokens, color: '#d29922', note: `模型生成内容，单价约为输入的 3-4 倍` },
            ].map(item => {
              const total = promptTokens + completionTokens
              const pct = total > 0 ? Math.round(item.tokens / total * 100) : 0
              return (
                <div key={item.label}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 4 }}>
                    <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <span style={{ width: 8, height: 8, borderRadius: '50%', background: item.color, display: 'inline-block' }} />
                      <span>{item.label}</span>
                      <span style={{ fontSize: 10, color: isDark ? '#6e7681' : '#8c959f' }}>{item.note}</span>
                    </span>
                    <span style={{ color: isDark ? '#8b949e' : '#656d76' }}>
                      {formatTokenCount(item.tokens)} ({pct}%)
                    </span>
                  </div>
                  <div style={{ height: 6, borderRadius: 3, background: isDark ? '#21262d' : '#e8e8e8' }}>
                    <div style={{ height: '100%', borderRadius: 3, background: item.color, width: `${pct}%`, transition: 'width 0.3s' }} />
                  </div>
                </div>
              )
            })}
          </div>
        </Card>
      )}

      {/* Prompt Caching 节省 */}
      <CacheSavingsCard
        promptTokens={promptTokens}
        cachedTokens={cachedTokens}
        model={activeModel}
        isDark={isDark}
      />

      {/* 执行历史消耗 */}
      {tokenRuns.length > 0 && (
        <Card size="small" title="执行历史消耗" style={{ marginTop: 16 }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {tokenRuns.map((run, idx) => {
              const ts = run.timestamp
                ? new Date(run.timestamp).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
                : ''
              const pct = totalTokens > 0 ? Math.round((run.total_tokens || 0) / totalTokens * 100) : 0
              return (
                <div key={idx} style={{
                  display: 'flex', alignItems: 'center', gap: 8, padding: '6px 0',
                  borderBottom: `1px solid ${isDark ? '#161b22' : '#f6f8fa'}`, fontSize: 12,
                }}>
                  <span style={{ width: 24, textAlign: 'center', color: isDark ? '#6e7681' : '#8c959f' }}>#{tokenRuns.length - idx}</span>
                  <span style={{ width: 90, color: isDark ? '#8b949e' : '#656d76' }}>{ts}</span>
                  <Tag color={run.success ? 'success' : 'error'} style={{ margin: 0 }}>{run.success ? '成功' : '失败'}</Tag>
                  {run.prompt_tokens > 0 ? (
                    <span style={{ flex: 1, display: 'flex', gap: 1, height: 4, borderRadius: 2, overflow: 'hidden' }}>
                      <span style={{ flex: Math.max(0, (run.prompt_tokens || 0) - (run.cached_tokens || 0)), background: '#58a6ff' }} />
                      {(run.cached_tokens || 0) > 0 && <span style={{ flex: run.cached_tokens, background: '#3fb950' }} />}
                      <span style={{ flex: run.completion_tokens || 0, background: '#d29922' }} />
                    </span>
                  ) : (
                    <span style={{ flex: 1 }}>
                      <div style={{ height: 4, borderRadius: 2, background: isDark ? '#21262d' : '#e8e8e8' }}>
                        <div style={{ height: '100%', borderRadius: 2, background: run.success ? '#3fb950' : '#f85149', width: `${pct}%` }} />
                      </div>
                    </span>
                  )}
                  <span style={{ width: 70, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                    {(run.total_tokens || 0).toLocaleString()}
                  </span>
                  {run.elapsed_seconds > 0 && (
                    <span style={{ width: 50, textAlign: 'right', color: isDark ? '#484f58' : '#bbb', fontSize: 11 }}>
                      {run.elapsed_seconds.toFixed(1)}s
                    </span>
                  )}
                </div>
              )
            })}
          </div>
        </Card>
      )}

      {/* AI 辅助消耗 */}
      {aiAssist.total > 0 && (
        <Card
          size="small"
          title={
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <ThunderboltOutlined style={{ color: '#a371f7' }} />
              AI 辅助消耗
              <Tag color="purple" style={{ fontSize: 10, margin: 0, padding: '0 4px', lineHeight: '16px' }}>非执行</Tag>
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
                    <span style={{ flex: 1, color: isDark ? '#8b949e' : '#656d76' }}>{ts}</span>
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
        promptTokens={promptTokens}
        completionTokens={completionTokens}
        cachedTokens={cachedTokens}
        isDark={isDark}
      />
    </div>
  )
}
