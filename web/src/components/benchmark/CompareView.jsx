import { useState, useEffect } from 'react'
import { Card, Table, Tag, Select, Button, Row, Col, Empty } from 'antd'
import { SwapOutlined, ArrowUpOutlined, ArrowDownOutlined } from '@ant-design/icons'
import useStore from '../../stores/useStore'

function DeltaTag({ delta }) {
  if (!delta) return '-'
  const { pct, improved } = delta
  if (pct === 0) return <Tag style={{ margin: 0 }}>-</Tag>
  return (
    <Tag
      color={improved ? 'success' : 'error'}
      style={{ margin: 0 }}
      icon={improved ? <ArrowDownOutlined /> : <ArrowUpOutlined />}
    >
      {pct > 0 ? '+' : ''}{pct}%
    </Tag>
  )
}

function MetricRow({ label, a, b, delta, isDark, suffix = '' }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', padding: '8px 0',
      borderBottom: `1px solid ${isDark ? '#21262d' : '#eaecef'}`,
      fontSize: 13,
    }}>
      <span style={{ flex: 1, color: isDark ? '#8b949e' : '#656d76' }}>{label}</span>
      <span style={{ width: 120, textAlign: 'right', fontFamily: 'monospace' }}>{a}{suffix}</span>
      <span style={{ width: 80, textAlign: 'center' }}><DeltaTag delta={delta} /></span>
      <span style={{ width: 120, textAlign: 'right', fontFamily: 'monospace' }}>{b}{suffix}</span>
    </div>
  )
}

export default function CompareView() {
  const theme = useStore((s) => s.theme)
  const compare = useStore((s) => s.benchmarkCompare)
  const history = useStore((s) => s.benchmarkHistory)
  const fetchCompare = useStore((s) => s.fetchBenchmarkCompare)
  const fetchHistory = useStore((s) => s.fetchBenchmarkHistory)
  const isDark = theme === 'dark'

  const [tagA, setTagA] = useState(compare?.tag_a || '')
  const [tagB, setTagB] = useState(compare?.tag_b || '')

  useEffect(() => { if (!history.length) fetchHistory() }, []) // eslint-disable-line
  useEffect(() => {
    if (compare) { setTagA(compare.tag_a); setTagB(compare.tag_b) }
  }, [compare])

  const tagOptions = history.map((r) => ({ label: r.tag, value: r.tag }))

  const handleCompare = () => {
    if (tagA && tagB && tagA !== tagB) fetchCompare(tagA, tagB)
  }

  const agg = compare?.aggregates || {}

  const caseColumns = [
    { title: '用例', dataIndex: 'name', key: 'name', render: (v) => <span style={{ fontWeight: 600 }}>{v}</span> },
    {
      title: `${compare?.tag_a || 'A'}`, key: 'a', width: 90,
      render: (_, r) => r.a_success === null ? <Tag style={{ margin: 0 }}>—</Tag>
        : r.a_success ? <Tag color="success" style={{ margin: 0 }}>通过</Tag>
          : <Tag color="error" style={{ margin: 0 }}>失败</Tag>,
    },
    {
      title: `${compare?.tag_b || 'B'}`, key: 'b', width: 90,
      render: (_, r) => r.b_success === null ? <Tag style={{ margin: 0 }}>—</Tag>
        : r.b_success ? <Tag color="success" style={{ margin: 0 }}>通过</Tag>
          : <Tag color="error" style={{ margin: 0 }}>失败</Tag>,
    },
    {
      title: 'Token 变化', key: 'tok_delta', width: 110,
      render: (_, r) => <DeltaTag delta={r.token_delta} />,
    },
    {
      title: '耗时变化', key: 'time_delta', width: 110,
      render: (_, r) => <DeltaTag delta={r.elapsed_delta} />,
    },
  ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* 选择器 */}
      <Card size="small" style={{ background: isDark ? '#161b22' : '#fff', borderColor: isDark ? '#30363d' : '#d0d7de' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <Select
            value={tagA || undefined}
            onChange={setTagA}
            options={tagOptions}
            placeholder="选择基准 (A)"
            style={{ width: 200 }}
            showSearch
          />
          <SwapOutlined style={{ fontSize: 16, color: isDark ? '#8b949e' : '#656d76' }} />
          <Select
            value={tagB || undefined}
            onChange={setTagB}
            options={tagOptions}
            placeholder="选择对照 (B)"
            style={{ width: 200 }}
            showSearch
          />
          <Button type="primary" onClick={handleCompare} disabled={!tagA || !tagB || tagA === tagB}>
            对比
          </Button>
        </div>
      </Card>

      {!compare ? (
        <Empty description="选择两个运行进行对比" style={{ padding: '60px 0' }} />
      ) : (
        <>
          {/* 聚合指标对比 */}
          <Card size="small" title="聚合指标对比"
            style={{ background: isDark ? '#161b22' : '#fff', borderColor: isDark ? '#30363d' : '#d0d7de' }}>
            <div style={{
              display: 'flex', padding: '4px 0 8px',
              borderBottom: `2px solid ${isDark ? '#30363d' : '#d0d7de'}`,
              fontSize: 12, fontWeight: 600, color: isDark ? '#8b949e' : '#656d76',
            }}>
              <span style={{ flex: 1 }}>指标</span>
              <span style={{ width: 120, textAlign: 'right' }}>{compare.tag_a}</span>
              <span style={{ width: 80, textAlign: 'center' }}>变化</span>
              <span style={{ width: 120, textAlign: 'right' }}>{compare.tag_b}</span>
            </div>
            <MetricRow
              label="完成率" isDark={isDark} suffix="%"
              a={((agg.completion_rate?.a || 0) * 100).toFixed(0)}
              b={((agg.completion_rate?.b || 0) * 100).toFixed(0)}
              delta={agg.completion_rate?.delta}
            />
            <MetricRow
              label={`平均 Token (${agg.avg_tokens?.label || ''})`} isDark={isDark}
              a={(agg.avg_tokens?.a || 0).toFixed(0)}
              b={(agg.avg_tokens?.b || 0).toFixed(0)}
              delta={agg.avg_tokens?.delta}
            />
            <MetricRow
              label={`平均耗时 (${agg.avg_elapsed?.label || ''})`} isDark={isDark} suffix="s"
              a={(agg.avg_elapsed?.a || 0).toFixed(1)}
              b={(agg.avg_elapsed?.b || 0).toFixed(1)}
              delta={agg.avg_elapsed?.delta}
            />
            <MetricRow
              label="总费用" isDark={isDark} suffix=""
              a={`$${(agg.total_cost?.a || 0).toFixed(4)}`}
              b={`$${(agg.total_cost?.b || 0).toFixed(4)}`}
              delta={agg.total_cost?.delta}
            />
          </Card>

          {/* 共同成功用例 */}
          {compare.common_success?.length > 0 && (
            <div style={{ fontSize: 12, color: isDark ? '#8b949e' : '#656d76', padding: '0 4px' }}>
              共同成功用例: {compare.common_success.join(', ')}（对比基于共同成功用例计算）
            </div>
          )}

          {/* 逐用例对比 */}
          <Card size="small" title="逐用例对比"
            style={{ background: isDark ? '#161b22' : '#fff', borderColor: isDark ? '#30363d' : '#d0d7de' }}>
            <Table
              dataSource={compare.per_case || []}
              columns={caseColumns}
              rowKey="name"
              size="small"
              pagination={false}
            />
          </Card>
        </>
      )}
    </div>
  )
}
