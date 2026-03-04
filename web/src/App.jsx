import { useEffect, Component } from 'react'
import { ConfigProvider, Layout, theme as antTheme, Button, Result } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import useStore from './stores/useStore'
import { darkTheme, lightTheme } from './styles/theme'
import AppHeader from './components/layout/AppHeader'
import StatusBar from './components/layout/StatusBar'
import WelcomePage from './components/WelcomePage'
import ProjectWorkspace from './components/workspace/ProjectWorkspace'
import BenchmarkPage from './components/benchmark/BenchmarkPage'
import SettingsDrawer from './components/modals/SettingsDrawer'
import CreateProjectModal from './components/modals/CreateProjectModal'

const { Content } = Layout

class ErrorBoundary extends Component {
  state = { hasError: false, error: null }
  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }
  componentDidCatch(error, info) {
    console.error('[ErrorBoundary]', error, info)
  }
  render() {
    if (this.state.hasError) {
      return (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', padding: 40 }}>
          <Result
            status="error"
            title="页面渲染出错"
            subTitle={this.state.error?.message || '未知错误'}
            extra={<Button type="primary" onClick={() => { this.setState({ hasError: false }); window.location.reload() }}>刷新页面</Button>}
          />
        </div>
      )
    }
    return this.props.children
  }
}

export default function App() {
  const currentTheme = useStore((s) => s.theme)
  const viewMode = useStore((s) => s.viewMode)
  const fetchProjects = useStore((s) => s.fetchProjects)
  const fetchSystemStatus = useStore((s) => s.fetchSystemStatus)
  const selectedProjectName = useStore((s) => s.selectedProjectName)
  const loadProjectHistory = useStore((s) => s.loadProjectHistory)

  const isRunning = useStore((s) => s.isRunning)

  useEffect(() => {
    const init = async () => {
      await fetchProjects()
      if (selectedProjectName && viewMode === 'workspace') {
        loadProjectHistory(selectedProjectName)
      }
    }
    init()
    fetchSystemStatus()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (isRunning) return
    const interval = setInterval(fetchSystemStatus, 60000)
    return () => clearInterval(interval)
  }, [fetchSystemStatus, isRunning])

  const themeConfig = currentTheme === 'dark' ? darkTheme : lightTheme
  const isDark = currentTheme === 'dark'

  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        ...themeConfig,
        algorithm: isDark ? antTheme.darkAlgorithm : antTheme.defaultAlgorithm,
      }}
    >
      <Layout style={{ height: '100vh' }}>
        <AppHeader />
        <Layout style={{ flex: 1, overflow: 'hidden' }}>
          <Content
            style={{
              height: '100%',
              background: isDark ? '#0d1117' : '#f6f8fa',
              overflow: viewMode === 'workspace' ? 'hidden' : 'auto',
              padding: viewMode === 'welcome' || viewMode === 'benchmark' ? 24 : 0,
            }}
          >
            <ErrorBoundary>
              {viewMode === 'workspace' ? <ProjectWorkspace />
                : viewMode === 'benchmark' ? <BenchmarkPage />
                  : <WelcomePage />}
            </ErrorBoundary>
          </Content>
        </Layout>
        <StatusBar />
      </Layout>
      <SettingsDrawer />
      <CreateProjectModal />
    </ConfigProvider>
  )
}
