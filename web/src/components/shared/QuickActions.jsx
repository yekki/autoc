import { Button, Space, Dropdown, Tooltip, Badge } from 'antd'
import {
  PlusOutlined, BugOutlined, PlayCircleOutlined,
  ThunderboltOutlined, HistoryOutlined,
  MoreOutlined,
} from '@ant-design/icons'
import useStore from '../../stores/useStore'

export default function QuickActions({ compact = false }) {
  const isRunning = useStore(s => s.isRunning)
  const executionBugsList = useStore(s => s.executionBugsList)
  const executionTaskList = useStore(s => s.executionTaskList)
  const selectedProjectName = useStore(s => s.selectedProjectName)
  const resumeProject = useStore(s => s.resumeProject)
  const quickFixBugs = useStore(s => s.quickFixBugs)
  const redefineProject = useStore(s => s.redefineProject)
  const addFeature = useStore(s => s.addFeature)

  const openBugs = executionBugsList?.filter(b => b.status === 'open') || []
  const failedTasks = executionTaskList?.filter(t => !t.passes) || []
  const hasTasks = executionTaskList?.length > 0

  const handleResume = () => {
    if (selectedProjectName) resumeProject(selectedProjectName)
  }

  const handleQuickFix = () => {
    if (selectedProjectName && openBugs.length > 0) {
      quickFixBugs(selectedProjectName, { bugs: openBugs })
    }
  }

  const handleRevise = () => {
    const newReq = prompt('输入新的需求描述:')
    if (newReq && selectedProjectName) {
      redefineProject(selectedProjectName, newReq)
    }
  }

  const moreItems = [
    {
      key: 'add-feature',
      icon: <PlusOutlined />,
      label: '追加功能',
      onClick: () => {
        const feature = prompt('描述要追加的功能:')
        if (feature && selectedProjectName) {
          addFeature(selectedProjectName, feature)
        }
      },
    },
    {
      key: 'revise',
      icon: <HistoryOutlined />,
      label: '调整需求',
      onClick: handleRevise,
    },
  ]

  if (compact) {
    return (
      <Dropdown menu={{ items: [
        { key: 'resume', icon: <PlayCircleOutlined />, label: `继续执行${failedTasks.length ? ` (${failedTasks.length} 待处理)` : ''}`, onClick: handleResume, disabled: isRunning || !hasTasks },
        { key: 'fix', icon: <BugOutlined />, label: `修复 Bug${openBugs.length ? ` (${openBugs.length})` : ''}`, onClick: handleQuickFix, disabled: isRunning || !openBugs.length },
        { type: 'divider' },
        ...moreItems.map(i => ({ ...i, disabled: isRunning })),
      ]}} trigger={['click']}>
        <Button type="text" icon={<ThunderboltOutlined />} size="small">
          快捷操作
        </Button>
      </Dropdown>
    )
  }

  return (
    <div style={{ padding: '8px 0' }}>
      <Space wrap>
        <Tooltip title="从断点恢复：跳过 PM，已通过的任务自动跳过">
          <Badge count={failedTasks.length} size="small" offset={[-4, 0]}>
            <Button
              icon={<PlayCircleOutlined />}
              onClick={handleResume}
              disabled={isRunning || !hasTasks}
              type="primary"
              size="small"
            >
              继续执行
            </Button>
          </Badge>
        </Tooltip>

        <Tooltip title="快速修复所有未解决的 Bug">
          <Badge count={openBugs.length} size="small" offset={[-4, 0]}>
            <Button
              icon={<BugOutlined />}
              onClick={handleQuickFix}
              disabled={isRunning || !openBugs.length}
              danger={openBugs.length > 0}
              size="small"
            >
              修复 Bug
            </Button>
          </Badge>
        </Tooltip>

        <Tooltip title="追加新功能到当前项目">
          <Button
            icon={<PlusOutlined />}
            onClick={() => {
              const feature = prompt('描述要追加的功能:')
              if (feature && selectedProjectName) {
                addFeature(selectedProjectName, feature)
              }
            }}
            disabled={isRunning}
            size="small"
          >
            追加功能
          </Button>
        </Tooltip>

        <Dropdown menu={{ items: moreItems.map(i => ({ ...i, disabled: isRunning })) }} trigger={['click']}>
          <Button type="text" icon={<MoreOutlined />} size="small" disabled={isRunning} />
        </Dropdown>
      </Space>
    </div>
  )
}
