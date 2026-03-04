import { Table, Tag, Button, Tooltip, Empty, message } from 'antd'
import {
  CheckCircleFilled,
  CloseCircleFilled,
  ClockCircleOutlined,
  LoadingOutlined,
  ReloadOutlined,
  ArrowLeftOutlined,
  FileTextOutlined,
  StopOutlined,
} from '@ant-design/icons'
import useStore from '../../stores/useStore'
import BugTracker from '../shared/BugTracker'

const STATUS_MAP = {
  verified: { icon: <CheckCircleFilled style={{ color: '#3fb950' }} />, tag: 'success', label: '已验证' },
  completed: { icon: <CheckCircleFilled style={{ color: '#58a6ff' }} />, tag: 'processing', label: '已完成' },
  in_progress: { icon: <LoadingOutlined style={{ color: '#d29922' }} />, tag: 'warning', label: '进行中' },
  failed: { icon: <CloseCircleFilled style={{ color: '#f85149' }} />, tag: 'error', label: '失败' },
  pending: { icon: <ClockCircleOutlined style={{ color: '#8b949e' }} />, tag: 'default', label: '待处理' },
}

function TaskDetailPanel({ task, isDark, onBack }) {
  const s = STATUS_MAP[task.status] || STATUS_MAP.pending
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
        <Button type="text" icon={<ArrowLeftOutlined />} size="small" onClick={onBack} />
        <span style={{ fontFamily: 'monospace', fontSize: 12, color: isDark ? '#8b949e' : '#656d76' }}>
          {task.id}
        </span>
        <Tag icon={s.icon} color={s.tag} style={{ margin: 0 }}>{s.label}</Tag>
        {task.passes && (
          <Tag color="success" style={{ margin: 0 }}>
            <CheckCircleFilled style={{ marginRight: 4 }} />Pass
          </Tag>
        )}
      </div>

      <h3 style={{ margin: '0 0 16px', fontSize: 16, fontWeight: 600, color: isDark ? '#f0f6fc' : '#1f2328' }}>
        {task.title}
      </h3>

      {task.description && (
        <div style={{
          padding: 12, marginBottom: 16, borderRadius: 6,
          background: isDark ? '#161b22' : '#f6f8fa',
          border: `1px solid ${isDark ? '#21262d' : '#e8e8e8'}`,
          fontSize: 13, color: isDark ? '#c9d1d9' : '#1f2328', lineHeight: '20px',
        }}>
          {task.description}
        </div>
      )}

      {task.feature_tag && (
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6, color: isDark ? '#8b949e' : '#656d76' }}>
            Feature 标签
          </div>
          <Tag>{task.feature_tag}</Tag>
        </div>
      )}

      {task.verification_steps && task.verification_steps.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 8, color: isDark ? '#8b949e' : '#656d76' }}>
            验证步骤
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {task.verification_steps.map((step, i) => (
              <div
                key={i}
                style={{
                  display: 'flex', alignItems: 'flex-start', gap: 8, padding: '8px 12px',
                  borderRadius: 6, background: isDark ? '#161b22' : '#f6f8fa',
                  border: `1px solid ${isDark ? '#21262d' : '#e8e8e8'}`,
                }}
              >
                <span style={{
                  flexShrink: 0, width: 20, height: 20, borderRadius: '50%', display: 'flex',
                  alignItems: 'center', justifyContent: 'center', fontSize: 11, fontWeight: 600,
                  background: task.passes ? '#238636' : (isDark ? '#21262d' : '#e8e8e8'),
                  color: task.passes ? '#fff' : (isDark ? '#8b949e' : '#656d76'),
                }}>
                  {task.passes ? '✓' : i + 1}
                </span>
                <span style={{ fontSize: 13, color: isDark ? '#c9d1d9' : '#1f2328', lineHeight: '20px' }}>
                  {step}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {task.files && task.files.length > 0 && (
        <div>
          <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 8, color: isDark ? '#8b949e' : '#656d76' }}>
            关联文件
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {task.files.map((f, i) => (
              <div
                key={i}
                style={{
                  display: 'flex', alignItems: 'center', gap: 6, padding: '4px 8px',
                  borderRadius: 4, fontSize: 12, fontFamily: 'monospace',
                  color: isDark ? '#58a6ff' : '#0969da',
                  background: isDark ? '#0d1117' : '#f6f8fa',
                }}
              >
                <FileTextOutlined style={{ fontSize: 12 }} />
                {f}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export default function VerifyTab() {
  const theme = useStore((s) => s.theme)
  const taskList = useStore((s) => s.executionTaskList)
  const bugsList = useStore((s) => s.executionBugsList)
  const isRunning = useStore((s) => s.isRunning)
  const selectedProjectName = useStore((s) => s.selectedProjectName)
  const selectedTaskId = useStore((s) => s.selectedTaskId)
  const setSelectedTaskId = useStore((s) => s.setSelectedTaskId)
  const resumeProject = useStore((s) => s.resumeProject)
  const isDark = theme === 'dark'

  const handleResume = async () => {
    try {
      await resumeProject(selectedProjectName)
    } catch (e) {
      message.error(e.message || '恢复执行失败')
    }
  }

  const selectedTask = selectedTaskId ? taskList.find((t) => t.id === selectedTaskId) : null

  if (selectedTask) {
    return <TaskDetailPanel task={selectedTask} isDark={isDark} onBack={() => setSelectedTaskId(null)} />
  }

  const hasUnverified = taskList.some((t) => !t.passes && t.status !== 'pending')

  const columns = [
    {
      title: 'ID',
      dataIndex: 'id',
      key: 'id',
      width: 80,
      render: (id) => <span style={{ fontFamily: 'monospace', fontSize: 11 }}>{id}</span>,
    },
    {
      title: '任务',
      dataIndex: 'title',
      key: 'title',
      ellipsis: true,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status) => {
        const s = STATUS_MAP[status] || STATUS_MAP.pending
        return <Tag icon={s.icon} color={s.tag} style={{ margin: 0, fontSize: 11 }}>{s.label}</Tag>
      },
    },
    {
      title: 'Passes',
      key: 'passes',
      width: 70,
      align: 'center',
      render: (_, record) => {
        if (record.passes) return <CheckCircleFilled style={{ color: '#3fb950', fontSize: 16 }} />
        if (record.status === 'failed') return <CloseCircleFilled style={{ color: '#f85149', fontSize: 16 }} />
        return <span style={{ color: isDark ? '#484f58' : '#ccc' }}>-</span>
      },
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <span style={{ fontWeight: 600, fontSize: 14, color: isDark ? '#f0f6fc' : '#1f2328' }}>
          任务验收
        </span>
        {hasUnverified && (
          <Tooltip title="对未通过的任务重新运行测试">
            <Button
              size="small"
              icon={<ReloadOutlined />}
              disabled={isRunning}
              onClick={handleResume}
            >
              继续执行
            </Button>
          </Tooltip>
        )}
      </div>

      {taskList.length > 0 ? (
        <Table
          dataSource={taskList}
          columns={columns}
          rowKey="id"
          size="small"
          pagination={false}
          onRow={(record) => ({
            onClick: () => setSelectedTaskId(record.id),
            style: { cursor: 'pointer' },
          })}
          style={{ marginBottom: 24 }}
        />
      ) : (
        <Empty description="暂无任务数据" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ marginBottom: 24 }} />
      )}

      <BugTracker bugs={bugsList} isDark={isDark} />
    </div>
  )
}
