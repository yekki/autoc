import { useState, useEffect, useRef, useCallback } from 'react'
import useStore from '../../stores/useStore'

const STAGES = [
  { key: 'sandbox',  label: '沙箱' },
  { key: 'planning', label: '规划' },
  { key: 'dev',      label: '开发' },
  { key: 'critique', label: '评审' },
  { key: 'finalize', label: '收尾' },
]

function formatElapsed(seconds) {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

export default function PhaseProgress() {
  const theme = useStore((s) => s.theme)
  const pipelineStage = useStore((s) => s.pipelineStage)
  const isRunning = useStore((s) => s.isRunning)
  const currentIteration = useStore((s) => s.currentIteration)
  const isDark = theme === 'dark'

  const activeIdx = STAGES.findIndex((s) => s.key === pipelineStage)

  // 每阶段独立计时：{ sandbox: 12, planning: 8, ... }
  const [elapsed, setElapsed] = useState({})
  const timerRef = useRef(null)
  const stageStartRef = useRef(null)
  const prevStageRef = useRef('')

  const stopTimer = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
  }, [])

  useEffect(() => {
    if (!isRunning && pipelineStage !== 'done') {
      stopTimer()
      stageStartRef.current = null
      prevStageRef.current = ''
      setElapsed({})
      return
    }

    if (pipelineStage === 'done') {
      stopTimer()
      stageStartRef.current = null
      return
    }

    if (pipelineStage && pipelineStage !== prevStageRef.current) {
      // 冻结上一阶段的计时
      if (prevStageRef.current && stageStartRef.current) {
        const finalSec = Math.floor((Date.now() - stageStartRef.current) / 1000)
        const prev = prevStageRef.current
        setElapsed((e) => ({ ...e, [prev]: finalSec }))
      }

      stopTimer()
      prevStageRef.current = pipelineStage
      stageStartRef.current = Date.now()

      timerRef.current = setInterval(() => {
        if (stageStartRef.current) {
          const sec = Math.floor((Date.now() - stageStartRef.current) / 1000)
          setElapsed((e) => ({ ...e, [pipelineStage]: sec }))
        }
      }, 1000)
    }

    return () => stopTimer()
  }, [pipelineStage, isRunning, stopTimer])

  const showProgress = isRunning || pipelineStage === 'done'
  if (!showProgress) return null

  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 0 }}>
        {STAGES.map((stage, idx) => {
          const isActive = idx === activeIdx && pipelineStage !== 'done'
          const isPast = pipelineStage === 'done' ? true : idx < activeIdx
          const stageTime = elapsed[stage.key]
          const hasTime = stageTime != null && stageTime > 0

          let dotColor = isDark ? '#484f58' : '#d0d7de'
          let textColor = isDark ? '#484f58' : '#bbb'
          let timeColor = isDark ? '#8b949e' : '#999'
          if (isPast) {
            dotColor = '#3fb950'
            textColor = '#3fb950'
            timeColor = '#3fb950'
          } else if (isActive) {
            dotColor = '#58a6ff'
            textColor = isDark ? '#f0f6fc' : '#1f2328'
            timeColor = isDark ? '#58a6ff' : '#0969da'
          }

          return (
            <div key={stage.key} style={{ display: 'flex', alignItems: 'flex-start', flex: 1 }}>
              <div style={{
                display: 'flex', flexDirection: 'column', alignItems: 'center',
                minWidth: 36, flex: '0 0 auto',
              }}>
                <div style={{
                  width: 10, height: 10, borderRadius: '50%',
                  background: dotColor, transition: 'all 0.3s',
                  boxShadow: isActive ? `0 0 8px ${dotColor}` : 'none',
                  animation: isActive ? 'phaseProgressPulse 1.5s infinite' : 'none',
                }} />
                <span style={{
                  fontSize: 10, color: textColor, marginTop: 3,
                  fontWeight: isActive ? 600 : 400, whiteSpace: 'nowrap',
                }}>
                  {stage.label}
                </span>
                {(isActive || (isPast && hasTime)) && (
                  <span style={{
                    fontSize: 10, color: timeColor,
                    fontFamily: 'monospace', marginTop: 2,
                    letterSpacing: '0.5px', fontWeight: isActive ? 600 : 400,
                    opacity: isPast ? 0.8 : 1,
                  }}>
                    {formatElapsed(stageTime || 0)}
                  </span>
                )}
              </div>
              {idx < STAGES.length - 1 && (
                <div style={{
                  flex: 1, height: 2, margin: '4px 4px 0',
                  background: isPast ? '#3fb950' : (isDark ? '#21262d' : '#e8e8e8'),
                  borderRadius: 1, transition: 'background 0.3s',
                }} />
              )}
            </div>
          )
        })}
      </div>

      {isRunning && (currentIteration.maxRounds > 0 || currentIteration.maxIterations > 0) && (
        <div style={{
          display: 'flex', gap: 12, marginTop: 4, fontSize: 11,
          color: isDark ? '#8b949e' : '#656d76', fontFamily: 'monospace',
        }}>
          {currentIteration.maxRounds > 0 && (
            <span>Round {currentIteration.round}/{currentIteration.maxRounds}</span>
          )}
          {currentIteration.maxIterations > 0 && (
            <span>Iteration {currentIteration.iteration}/{currentIteration.maxIterations}</span>
          )}
        </div>
      )}

      <style>{`
        @keyframes phaseProgressPulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.5; }
        }
      `}</style>
    </div>
  )
}
