import { useEffect, useMemo } from 'react'
import { Card, Tag, Empty, Row, Col, Progress } from 'antd'
import {
  LoadingOutlined, WarningOutlined, CheckCircleOutlined,
  RightOutlined, FireOutlined, InfoCircleOutlined,
} from '@ant-design/icons'
import useStore from '../../stores/useStore'

// ─── 工具函数 ────────────────────────────────────────────────
function fmtNum(n) { return n >= 1000 ? `${(n / 1000).toFixed(1)}K` : String(Math.round(n || 0)) }
function fmtDelta(delta) {
  // delta=0 或极小变化（<0.1%）不显示
  if (delta == null || isNaN(delta) || Math.abs(delta) < 0.001) return null
  const positive = delta > 0
  const pct = Math.abs(delta * 100).toFixed(0)
  return { label: `${positive ? '+' : '−'}${pct}%`, positive }
}
// 数组中位数
function median(arr) {
  if (!arr.length) return null
  const s = [...arr].sort((a, b) => a - b)
  const m = Math.floor(s.length / 2)
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2
}
function healthColor(v) { return v >= 75 ? '#3fb950' : v >= 55 ? '#d29922' : '#f85149' }

// ─── 综合健康度仪表盘 ─────────────────────────────────────────
function HealthGauge({ score, breakdown, isDark }) {
  const r = 62, cx = 100, cy = 82
  const arc = Math.PI * r
  const filled = (Math.min(Math.max(score, 0), 100) / 100) * arc
  const track = isDark ? '#21262d' : '#e1e4e8'
  const dim = isDark ? '#6e7681' : '#8c959f'
  const color = healthColor(score)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
      <svg width="200" height="108" viewBox="0 0 200 108" style={{ overflow: 'visible' }}>
        <circle cx={cx} cy={cy} r={r} fill="none" stroke={track} strokeWidth="11"
          strokeLinecap="round"
          strokeDasharray={`${arc} ${arc * 2 + 50}`}
          transform={`rotate(180 ${cx} ${cy})`} />
        <circle cx={cx} cy={cy} r={r} fill="none" stroke={color} strokeWidth="11"
          strokeLinecap="round"
          strokeDasharray={`${filled} ${arc * 2 + 50}`}
          transform={`rotate(180 ${cx} ${cy})`}
          style={{ transition: 'stroke-dasharray 0.6s ease' }} />
        <text x={cx} y={cy + 4} textAnchor="middle"
          fill={isDark ? '#c9d1d9' : '#1f2328'} fontSize="30" fontWeight="700">{score}</text>
        <text x={cx} y={cy + 20} textAnchor="middle" fill={dim} fontSize="11">综合健康度</text>
      </svg>
      <div style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: 7, paddingTop: 2 }}>
        {breakdown.map(({ label, value, color: c }) => (
          <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 11, color: dim, width: 72, flexShrink: 0 }}>{label}</span>
            <div style={{ flex: 1, height: 5, background: track, borderRadius: 3 }}>
              <div style={{ width: `${value}%`, height: '100%', background: c, borderRadius: 3, transition: 'width 0.5s' }} />
            </div>
            <span style={{ fontSize: 11, color: c, width: 32, textAlign: 'right' }}>{value}%</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── 统计卡片 ─────────────────────────────────────────────────
// delta: 正数=增加，增加是坏事（Token/耗时语义），用红色标注
function StatCard({ title, value, unit, delta, subtext, valueColor, isDark }) {
  const d = fmtDelta(delta)
  return (
    <Card size="small"
      style={{ background: isDark ? '#161b22' : '#fff', borderColor: isDark ? '#30363d' : '#d0d7de', height: '100%' }}
      styles={{ body: { padding: '14px 16px' } }}>
      <div style={{ fontSize: 12, color: isDark ? '#8b949e' : '#656d76', marginBottom: 6 }}>{title}</div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginBottom: 4 }}>
        <span style={{ fontSize: 26, fontWeight: 700, color: valueColor || (isDark ? '#c9d1d9' : '#1f2328') }}>
          {value}
        </span>
        {unit && <span style={{ fontSize: 13, color: isDark ? '#8b949e' : '#656d76' }}>{unit}</span>}
        {d && (
          <span style={{ fontSize: 11, fontWeight: 600, color: d.positive ? '#f85149' : '#3fb950' }}>
            {d.label} vs 上次
          </span>
        )}
      </div>
      {subtext && <div style={{ fontSize: 11, color: isDark ? '#6e7681' : '#8c959f' }}>{subtext}</div>}
    </Card>
  )
}

// ─── Token & 耗时双轴趋势图 ───────────────────────────────────
function TrendChart({ runs, isDark, onClickRun }) {
  if (runs.length < 2) return null
  const recent = [...runs].slice(0, 10).reverse()
  const W = 600, H = 130, PL = 52, PR = 52, PT = 8, PB = 32
  const cW = W - PL - PR, cH = H - PT - PB

  const tokens = recent.map((r) => r.avg_tokens || 0)
  const elapseds = recent.map((r) => r.avg_elapsed || 0)
  const maxTok = Math.max(...tokens) * 1.2 || 1
  const maxEl = Math.max(...elapseds) * 1.2 || 1

  const tx = (i) => PL + (i / Math.max(recent.length - 1, 1)) * cW
  const tyT = (v) => PT + cH - (v / maxTok) * cH
  const tyE = (v) => PT + cH - (v / maxEl) * cH

  const tokPath = tokens.map((v, i) => `${i === 0 ? 'M' : 'L'}${tx(i).toFixed(1)},${tyT(v).toFixed(1)}`).join(' ')
  const elPath = elapseds.map((v, i) => `${i === 0 ? 'M' : 'L'}${tx(i).toFixed(1)},${tyE(v).toFixed(1)}`).join(' ')

  const grid = isDark ? '#21262d' : '#e8ecf0'
  const dim = isDark ? '#6e7681' : '#8c959f'

  return (
    <Card size="small"
      title={<span style={{ fontSize: 13, fontWeight: 600 }}>Token & 耗时趋势（最近 {recent.length} 次）</span>}
      extra={<span style={{ fontSize: 11, color: dim }}>
        <span style={{ color: '#58a6ff' }}>— Token</span>
        <span style={{ margin: '0 8px', color: '#f0883e' }}>— 耗时</span>
      </span>}
      styles={{ body: { padding: '8px 16px 12px' } }}
      style={{ background: isDark ? '#161b22' : '#fff', borderColor: isDark ? '#30363d' : '#d0d7de' }}>
      <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ overflow: 'visible' }}>
        {/* grid lines */}
        {[0.25, 0.5, 0.75, 1].map((t) => (
          <line key={t} x1={PL} x2={W - PR} y1={PT + cH * (1 - t)} y2={PT + cH * (1 - t)}
            stroke={grid} strokeWidth="1" />
        ))}
        {/* Y axis labels - left (Token) */}
        {[0, 0.5, 1].map((t) => (
          <text key={`yt${t}`} x={PL - 6} y={PT + cH * (1 - t) + 4} textAnchor="end"
            fontSize="10" fill={dim}>{fmtNum(maxTok * t)}</text>
        ))}
        {/* Y axis labels - right (Elapsed) */}
        {[0, 0.5, 1].map((t) => (
          <text key={`ye${t}`} x={W - PR + 6} y={PT + cH * (1 - t) + 4} textAnchor="start"
            fontSize="10" fill={dim}>{Math.round(maxEl * t)}s</text>
        ))}
        {/* Token line */}
        <path d={tokPath} fill="none" stroke="#58a6ff" strokeWidth="2" strokeLinejoin="round" />
        {tokens.map((v, i) => (
          <circle key={`td${i}`} cx={tx(i)} cy={tyT(v)} r="3.5" fill="#58a6ff"
            style={{ cursor: 'pointer' }} onClick={() => onClickRun(recent[i].tag)}
            title={`${recent[i].tag}: ${Math.round(v).toLocaleString()} tok`} />
        ))}
        {/* Elapsed line */}
        <path d={elPath} fill="none" stroke="#f0883e" strokeWidth="2" strokeLinejoin="round" />
        {elapseds.map((v, i) => (
          <circle key={`ed${i}`} cx={tx(i)} cy={tyE(v)} r="3.5" fill="#f0883e"
            style={{ cursor: 'pointer' }} onClick={() => onClickRun(recent[i].tag)}
            title={`${recent[i].tag}: ${v.toFixed(1)}s`} />
        ))}
        {/* X axis labels — 保留前缀，超长则末尾省略 */}
        {recent.map((r, i) => (
          <text key={`xl${i}`} x={tx(i)} y={H - 4} textAnchor="middle"
            fontSize="9.5" fill={dim}
            style={{ cursor: 'pointer' }} onClick={() => onClickRun(r.tag)}>
            {r.tag.length > 14 ? `${r.tag.slice(0, 12)}…` : r.tag}
          </text>
        ))}
      </svg>
    </Card>
  )
}

// ─── 最近运行卡片 ─────────────────────────────────────────────
function RecentRunCard({ run, prev, isDark, onClick }) {
  const rate = run.completion_rate || 0
  // 只在用例数相同时比较 Token，避免跨用例集的无效对比
  const tokenDelta = (prev?.avg_tokens && prev?.case_count === run.case_count)
    ? (run.avg_tokens - prev.avg_tokens) / prev.avg_tokens
    : null
  const d = fmtDelta(tokenDelta)
  const integrityColor = run.integrity === 'ok' ? '#3fb950' : run.integrity === 'warn' ? '#d29922' : '#f85149'

  return (
    <Card hoverable size="small" onClick={() => onClick(run.tag)}
      style={{ background: isDark ? '#161b22' : '#fff', borderColor: isDark ? '#30363d' : '#d0d7de', borderRadius: 8 }}
      styles={{ body: { padding: '12px 16px' } }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
        <span style={{ fontWeight: 600, fontSize: 13, color: isDark ? '#c9d1d9' : '#1f2328', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {run.tag}
        </span>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          {d && (
            <span style={{ fontSize: 11, fontWeight: 600, color: d.positive ? '#f85149' : '#3fb950' }}>
              Token {d.label}
            </span>
          )}
          <Tag color={rate >= 1 ? 'success' : rate >= 0.5 ? 'warning' : 'error'} style={{ margin: 0 }}>
            {(rate * 100).toFixed(0)}%
          </Tag>
        </div>
      </div>
      <div style={{ display: 'flex', gap: 12, fontSize: 12, color: isDark ? '#8b949e' : '#656d76', flexWrap: 'wrap' }}>
        <span>{fmtNum(run.avg_tokens || 0)} tok</span>
        <span>{(run.avg_elapsed || 0).toFixed(1)}s</span>
        <span>{run.case_count} 用例</span>
        {run.total_cost_usd > 0 && <span>${run.total_cost_usd.toFixed(3)}</span>}
        {run.environment?.model && (
          <span style={{ color: isDark ? '#6e7681' : '#9a9ea7' }}>{run.environment.model}</span>
        )}
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6, fontSize: 11, color: isDark ? '#6e7681' : '#8c959f' }}>
        <span>{run.timestamp?.replace('T', ' ').slice(0, 16)}{run.git_commit ? ` · ${run.git_commit.slice(0, 7)}${run.git_dirty ? '*' : ''}` : ''}</span>
        <span style={{ color: integrityColor }}>{run.integrity === 'ok' ? '数据完整' : run.integrity === 'warn' ? '数据不完整' : '数据异常'}</span>
      </div>
    </Card>
  )
}

// ─── 问题看板 ─────────────────────────────────────────────────
function ProblemBoard({ problems, isDark }) {
  const blocking = problems.filter((p) => p.level === 'error')
  const attention = problems.filter((p) => p.level === 'warn')

  if (!problems.length) {
    return (
      <Card size="small"
        title={<span style={{ fontSize: 13, fontWeight: 600 }}>问题看板</span>}
        style={{ background: isDark ? '#161b22' : '#fff', borderColor: isDark ? '#30363d' : '#d0d7de' }}
        styles={{ body: { padding: '12px 16px' } }}>
        <div style={{ textAlign: 'center', padding: '16px 0', color: '#3fb950', fontSize: 13 }}>
          <CheckCircleOutlined style={{ marginRight: 6 }} />无异常，状态健康
        </div>
      </Card>
    )
  }

  return (
    <Card size="small"
      title={<span style={{ fontSize: 13, fontWeight: 600 }}>问题看板</span>}
      style={{ background: isDark ? '#161b22' : '#fff', borderColor: isDark ? '#30363d' : '#d0d7de' }}
      styles={{ body: { padding: '8px 12px' } }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {blocking.length > 0 && (
          <div>
            <div style={{ fontSize: 11, fontWeight: 600, color: '#f85149', marginBottom: 5 }}>
              🔴 阻塞问题（{blocking.length}）
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {blocking.map((p, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 8, padding: '7px 10px', background: isDark ? '#1c0e0e' : '#fff5f5', borderRadius: 6, borderLeft: '3px solid #f85149' }}>
                  <WarningOutlined style={{ color: '#f85149', fontSize: 12, marginTop: 1.5, flexShrink: 0 }} />
                  <span style={{ fontSize: 12, color: isDark ? '#c9d1d9' : '#1f2328', lineHeight: 1.5 }}>{p.text}</span>
                </div>
              ))}
            </div>
          </div>
        )}
        {attention.length > 0 && (
          <div>
            <div style={{ fontSize: 11, fontWeight: 600, color: '#d29922', marginBottom: 5 }}>
              🟠 关注项（{attention.length}）
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {attention.map((p, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 8, padding: '7px 10px', background: isDark ? '#191408' : '#fffbf0', borderRadius: 6, borderLeft: '3px solid #d29922' }}>
                  <InfoCircleOutlined style={{ color: '#d29922', fontSize: 12, marginTop: 1.5, flexShrink: 0 }} />
                  <span style={{ fontSize: 12, color: isDark ? '#c9d1d9' : '#1f2328', lineHeight: 1.5 }}>{p.text}</span>
                </div>
              ))}
            </div>
          </div>
        )}
        {/* blocking/attention 不可能同时为 0（外部已 guard problems.length > 0），此处无需兜底 */}
      </div>
    </Card>
  )
}

// ─── 实时运行进度卡片（保留原有逻辑）──────────────────────────
function LiveProgressCard({ isDark }) {
  const running = useStore((s) => s.benchmarkRunning)
  const progress = useStore((s) => s.benchmarkRunProgress)
  if (!running && !progress) return null
  const isComplete = progress?.lastEvent?.type === 'run_complete'
  const isError = progress?.lastEvent?.type === 'run_error'
  const isDisconnected = progress?.status === 'disconnected'
  if (isComplete || isError) return null

  if (isDisconnected) {
    return (
      <Card size="small"
        style={{ background: isDark ? '#161b22' : '#fff', borderColor: isDark ? '#9e6a03' : '#d29922' }}
        styles={{ body: { padding: '10px 16px' } }}>
        <span style={{ fontSize: 13, color: '#d29922' }}>
          ⚠ 与后端连接中断，{progress?.tag || '...'} 可能仍在后台运行，请稍后查看结果。
        </span>
      </Card>
    )
  }

  const events = progress?.events || []
  const startEvt = events.find((e) => e.type === 'run_start')
  const doneEvts = events.filter((e) => e.type === 'case_done')
  const lastCaseStart = events.filter((e) => e.type === 'case_start').at(-1)
  const total = startEvt?.total_cases || 0
  const completed = doneEvts.length
  const tag = progress?.tag || startEvt?.tag || '...'
  const pct = total > 0 ? Math.round((completed / total) * 100) : 0

  return (
    <Card size="small"
      style={{ background: isDark ? '#161b22' : '#fff', borderColor: isDark ? '#1f6feb' : '#0969da' }}
      styles={{ body: { padding: '12px 16px' } }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 8, fontWeight: 600, fontSize: 13, color: isDark ? '#58a6ff' : '#0969da' }}>
          <LoadingOutlined spin />正在运行：{tag}
        </span>
        {total > 0 && <span style={{ fontSize: 12, color: isDark ? '#8b949e' : '#656d76' }}>{completed} / {total} 用例</span>}
      </div>
      {total > 0 && (
        <Progress percent={pct} size="small" strokeColor={isDark ? '#58a6ff' : '#0969da'}
          trailColor={isDark ? '#21262d' : '#e1e4e8'} showInfo={false}
          style={{ marginBottom: lastCaseStart ? 6 : 0 }} />
      )}
      {lastCaseStart && (
        <div style={{ fontSize: 12, color: isDark ? '#6e7681' : '#8c959f' }}>
          当前用例：<span style={{ color: isDark ? '#c9d1d9' : '#1f2328' }}>{lastCaseStart.case}</span>
          {doneEvts.find((e) => e.case === lastCaseStart.case) ? '' : ' ...'}
        </div>
      )}
      {!total && <div style={{ fontSize: 12, color: isDark ? '#6e7681' : '#8c959f' }}>正在初始化...</div>}
    </Card>
  )
}

// ─── 数据计算函数 ─────────────────────────────────────────────
function computeDashboardData(history) {
  if (!history.length) return null
  const latest = history[0]
  const prev = history[1]

  // 各分项健康度（0-100）
  const funcScore = Math.round((latest.completion_rate || 0) * 100)
  const cacheRate = latest.avg_cache_hit_rate != null ? Math.round(latest.avg_cache_hit_rate * 100) : null
  const cacheScore = cacheRate != null ? Math.min(cacheRate, 100) : 70

  // Token/耗时效率：
  //   ≥6 条：近 3 次中位数 vs 前 3 次中位数（抑制 LLM 随机波动）
  //   3-5 条：近半 vs 旧半
  //   2 条：latest vs prev（直接对比）
  //   <2 条：默认 70
  function deltaScore(field) {
    const vals = history.map((r) => r[field]).filter((v) => v > 0)
    if (vals.length < 2) return 70
    let recentMed, prevMed
    if (vals.length === 2) {
      recentMed = vals[0]
      prevMed = vals[1]
    } else {
      const split = vals.length >= 6 ? 3 : Math.ceil(vals.length / 2)
      recentMed = median(vals.slice(0, split))
      prevMed = median(vals.slice(split))
    }
    if (!recentMed || !prevMed) return 70
    const delta = (recentMed - prevMed) / prevMed
    return delta <= -0.15 ? 95 : delta <= -0.05 ? 85 : delta <= 0.05 ? 75 : delta <= 0.15 ? 55 : 35
  }

  const tokenScore = deltaScore('avg_tokens')
  const elapsedScore = deltaScore('avg_elapsed')

  const health = Math.round(funcScore * 0.40 + tokenScore * 0.25 + elapsedScore * 0.20 + cacheScore * 0.15)
  const breakdown = [
    { label: '功能完整度', value: funcScore, color: healthColor(funcScore) },
    { label: 'Token 效率', value: tokenScore, color: healthColor(tokenScore) },
    { label: '耗时效率', value: elapsedScore, color: healthColor(elapsedScore) },
    { label: '缓存命中率', value: cacheScore, color: healthColor(cacheScore) },
  ]

  // 问题看板
  const problems = []
  if ((latest.completion_rate || 0) < 1) {
    // 用整数运算避免浮点误差
    const total = latest.case_count || 0
    const passed = Math.round((latest.completion_rate || 0) * total)
    const failed = total - passed
    problems.push({ level: 'error', text: `${failed} 个用例执行失败（最新运行：${latest.tag}）` })
  }
  if (latest.integrity === 'bad') {
    problems.push({ level: 'error', text: `结果数据异常（integrity=bad），请检查执行日志` })
  }
  if (!latest.environment?.model) {
    problems.push({ level: 'warn', text: '环境元数据缺失：model/provider 为空，结果不可溯源' })
  }
  if (cacheRate != null && cacheRate < 75) {
    problems.push({ level: 'warn', text: `缓存命中率 ${cacheRate}%，低于目标 80%，影响成本` })
  }
  // Token 趋势警告：用中位数而非单次对比，减少噪声
  const recentToks = history.slice(0, 3).map((r) => r.avg_tokens).filter((v) => v > 0)
  const prevToks = history.slice(3, 6).map((r) => r.avg_tokens).filter((v) => v > 0)
  const recentTokMed = median(recentToks)
  const prevTokMed = median(prevToks)
  if (recentTokMed && prevTokMed && (recentTokMed - prevTokMed) / prevTokMed > 0.2) {
    problems.push({ level: 'warn', text: `Token 消耗（近3次中位 ${fmtNum(recentTokMed)}）较前期增加 ${Math.round((recentTokMed - prevTokMed) / prevTokMed * 100)}%，注意效率退化` })
  }
  if (latest.integrity === 'warn') {
    problems.push({ level: 'warn', text: `结果数据不完整（integrity=warn），部分指标可能不准确` })
  }

  return { health, breakdown, problems, latest, prev, cacheRate }
}

// ─── 主组件 ──────────────────────────────────────────────────
export default function DashboardView() {
  const theme = useStore((s) => s.theme)
  const history = useStore((s) => s.benchmarkHistory)
  const fetchHistory = useStore((s) => s.fetchBenchmarkHistory)
  const fetchDetail = useStore((s) => s.fetchBenchmarkDetail)
  const isDark = theme === 'dark'

  useEffect(() => { fetchHistory() }, [fetchHistory])

  const data = useMemo(() => computeDashboardData(history), [history])

  if (!history.length) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
        <LiveProgressCard isDark={isDark} />
        <Empty description="暂无运行记录" style={{ padding: '60px 0' }}>
          <span style={{ color: isDark ? '#8b949e' : '#656d76', fontSize: 13 }}>
            点击右上角「发起测试」开始首次 Benchmark
          </span>
        </Empty>
      </div>
    )
  }

  const { health, breakdown, problems, latest, prev, cacheRate } = data
  // 只在同用例数的相邻运行之间计算 delta，避免跨用例集的无效对比
  const sameCases = prev?.case_count === latest.case_count
  const tokenDelta = (sameCases && prev?.avg_tokens && latest.avg_tokens) ? (latest.avg_tokens - prev.avg_tokens) / prev.avg_tokens : null
  const elapsedDelta = (sameCases && prev?.avg_elapsed && latest.avg_elapsed) ? (latest.avg_elapsed - prev.avg_elapsed) / prev.avg_elapsed : null

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <LiveProgressCard isDark={isDark} />

      {/* 健康度 + 统计卡片 */}
      <Row gutter={[16, 16]} align="stretch">
        <Col xs={24} sm={8}>
          <Card size="small"
            style={{ background: isDark ? '#161b22' : '#fff', borderColor: isDark ? '#30363d' : '#d0d7de', height: '100%' }}
            styles={{ body: { padding: '14px 16px' } }}>
            <HealthGauge score={health} breakdown={breakdown} isDark={isDark} />
          </Card>
        </Col>
        <Col xs={24} sm={16}>
          <Row gutter={[12, 12]} style={{ height: '100%' }}>
            <Col xs={12}>
              <StatCard
                title={<><CheckCircleOutlined style={{ marginRight: 4 }} />最新完成率</>}
                value={`${((latest.completion_rate || 0) * 100).toFixed(0)}%`}
                valueColor={(latest.completion_rate || 0) >= 1 ? '#3fb950' : (latest.completion_rate || 0) >= 0.5 ? '#d29922' : '#f85149'}
                subtext={`${latest.case_count || 0} 个用例 · ${latest.integrity === 'ok' ? '数据完整' : latest.integrity === 'warn' ? '数据不完整' : '数据异常'}`}
                isDark={isDark}
              />
            </Col>
            <Col xs={12}>
              <StatCard
                title={<><FireOutlined style={{ marginRight: 4 }} />Token 消耗</>}
                value={Math.round(latest.avg_tokens || 0).toLocaleString()}
                delta={tokenDelta}
                subtext={latest.total_cost_usd > 0 ? `$${latest.total_cost_usd.toFixed(3)}${latest.environment?.model ? ` · ${latest.environment.model}` : ''}` : (latest.environment?.model || '—')}
                isDark={isDark}
              />
            </Col>
            <Col xs={12}>
              <StatCard
                title={<><RightOutlined style={{ marginRight: 4 }} />平均耗时</>}
                value={(latest.avg_elapsed || 0).toFixed(1)}
                unit="s"
                delta={elapsedDelta}
                subtext={latest.avg_pc_ratio ? `P:C = ${latest.avg_pc_ratio.toFixed(1)}:1` : undefined}
                isDark={isDark}
              />
            </Col>
            <Col xs={12}>
              <StatCard
                title="缓存命中率"
                value={cacheRate != null ? `${cacheRate}%` : '—'}
                valueColor={cacheRate != null ? (cacheRate >= 80 ? '#3fb950' : cacheRate >= 65 ? '#d29922' : '#f85149') : undefined}
                subtext={cacheRate != null ? (cacheRate >= 80 ? '✓ 达到目标 ≥80%' : `目标 ≥80%，差 ${80 - cacheRate}pp`) : '数据不足'}
                isDark={isDark}
              />
            </Col>
          </Row>
        </Col>
      </Row>

      {/* 趋势图 */}
      <TrendChart runs={history} isDark={isDark} onClickRun={fetchDetail} />

      {/* 最近运行 + 问题看板 */}
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={14}>
          <div>
            <h4 style={{ margin: '0 0 10px', fontSize: 14, fontWeight: 600, color: isDark ? '#c9d1d9' : '#1f2328' }}>
              最近运行
            </h4>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {history.slice(0, 4).map((r, i) => (
                <RecentRunCard key={r.tag} run={r} prev={history[i + 1]} isDark={isDark} onClick={fetchDetail} />
              ))}
            </div>
          </div>
        </Col>
        <Col xs={24} sm={10}>
          <div>
            <h4 style={{ margin: '0 0 10px', fontSize: 14, fontWeight: 600, color: isDark ? '#c9d1d9' : '#1f2328' }}>
              问题看板
            </h4>
            <ProblemBoard problems={problems} isDark={isDark} />
          </div>
        </Col>
      </Row>
    </div>
  )
}
