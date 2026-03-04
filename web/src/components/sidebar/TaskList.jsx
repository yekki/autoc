import { Tooltip } from 'antd'
import {
  CheckCircleFilled,
  CloseCircleFilled,
  ClockCircleOutlined,
  LoadingOutlined,
  MinusCircleOutlined,
} from '@ant-design/icons'
import useStore from '../../stores/useStore'

const STATUS_CONFIG = {
  verified: { icon: <CheckCircleFilled style={{ color: '#3fb950' }} />, label: '已验证' },
  completed: { icon: <CheckCircleFilled style={{ color: '#58a6ff' }} />, label: '已完成' },
  in_progress: { icon: <LoadingOutlined style={{ color: '#d29922' }} />, label: '进行中' },
  failed: { icon: <CloseCircleFilled style={{ color: '#f85149' }} />, label: '失败' },
  pending: { icon: <ClockCircleOutlined style={{ color: '#8b949e' }} />, label: '待处理' },
}

export default function TaskList() {
  const theme = useStore((s) => s.theme)
  const taskList = useStore((s) => s.executionTaskList)
  const selectedTaskId = useStore((s) => s.selectedTaskId)
  const setActiveTab = useStore((s) => s.setActiveTab)
  const setSelectedTaskId = useStore((s) => s.setSelectedTaskId)
  const isDark = theme === 'dark'

  if (taskList.length === 0) {
    return (
      <div style={{ padding: '16px 12px', textAlign: 'center' }}>
        <MinusCircleOutlined style={{ fontSize: 20, color: isDark ? '#484f58' : '#bbb', marginBottom: 6 }} />
        <div style={{ fontSize: 12, color: isDark ? '#484f58' : '#aaa' }}>
          暂无任务
        </div>
      </div>
    )
  }

  return (
    <div style={{ padding: '8px 0' }}>
      <div
        style={{
          padding: '4px 12px 6px',
          fontSize: 11,
          fontWeight: 600,
          color: isDark ? '#8b949e' : '#656d76',
          textTransform: 'uppercase',
          letterSpacing: 0.5,
        }}
      >
        任务 ({taskList.filter((t) => t.status === 'verified' || t.passes).length}/{taskList.length})
      </div>
      {taskList.map((task) => {
        const config = STATUS_CONFIG[task.status] || STATUS_CONFIG.pending
        return (
          <Tooltip key={task.id} title={`${task.title} — ${config.label}`} placement="right">
            <div
              onClick={() => {
                setSelectedTaskId(task.id)
                setActiveTab('overview')
              }}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                padding: '5px 12px',
                cursor: 'pointer',
                fontSize: 12,
                color: isDark ? '#c9d1d9' : '#1f2328',
                background: selectedTaskId === task.id ? (isDark ? '#1c2333' : '#e8f0fe') : 'transparent',
                borderRight: selectedTaskId === task.id ? '2px solid #58a6ff' : '2px solid transparent',
                transition: 'background 0.15s',
              }}
              onMouseEnter={(e) => {
                if (selectedTaskId !== task.id) e.currentTarget.style.background = isDark ? '#161b22' : '#f0f0f0'
              }}
              onMouseLeave={(e) => {
                if (selectedTaskId !== task.id) e.currentTarget.style.background = 'transparent'
              }}
            >
              <span style={{ flexShrink: 0, fontSize: 12 }}>{config.icon}</span>
              <span
                style={{
                  flex: 1,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {task.title}
              </span>
              <span
                style={{
                  flexShrink: 0,
                  fontSize: 10,
                  color: isDark ? '#484f58' : '#bbb',
                  fontFamily: 'monospace',
                }}
              >
                {task.id}
              </span>
            </div>
          </Tooltip>
        )
      })}
    </div>
  )
}
