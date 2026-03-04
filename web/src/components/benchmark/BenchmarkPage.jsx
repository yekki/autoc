import { useEffect } from 'react'
import { Button, Tabs } from 'antd'
import {
  ArrowLeftOutlined, PlayCircleOutlined,
  DashboardOutlined, HistoryOutlined, SwapOutlined,
  AppstoreOutlined, LoadingOutlined,
} from '@ant-design/icons'
import useStore from '../../stores/useStore'
import DashboardView from './DashboardView'
import HistoryView from './HistoryView'
import DetailView from './DetailView'
import CompareView from './CompareView'
import CasesView from './CasesView'
import RunDrawer from './RunDrawer'

const TAB_ITEMS = [
  { key: 'dashboard', label: '仪表盘', icon: <DashboardOutlined /> },
  { key: 'history', label: '运行历史', icon: <HistoryOutlined /> },
  { key: 'compare', label: '对比分析', icon: <SwapOutlined /> },
  { key: 'cases', label: '用例管理', icon: <AppstoreOutlined /> },
]

export default function BenchmarkPage() {
  const theme = useStore((s) => s.theme)
  const activeTab = useStore((s) => s.benchmarkActiveTab)
  const setActiveTab = useStore((s) => s.setBenchmarkActiveTab)
  const backFromBenchmark = useStore((s) => s.backFromBenchmark)
  const detail = useStore((s) => s.benchmarkDetail)
  const compare = useStore((s) => s.benchmarkCompare)
  const isDark = theme === 'dark'

  const fetchRunning = useStore((s) => s.fetchRunningBenchmarks)
  const isRunning = useStore((s) => s.benchmarkRunning)
  const drawerOpen = useStore((s) => s.benchmarkDrawerOpen)
  const setDrawerOpen = useStore((s) => s.setBenchmarkDrawerOpen)

  // 轮询触发 slice 自动感知：发现未跟踪的 running benchmark 会自动订阅 SSE
  useEffect(() => {
    fetchRunning()
    const timer = setInterval(fetchRunning, 3000)
    return () => clearInterval(timer)
  }, []) // eslint-disable-line

  const showDetail = activeTab === 'detail' && detail
  const showCompare = activeTab === 'compare' && compare

  const renderContent = () => {
    if (showDetail) return <DetailView />
    if (showCompare) return <CompareView />
    switch (activeTab) {
      case 'dashboard': return <DashboardView />
      case 'history': return <HistoryView />
      case 'compare': return <CompareView />
      case 'cases': return <CasesView />
      default: return <DashboardView />
    }
  }

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', padding: '20px 24px' }}>
      {/* 顶栏 */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        marginBottom: 20,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <Button
            type="text" size="small"
            icon={<ArrowLeftOutlined />}
            onClick={() => {
              if (showDetail) { setActiveTab('history'); return }
              backFromBenchmark()
            }}
            style={{ color: isDark ? '#8b949e' : '#656d76' }}
          />
          <div>
            <h2 style={{
              margin: 0, fontSize: 20, fontWeight: 700,
              color: isDark ? '#f0f6fc' : '#1f2328',
              display: 'flex', alignItems: 'center', gap: 8,
            }}>
              Benchmark
              {isRunning && (
                <span style={{ fontSize: 13, fontWeight: 400, color: isDark ? '#58a6ff' : '#0969da', display: 'flex', alignItems: 'center', gap: 4 }}>
                  <LoadingOutlined spin style={{ fontSize: 12 }} />
                  运行中
                </span>
              )}
              {showDetail && (
                <span style={{ fontSize: 14, fontWeight: 400, color: isDark ? '#8b949e' : '#656d76' }}>
                  / {detail.tag || '详情'}
                </span>
              )}
            </h2>
          </div>
        </div>
        <Button
          type="primary"
          icon={isRunning ? <LoadingOutlined /> : <PlayCircleOutlined />}
          onClick={() => setDrawerOpen(true)}
          disabled={isRunning}
        >
          {isRunning ? '运行中...' : '发起测试'}
        </Button>
      </div>

      {/* Tabs */}
      {!showDetail && (
        <Tabs
          activeKey={activeTab}
          onChange={(key) => setActiveTab(key)}
          items={TAB_ITEMS.map((t) => ({
            key: t.key,
            label: <span>{t.icon} {t.label}</span>,
          }))}
          size="small"
          style={{ marginBottom: 16 }}
        />
      )}

      {/* 内容区 */}
      {renderContent()}

      {/* 运行抽屉 */}
      <RunDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} />
    </div>
  )
}
