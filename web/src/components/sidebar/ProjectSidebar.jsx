import useStore from '../../stores/useStore'
import TaskList from './TaskList'

export default function ProjectSidebar() {
  const theme = useStore((s) => s.theme)
  const isDark = theme === 'dark'

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          flex: 1,
          overflow: 'auto',
        }}
      >
        <TaskList />
      </div>
    </div>
  )
}
