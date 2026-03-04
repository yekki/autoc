import { Card, Tag, Table, Descriptions, Row, Col, Empty, Collapse } from 'antd'
import {
  CheckCircleFilled, CloseCircleFilled, WarningFilled,
  ClockCircleOutlined, ThunderboltOutlined,
} from '@ant-design/icons'
import useStore from '../../stores/useStore'

function PercentBar({ value, max, color = '#58a6ff', label, suffix = '' }) {
  const pct = max > 0 ? (value / max) * 100 : 0
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
      <span style={{ width: 100, fontSize: 12, textAlign: 'right', flexShrink: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {label}
      </span>
      <div style={{ flex: 1, height: 16, background: 'rgba(128,128,128,0.15)', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ width: `${Math.min(pct, 100)}%`, height: '100%', background: color, borderRadius: 3, transition: 'width 0.3s' }} />
      </div>
      <span style={{ width: 70, fontSize: 12, textAlign: 'right', flexShrink: 0 }}>
        {typeof value === 'number' ? value.toLocaleString() : value}{suffix}
      </span>
    </div>
  )
}

function BottleneckSection({ detail, isDark }) {
  const cases = detail.cases || []
  const successful = cases.filter((c) => c.success)
  if (!successful.length) return null

  const stageAgg = {}
  const agentAgg = {}
  const toolAgg = {}

  for (const c of successful) {
    if (c.stage_timings) {
      for (const [stage, time] of Object.entries(c.stage_timings)) {
        stageAgg[stage] = (stageAgg[stage] || 0) + time
      }
    }
    if (c.agent_tokens) {
      for (const [agent, tokens] of Object.entries(c.agent_tokens)) {
        agentAgg[agent] = (agentAgg[agent] || 0) + tokens
      }
    }
    if (c.tool_calls) {
      for (const [tool, count] of Object.entries(c.tool_calls)) {
        toolAgg[tool] = (toolAgg[tool] || 0) + count
      }
    }
  }

  const stages = Object.entries(stageAgg).sort((a, b) => b[1] - a[1])
  const agents = Object.entries(agentAgg).sort((a, b) => b[1] - a[1])
  const tools = Object.entries(toolAgg).sort((a, b) => b[1] - a[1]).slice(0, 10)

  const maxStage = stages.length ? stages[0][1] : 1
  const maxAgent = agents.length ? agents[0][1] : 1
  const maxTool = tools.length ? tools[0][1] : 1

  return (
    <Row gutter={[16, 16]}>
      {stages.length > 0 && (
        <Col xs={24} md={12}>
          <Card size="small" title={<span style={{ fontSize: 13 }}><ClockCircleOutlined /> 阶段耗时分布</span>}
            style={{ background: isDark ? '#161b22' : '#fff', borderColor: isDark ? '#30363d' : '#d0d7de' }}>
            {stages.map(([stage, time]) => (
              <PercentBar key={stage} label={stage} value={parseFloat(time.toFixed(1))} max={maxStage} color="#58a6ff" suffix="s" />
            ))}
          </Card>
        </Col>
      )}
      {agents.length > 0 && (
        <Col xs={24} md={12}>
          <Card size="small" title={<span style={{ fontSize: 13 }}><ThunderboltOutlined /> Agent Token 分布</span>}
            style={{ background: isDark ? '#161b22' : '#fff', borderColor: isDark ? '#30363d' : '#d0d7de' }}>
            {agents.map(([agent, tokens]) => (
              <PercentBar key={agent} label={agent} value={tokens} max={maxAgent} color="#d2a8ff" />
            ))}
          </Card>
        </Col>
      )}
      {tools.length > 0 && (
        <Col xs={24}>
          <Card size="small" title={<span style={{ fontSize: 13 }}>工具调用 TOP {tools.length}</span>}
            style={{ background: isDark ? '#161b22' : '#fff', borderColor: isDark ? '#30363d' : '#d0d7de' }}>
            {tools.map(([tool, count]) => (
              <PercentBar key={tool} label={tool} value={count} max={maxTool} color="#3fb950" suffix="x" />
            ))}
          </Card>
        </Col>
      )}
    </Row>
  )
}

function QualitySection({ detail, isDark }) {
  const cases = detail.cases || []
  const withQuality = cases.filter((c) => c.quality_checks && c.quality_checks.length > 0)
  if (!withQuality.length) return null

  return (
    <Card size="small" title="产出质量验证"
      style={{ background: isDark ? '#161b22' : '#fff', borderColor: isDark ? '#30363d' : '#d0d7de' }}>
      <Collapse ghost size="small" items={withQuality.map((c) => ({
        key: c.case_name,
        label: (
          <span>
            {c.quality_verified ? <CheckCircleFilled style={{ color: '#3fb950', marginRight: 6 }} />
              : <CloseCircleFilled style={{ color: '#f85149', marginRight: 6 }} />}
            {c.case_name}
          </span>
        ),
        children: (
          <div style={{ fontSize: 12 }}>
            {c.quality_checks.map((check, i) => (
              <div key={i} style={{ padding: '2px 0', color: check.passed ? (isDark ? '#8b949e' : '#656d76') : '#f85149' }}>
                {check.passed ? '✓' : '✗'} [{check.level}] {check.name}
              </div>
            ))}
          </div>
        ),
      }))} />
    </Card>
  )
}

function AnomalySection({ detail, isDark }) {
  const agg = detail.aggregates || {}
  const anomalies = agg.anomalies || []
  if (!anomalies.length) return null

  return (
    <Card size="small" title="异常值检测"
      style={{ background: isDark ? '#161b22' : '#fff', borderColor: isDark ? '#30363d' : '#d0d7de' }}>
      {anomalies.map((a, i) => (
        <div key={i} style={{ padding: '4px 0', fontSize: 13 }}>
          <WarningFilled style={{ color: a.severity === 'high' ? '#f85149' : '#d29922', marginRight: 6 }} />
          {a.message || a}
        </div>
      ))}
    </Card>
  )
}

export default function DetailView() {
  const theme = useStore((s) => s.theme)
  const detail = useStore((s) => s.benchmarkDetail)
  const isDark = theme === 'dark'

  if (!detail) return <Empty description="选择一次运行查看详情" />

  const agg = detail.aggregates || {}
  const cases = detail.cases || []
  const env = detail.environment || {}

  const caseColumns = [
    {
      title: '用例', dataIndex: 'case_name', key: 'name',
      render: (name, r) => (
        <span style={{ fontWeight: 600, color: r.success ? undefined : '#f85149' }}>{name}</span>
      ),
    },
    {
      title: '状态', dataIndex: 'success', key: 'status', width: 70,
      render: (v) => v
        ? <Tag color="success" style={{ margin: 0 }}>通过</Tag>
        : <Tag color="error" style={{ margin: 0 }}>失败</Tag>,
    },
    { title: '迭代', dataIndex: 'dev_iterations', key: 'iter', width: 60, render: (v) => v || '-' },
    { title: 'Token', dataIndex: 'total_tokens', key: 'tokens', width: 90, render: (v) => v?.toLocaleString() || '-' },
    { title: '耗时', dataIndex: 'elapsed_seconds', key: 'elapsed', width: 80, render: (v) => v ? `${v.toFixed(1)}s` : '-' },
    {
      title: '任务', key: 'tasks', width: 80,
      render: (_, r) => r.tasks_total > 0 ? `${r.tasks_verified}/${r.tasks_total}` : '-',
    },
    { title: '退出原因', dataIndex: 'exit_reason', key: 'exit', width: 120, ellipsis: true },
    {
      title: '质量', key: 'quality', width: 60,
      render: (_, r) => r.quality_verified === true
        ? <CheckCircleFilled style={{ color: '#3fb950' }} />
        : r.quality_verified === false
          ? <CloseCircleFilled style={{ color: '#f85149' }} />
          : '-',
    },
  ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* 运行概览 */}
      <Card size="small" style={{ background: isDark ? '#161b22' : '#fff', borderColor: isDark ? '#30363d' : '#d0d7de' }}>
        <Descriptions column={{ xs: 1, sm: 2, md: 3 }} size="small">
          <Descriptions.Item label="标签">{detail.tag}</Descriptions.Item>
          <Descriptions.Item label="时间">{detail.timestamp?.replace('T', ' ').slice(0, 19)}</Descriptions.Item>
          <Descriptions.Item label="Git">{detail.git_commit?.slice(0, 7)}{detail.git_dirty ? '*' : ''}</Descriptions.Item>
          <Descriptions.Item label="Critique">{detail.critique_enabled ? '开启' : '关闭'}</Descriptions.Item>
          <Descriptions.Item label="总耗时">{detail.total_elapsed?.toFixed(1)}s</Descriptions.Item>
          <Descriptions.Item label="数据完整性"><Tag color={detail.integrity === 'ok' ? 'success' : detail.integrity === 'warn' ? 'warning' : 'error'} style={{ margin: 0 }}>{detail.integrity}</Tag></Descriptions.Item>
          {detail.description && <Descriptions.Item label="描述" span={3}>{detail.description}</Descriptions.Item>}
          {env.python_version && <Descriptions.Item label="Python">{env.python_version}</Descriptions.Item>}
          {env.os && <Descriptions.Item label="平台">{env.os}</Descriptions.Item>}
          {(env.model || (env.provider && env.provider !== 'unknown')) && (
            <Descriptions.Item label="模型">
              {[env.model, env.provider !== 'unknown' ? env.provider : null].filter(Boolean).join(' / ')}
            </Descriptions.Item>
          )}
        </Descriptions>
      </Card>

      {/* 汇总指标 */}
      <Row gutter={[12, 12]}>
        {[
          { label: '完成率', value: `${((agg.completion_rate || 0) * 100).toFixed(0)}%`, color: (agg.completion_rate || 0) >= 1 ? '#3fb950' : '#d29922' },
          { label: '平均 Token', value: (agg.avg_tokens || 0).toFixed(0) },
          { label: '平均耗时', value: `${(agg.avg_elapsed || 0).toFixed(1)}s` },
          { label: 'P:C 比值', value: (agg.avg_pc_ratio || 0).toFixed(2) },
          { label: '缓存命中', value: `${((agg.avg_cache_hit_rate || 0) * 100).toFixed(0)}%` },
          { label: '总费用', value: `$${(agg.total_cost_usd || 0).toFixed(4)}` },
        ].map((item) => (
          <Col key={item.label} xs={8} sm={4}>
            <Card size="small" style={{ textAlign: 'center', background: isDark ? '#161b22' : '#fff', borderColor: isDark ? '#30363d' : '#d0d7de' }}>
              <div style={{ fontSize: 20, fontWeight: 700, color: item.color || (isDark ? '#c9d1d9' : '#1f2328') }}>{item.value}</div>
              <div style={{ fontSize: 11, color: isDark ? '#8b949e' : '#656d76' }}>{item.label}</div>
            </Card>
          </Col>
        ))}
      </Row>

      {/* 逐用例表 */}
      <Card size="small" title="逐用例结果"
        style={{ background: isDark ? '#161b22' : '#fff', borderColor: isDark ? '#30363d' : '#d0d7de' }}>
        <Table
          dataSource={cases}
          columns={caseColumns}
          rowKey="case_name"
          size="small"
          pagination={false}
          rowClassName={(r) => r.success ? '' : 'benchmark-row-failed'}
        />
      </Card>

      {/* 瓶颈分析 */}
      <BottleneckSection detail={detail} isDark={isDark} />

      {/* 质量验证 */}
      <QualitySection detail={detail} isDark={isDark} />

      {/* 多次运行统计 */}
      {cases.some((c) => c.repeat_runs && c.repeat_runs.length > 1) && (
        <Card size="small" title="多次运行统计"
          style={{ background: isDark ? '#161b22' : '#fff', borderColor: isDark ? '#30363d' : '#d0d7de' }}>
          <Table
            size="small" pagination={false} rowKey="case_name"
            dataSource={cases.filter((c) => c.repeat_runs && c.repeat_runs.length > 1)}
            columns={[
              { title: '用例', dataIndex: 'case_name', key: 'name' },
              { title: '次数', dataIndex: 'repeat_count', key: 'count', width: 60 },
              {
                title: 'Token (min/med/max)', key: 'tokens', width: 180,
                render: (_, r) => {
                  const runs = r.repeat_runs || []
                  const tokens = runs.map((rr) => rr.total_tokens || 0).sort((a, b) => a - b)
                  return tokens.length >= 2
                    ? `${tokens[0].toLocaleString()} / ${tokens[Math.floor(tokens.length / 2)].toLocaleString()} / ${tokens[tokens.length - 1].toLocaleString()}`
                    : '-'
                },
              },
              {
                title: '耗时 (min/med/max)', key: 'elapsed', width: 160,
                render: (_, r) => {
                  const runs = r.repeat_runs || []
                  const times = runs.map((rr) => rr.elapsed_seconds || 0).sort((a, b) => a - b)
                  return times.length >= 2
                    ? `${times[0].toFixed(1)} / ${times[Math.floor(times.length / 2)].toFixed(1)} / ${times[times.length - 1].toFixed(1)}s`
                    : '-'
                },
              },
            ]}
          />
        </Card>
      )}

      {/* 异常检测 */}
      <AnomalySection detail={detail} isDark={isDark} />
    </div>
  )
}
