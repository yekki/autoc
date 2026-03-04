import { useRef, useEffect } from 'react'
import { Tooltip } from 'antd'
import {
  CheckCircleFilled, CloseCircleFilled, SyncOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons'
import useStore from '../../stores/useStore'
import { formatTokens } from './utils'

const PHASE_CONFIG = {
  refine: { label: '优化', color: '#bc8cff', bg: 'rgba(188,140,255,0.1)' },
  planning: { label: 'Helper', color: '#58a6ff', bg: 'rgba(88,166,255,0.1)' },
  plan: { label: '规划', color: '#58a6ff', bg: 'rgba(88,166,255,0.1)' },
  dev: { label: '开发', color: '#3fb950', bg: 'rgba(63,185,80,0.1)' },
  test: { label: '测试', color: '#d29922', bg: 'rgba(210,153,34,0.1)' },
  fix: { label: '修复', color: '#f85149', bg: 'rgba(248,81,73,0.1)' },
}

function StatusIcon({ success, isLast, isRunning }) {
  if (isLast && isRunning) return <SyncOutlined spin style={{ color: '#58a6ff', fontSize: 11 }} />
  if (success === true) return <CheckCircleFilled style={{ color: '#3fb950', fontSize: 11 }} />
  if (success === false) return <CloseCircleFilled style={{ color: '#f85149', fontSize: 11 }} />
  return <ClockCircleOutlined style={{ color: '#8b949e', fontSize: 11 }} />
}

export default function IterationTimeline() {
  const theme = useStore((s) => s.theme)
  const iterations = useStore((s) => s.iterationHistory)
  const selectedIteration = useStore((s) => s.selectedIteration)
  const setSelectedIteration = useStore((s) => s.setSelectedIteration)
  const isRunning = useStore((s) => s.isRunning)
  const isDark = theme === 'dark'
  const scrollRef = useRef(null)

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollLeft = scrollRef.current.scrollWidth
    }
  }, [iterations.length])

  if (iterations.length === 0) return null

  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: isDark ? '#8b949e' : '#656d76', marginBottom: 8, textTransform: 'uppercase', letterSpacing: 0.5 }}>
        迭代时间线
      </div>
      <div
        ref={scrollRef}
        style={{
          display: 'flex', gap: 6, overflowX: 'auto', paddingBottom: 4,
          scrollbarWidth: 'thin',
        }}
      >
        {iterations.map((iter, idx) => {
          const cfg = PHASE_CONFIG[iter.phase] || PHASE_CONFIG.dev
          const isSelected = selectedIteration === iter.iteration
          const isLast = idx === iterations.length - 1
          const storyLabel = iter.storyId
            ? iter.storyId
            : iter.storyTitle
              ? iter.storyTitle.length > 12 ? iter.storyTitle.slice(0, 12) + '...' : iter.storyTitle
              : iter.phase === 'test' || iter.phase === 'fix' ? '全部' : '-'

          return (
            <Tooltip
              key={iter.iteration}
              title={
                <div style={{ fontSize: 12 }}>
                  <div>迭代 #{iter.iteration} — {cfg.label}</div>
                  {iter.storyTitle && <div>任务: {iter.storyTitle}</div>}
                  {iter.tokensUsed > 0 && <div>消耗：{iter.tokensUsed.toLocaleString()}</div>}
                  {iter.elapsedSeconds > 0 && <div>耗时：{iter.elapsedSeconds.toFixed(1)}s</div>}
                  {iter.bugs?.length > 0 && <div>缺陷：{iter.bugs.length} 个</div>}
                </div>
              }
            >
              <div
                onClick={() => setSelectedIteration(iter.iteration)}
                style={{
                  flexShrink: 0, width: 72, padding: '6px 8px',
                  borderRadius: 6, cursor: 'pointer',
                  background: isSelected
                    ? (isDark ? cfg.bg : cfg.bg)
                    : (isDark ? '#0d1117' : '#f6f8fa'),
                  border: `1.5px solid ${isSelected ? cfg.color : (isDark ? '#21262d' : '#e8e8e8')}`,
                  transition: 'all 0.15s',
                  textAlign: 'center',
                }}
              >
                <div style={{ fontSize: 10, fontWeight: 700, color: cfg.color, marginBottom: 2 }}>
                  {cfg.label}
                </div>
                <div style={{ fontSize: 14, fontWeight: 600, color: isDark ? '#c9d1d9' : '#1f2328', marginBottom: 2 }}>
                  #{iter.iteration}
                </div>
                {iter.tokensUsed > 0 && (
                  <div style={{ fontSize: 10, color: isDark ? '#6e7681' : '#8c959f', fontVariantNumeric: 'tabular-nums', marginBottom: 2 }}>
                    {formatTokens(iter.tokensUsed)}
                  </div>
                )}
                <div style={{ fontSize: 9, color: isDark ? '#484f58' : '#aaa', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', marginBottom: 2 }}>
                  {storyLabel}
                </div>
                <StatusIcon success={iter.success} isLast={isLast} isRunning={isRunning} />
              </div>
            </Tooltip>
          )
        })}
      </div>
    </div>
  )
}
