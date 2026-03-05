import { useState, useMemo, useEffect } from 'react'
import { Card, Tag, Button } from 'antd'
import {
  CheckCircleFilled, CloseCircleFilled, ClockCircleOutlined,
  DownOutlined, RightOutlined, PlusOutlined,
} from '@ant-design/icons'
import useStore from '../../../stores/useStore'
import * as api from '../../../services/api'
import { formatTokenCount } from '../helpers'

function parseMajor(ver) {
  if (!ver) return 0
  const m = String(ver).match(/^(\d+)/)
  return m ? parseInt(m[1], 10) : 0
}

function VersionTreeItem({ v, isDark, dimColor, mutedColor }) {
  const sectionKey = `version-tree-${v.version}`
  const storedCollapsed = useStore(s => s.collapsedSections[sectionKey])
  const setSectionCollapsed = useStore(s => s.setSectionCollapsed)
  const isPatch = v.requirement_type === 'patch'
  const shouldAutoExpand = !v.success
  const expanded = storedCollapsed === undefined ? shouldAutoExpand : !storedCollapsed

  const tasks = v.tasks || []
  const bugs = v.bugs_fixed || []
  const hasContent = tasks.length > 0 || bugs.length > 0 || v.requirement
  const passedCount = tasks.filter(t => t.passes).length

  const statusIcon = v.success
    ? <CheckCircleFilled style={{ color: '#3fb950', fontSize: 13 }} />
    : <CloseCircleFilled style={{ color: '#f85149', fontSize: 13 }} />

  const typeLabel = v.requirement_type === 'primary' ? '主需求'
    : v.requirement_type === 'secondary' ? '次级需求'
    : v.requirement_type === 'patch' ? '补丁' : ''

  const timeStr = useMemo(() => {
    if (!v.started_at) return ''
    const fmt = (ts) => new Date(ts * 1000).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
    return `${fmt(v.started_at)} → ${fmt(v.ended_at || v.started_at)}`
  }, [v.started_at, v.ended_at])

  return (
    <div style={{ marginLeft: isPatch ? 20 : 0 }}>
      <div
        onClick={() => hasContent && setSectionCollapsed(sectionKey, expanded)}
        style={{
          display: 'flex', alignItems: 'center', gap: 8, padding: '8px 4px',
          cursor: hasContent ? 'pointer' : 'default',
          borderBottom: `1px solid ${isDark ? '#161b22' : '#f6f8fa'}`,
        }}
      >
        {hasContent
          ? <span style={{ width: 14, textAlign: 'center' }}>
              {expanded
                ? <DownOutlined style={{ fontSize: 9, color: dimColor }} />
                : <RightOutlined style={{ fontSize: 9, color: dimColor }} />}
            </span>
          : <span style={{ width: 14 }} />}
        <Tag style={{
          margin: 0, fontSize: 11, fontWeight: 600, fontFamily: 'monospace',
          minWidth: 48, textAlign: 'center',
          border: 'none', background: isDark ? '#21262d' : '#eef1f4',
          color: isDark ? '#c9d1d9' : '#1f2328',
        }}>
          v{v.version}
        </Tag>
        {statusIcon}
        {timeStr && <span style={{ fontSize: 10, color: dimColor, fontFamily: 'monospace' }}>{timeStr}</span>}
        {v.total_tokens > 0 && <span style={{ fontSize: 10, color: dimColor, fontFamily: 'monospace' }}>{formatTokenCount(v.total_tokens)}</span>}
        <span style={{ flex: 1 }} />
        {typeLabel && <span style={{ fontSize: 10, color: mutedColor }}>{typeLabel}</span>}
        {tasks.length > 0 && (
          <span style={{ fontSize: 11, fontFamily: 'monospace', color: mutedColor }}>{passedCount}/{tasks.length}</span>
        )}
      </div>

      {expanded && hasContent && (
        <div style={{
          padding: '8px 12px 8px 28px',
          borderBottom: `1px solid ${isDark ? '#161b22' : '#f6f8fa'}`,
          background: isDark ? '#0d1117' : '#fafbfc',
          fontSize: 12,
        }}>
          {v.requirement && (
            <div style={{ color: mutedColor, marginBottom: 6, lineHeight: 1.6, fontSize: 12 }}>
              {v.requirement}
            </div>
          )}
          {v.tech_stack?.length > 0 && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 8 }}>
              {v.tech_stack.map((t, i) => <Tag key={i} style={{ margin: 0, fontSize: 10 }}>{t}</Tag>)}
            </div>
          )}
          {tasks.length > 0 && tasks.map((t, i) => {
            const isFailed = t.status === 'failed' || (!t.passes && t.status !== 'pending')
            const failReason = t.error || t.error_info?.message || ''
            return (
              <div key={t.id || i}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '3px 0' }}>
                  {t.passes
                    ? <CheckCircleFilled style={{ color: '#3fb950', fontSize: 11 }} />
                    : t.status === 'failed'
                      ? <CloseCircleFilled style={{ color: '#f85149', fontSize: 11 }} />
                      : <ClockCircleOutlined style={{ color: dimColor, fontSize: 11 }} />}
                  <span style={{ color: dimColor, fontFamily: 'monospace', fontSize: 10 }}>{t.id}</span>
                  <span style={{ flex: 1, color: isDark ? '#c9d1d9' : '#1f2328' }}>{t.title}</span>
                  {t.elapsed_seconds > 0 && (
                    <span style={{ color: dimColor, fontFamily: 'monospace', fontSize: 10 }}>
                      {t.elapsed_seconds >= 60
                        ? `${Math.floor(t.elapsed_seconds / 60)}m${Math.round(t.elapsed_seconds % 60)}s`
                        : `${Math.round(t.elapsed_seconds)}s`}
                    </span>
                  )}
                  {t.tokens_used > 0 && <span style={{ color: dimColor, fontFamily: 'monospace', fontSize: 10 }}>{formatTokenCount(t.tokens_used)}</span>}
                </div>
                {isFailed && failReason && (
                  <div style={{ marginLeft: 18, padding: '2px 6px', fontSize: 10, color: '#f85149', lineHeight: 1.4 }}>
                    {failReason}
                  </div>
                )}
              </div>
            )
          })}
          {bugs.length > 0 && bugs.map((b, i) => (
            <div key={b.id || i} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '3px 0' }}>
              {b.status === 'fixed'
                ? <CheckCircleFilled style={{ color: '#3fb950', fontSize: 11 }} />
                : <CloseCircleFilled style={{ color: '#f85149', fontSize: 11 }} />}
              <span style={{ color: isDark ? '#c9d1d9' : '#1f2328' }}>{b.title}</span>
              <span style={{ fontSize: 10, color: dimColor }}>{b.status}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export function VersionTimeline({ isDark, projectName, onAddFeature }) {
  const [allVersions, setAllVersions] = useState([])
  const [loading, setLoading] = useState(false)
  const isRunning = useStore(s => s.isRunning)
  const storeProject = useStore(s => s.getSelectedProject)()
  const expectedVersion = useStore(s => s.executionExpectedVersion)
  const executionSummary = useStore(s => s.executionSummary)

  const summaryKey = executionSummary ? `${executionSummary.success}-${executionSummary.tasks_total}` : ''

  useEffect(() => {
    if (!projectName) return
    let cancelled = false
    const doFetch = () => {
      setLoading(true)
      api.fetchProjectVersions(projectName)
        .then(data => { if (!cancelled) setAllVersions(data?.versions || []) })
        .catch(() => {})
        .finally(() => { if (!cancelled) setLoading(false) })
    }
    if (!isRunning && summaryKey) {
      const timer = setTimeout(doFetch, 500)
      return () => { cancelled = true; clearTimeout(timer) }
    }
    doFetch()
    return () => { cancelled = true }
  }, [projectName, isRunning, summaryKey])

  const currentVersion = expectedVersion || executionSummary?.version || storeProject?.version || '1.0.0'
  const currentMajor = parseMajor(currentVersion)
  const versions = useMemo(
    () => allVersions.filter(v => parseMajor(v.version) === currentMajor),
    [allVersions, currentMajor]
  )

  if (versions.length === 0 && !loading) return null

  const dimColor = isDark ? '#6e7681' : '#8c959f'
  const mutedColor = isDark ? '#8b949e' : '#656d76'

  return (
    <Card size="small" style={{ marginBottom: 12 }}
      title={<span style={{ fontSize: 13 }}>迭代时间线</span>}
      extra={
        !isRunning && onAddFeature && versions.length > 0 && (
          <Button size="small" type="link" icon={<PlusOutlined />} onClick={onAddFeature}>
            添加/修复
          </Button>
        )
      }
    >
      {versions.map((v, idx) => (
        <VersionTreeItem key={v.version || idx} v={v} isDark={isDark}
          dimColor={dimColor} mutedColor={mutedColor} />
      ))}
    </Card>
  )
}
