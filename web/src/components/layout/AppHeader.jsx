import { Button, Space, Tooltip, Dropdown, Modal } from 'antd'
import {
  SettingOutlined,
  EditOutlined,
  DeleteOutlined,
  MoreOutlined,
  DashboardOutlined,
} from '@ant-design/icons'
import useStore from '../../stores/useStore'

export default function AppHeader() {
  const theme = useStore((s) => s.theme)
  const setTheme = useStore((s) => s.setTheme)
  const setSettingsOpen = useStore((s) => s.setSettingsOpen)
  const openEditProject = useStore((s) => s.openEditProject)
  const projects = useStore((s) => s.projects)
  const selectedProjectName = useStore((s) => s.selectedProjectName)
  const deleteProject = useStore((s) => s.deleteProject)
  const backToAllProjects = useStore((s) => s.backToAllProjects)
  const navigateToBenchmark = useStore((s) => s.navigateToBenchmark)
  const viewMode = useStore((s) => s.viewMode)
  const isDark = theme === 'dark'

  const selectedProject = projects.find((p) => p.folder === selectedProjectName) || null

  const confirmDeleteProject = (folder) => {
    const proj = projects.find((p) => p.folder === folder)
    const displayName = proj?.name || folder
    Modal.confirm({
      title: '删除项目',
      content: `确定删除项目「${displayName}」？此操作不可恢复。`,
      okText: '删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: () => deleteProject(folder),
    })
  }

  const moreMenuItems = [
    {
      key: 'edit',
      icon: <EditOutlined />,
      label: '编辑项目',
      disabled: !selectedProject,
      onClick: () => selectedProject && openEditProject({
        name: selectedProject.name,
        folder: selectedProject.folder,
        description: selectedProject.description,
        tech_stack: selectedProject.tech_stack || [],
      }),
    },
    {
      key: 'delete',
      icon: <DeleteOutlined />,
      label: '删除项目',
      danger: true,
      disabled: !selectedProject,
      onClick: () => selectedProjectName && confirmDeleteProject(selectedProjectName),
    },
    { type: 'divider' },
    {
      key: 'theme',
      label: isDark ? '切换亮色主题' : '切换暗色主题',
      onClick: () => setTheme(isDark ? 'light' : 'dark'),
    },
  ]

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 16px',
        height: 48,
        background: isDark ? '#161b22' : '#ffffff',
        borderBottom: `1px solid ${isDark ? '#30363d' : '#d0d7de'}`,
        position: 'sticky',
        top: 0,
        zIndex: 100,
        flexShrink: 0,
      }}
    >
      {/* 左侧：Logo + 项目名 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 0 }}>
        <button
          aria-label="返回所有项目"
          style={{
            display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer',
            background: 'none', border: 'none', padding: 0,
          }}
          onClick={backToAllProjects}
        >
          <span
            style={{
              fontSize: 18,
              fontWeight: 800,
              letterSpacing: -0.5,
              color: isDark ? '#58a6ff' : '#0969da',
              userSelect: 'none',
            }}
          >
            AutoC
          </span>
        </button>
        {selectedProject && viewMode === 'workspace' && (
          <>
            <span style={{
              margin: '0 8px',
              color: isDark ? '#484f58' : '#b1bac4',
              fontSize: 18,
              fontWeight: 300,
              userSelect: 'none',
            }}>/</span>
            <span style={{
              fontSize: 15,
              fontWeight: 600,
              color: isDark ? '#e6edf3' : '#1f2328',
              userSelect: 'none',
              maxWidth: 260,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}>
              {selectedProject.name}
            </span>
          </>
        )}
      </div>

      {/* 右侧：操作按钮 */}
      <Space size={4}>
        <Tooltip title="Benchmark">
          <Button
            type="text"
            size="small"
            icon={<DashboardOutlined />}
            onClick={navigateToBenchmark}
            style={{
              color: viewMode === 'benchmark' ? '#58a6ff' : (isDark ? '#8b949e' : '#656d76'),
            }}
          />
        </Tooltip>

        <Tooltip title="设置">
          <Button
            type="text"
            size="small"
            icon={<SettingOutlined />}
            onClick={() => setSettingsOpen(true)}
            style={{ color: isDark ? '#8b949e' : '#656d76' }}
          />
        </Tooltip>

        <Dropdown menu={{ items: moreMenuItems }} trigger={['click']} placement="bottomRight">
          <Button
            type="text"
            size="small"
            icon={<MoreOutlined />}
            style={{ color: isDark ? '#8b949e' : '#656d76' }}
          />
        </Dropdown>
      </Space>
    </div>
  )
}
