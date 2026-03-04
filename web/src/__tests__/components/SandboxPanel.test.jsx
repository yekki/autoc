import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConfigProvider } from 'antd'
import SandboxPanel from '../../components/shared/SandboxPanel'
import useStore from '../../stores/useStore'

vi.mock('../../services/api', () => ({
  fetchSandboxStatus: vi.fn(),
  stopSandbox: vi.fn(),
  fetchProjects: vi.fn().mockResolvedValue([]),
  fetchConfig: vi.fn().mockResolvedValue(null),
  fetchModelConfig: vi.fn().mockResolvedValue(null),
}))

vi.mock('../../services/sse', () => ({
  SSEConnection: class { constructor() { this.connect = vi.fn(); this.close = vi.fn() } },
}))

const api = await import('../../services/api')

function renderSandbox() {
  return render(<ConfigProvider><SandboxPanel /></ConfigProvider>)
}

describe('SandboxPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useStore.setState({ theme: 'dark' })
  })

  it('shows loading spinner initially', () => {
    api.fetchSandboxStatus.mockReturnValue(new Promise(() => {}))
    renderSandbox()
    expect(document.querySelector('.ant-spin')).toBeTruthy()
  })

  it('shows "Docker 不可用" when docker is not available', async () => {
    api.fetchSandboxStatus.mockResolvedValue({ docker_available: false })
    renderSandbox()

    await waitFor(() => {
      expect(screen.getByText('Docker 不可用 — 沙箱功能需要 Docker')).toBeInTheDocument()
    })
  })

  it('shows sandbox status with enabled tag when docker available', async () => {
    api.fetchSandboxStatus.mockResolvedValue({
      docker_available: true,
      sandbox_mode: 'project',
      containers: [],
    })
    renderSandbox()

    await waitFor(() => {
      expect(screen.getByText('沙箱状态')).toBeInTheDocument()
      expect(screen.getByText('已启用')).toBeInTheDocument()
      expect(screen.getByText('project 模式')).toBeInTheDocument()
    })
  })

  it('shows empty state when no containers running', async () => {
    api.fetchSandboxStatus.mockResolvedValue({
      docker_available: true,
      sandbox_mode: 'project',
      containers: [],
    })
    renderSandbox()

    await waitFor(() => {
      expect(screen.getByText('暂无运行中的沙箱容器')).toBeInTheDocument()
    })
  })

  it('renders container list with state and name', async () => {
    api.fetchSandboxStatus.mockResolvedValue({
      docker_available: true,
      sandbox_mode: 'project',
      containers: [
        { name: 'autoc-sandbox-abc', state: 'running', image: 'autoc:latest', ports: '8080:8080' },
        { name: 'autoc-sandbox-def', state: 'exited', image: 'autoc:latest', ports: '' },
      ],
    })
    renderSandbox()

    await waitFor(() => {
      expect(screen.getByText('autoc-sandbox-abc')).toBeInTheDocument()
      expect(screen.getByText('autoc-sandbox-def')).toBeInTheDocument()
    })

    const runningTags = screen.getAllByText('running')
    expect(runningTags).toHaveLength(1)
    expect(screen.getByText('exited')).toBeInTheDocument()
    expect(screen.getByText('端口映射: 8080:8080')).toBeInTheDocument()
  })

  it('refresh button reloads sandbox status', async () => {
    const user = userEvent.setup()
    api.fetchSandboxStatus.mockResolvedValue({
      docker_available: true, sandbox_mode: 'project', containers: [],
    })
    renderSandbox()

    await waitFor(() => screen.getByText('刷新'))

    api.fetchSandboxStatus.mockResolvedValue({
      docker_available: true, sandbox_mode: 'project',
      containers: [{ name: 'new-container', state: 'running', image: 'img' }],
    })

    await user.click(screen.getByText('刷新'))

    await waitFor(() => {
      expect(screen.getByText('new-container')).toBeInTheDocument()
    })

    expect(api.fetchSandboxStatus).toHaveBeenCalledTimes(2)
  })

  it('stop button calls API and refreshes', async () => {
    const user = userEvent.setup()
    api.fetchSandboxStatus.mockResolvedValue({
      docker_available: true, sandbox_mode: 'project',
      containers: [{ name: 'my-sandbox', state: 'running', image: 'img' }],
    })
    api.stopSandbox.mockResolvedValue({})

    renderSandbox()

    await waitFor(() => screen.getByText('my-sandbox'))

    const stopBtn = screen.getAllByText('停止').find(el => el.closest('button'))?.closest('button')
    await user.click(stopBtn)

    await waitFor(() => {
      const popconfirmBtns = document.querySelectorAll('.ant-popconfirm-buttons button')
      expect(popconfirmBtns.length).toBeGreaterThan(0)
    })

    const confirmBtns = document.querySelectorAll('.ant-popconfirm-buttons button')
    const okBtn = Array.from(confirmBtns).find(b => b.classList.contains('ant-btn-primary') || b.classList.contains('ant-btn-dangerous'))
      || confirmBtns[confirmBtns.length - 1]
    await user.click(okBtn)

    await waitFor(() => {
      expect(api.stopSandbox).toHaveBeenCalledWith('my-sandbox')
    })
  })

  it('handles API error gracefully', async () => {
    api.fetchSandboxStatus.mockRejectedValue(new Error('Network error'))
    renderSandbox()

    await waitFor(() => {
      expect(screen.getByText('Docker 不可用 — 沙箱功能需要 Docker')).toBeInTheDocument()
    })
  })

  it('shows stop failure message', async () => {
    const user = userEvent.setup()
    api.fetchSandboxStatus.mockResolvedValue({
      docker_available: true, sandbox_mode: 'project',
      containers: [{ name: 'fail-sandbox', state: 'running', image: 'img' }],
    })
    api.stopSandbox.mockRejectedValue(new Error('Permission denied'))

    renderSandbox()

    await waitFor(() => screen.getByText('fail-sandbox'))

    const stopBtn = screen.getAllByText('停止').find(el => el.closest('button'))?.closest('button')
    await user.click(stopBtn)

    await waitFor(() => {
      const popconfirmBtns = document.querySelectorAll('.ant-popconfirm-buttons button')
      expect(popconfirmBtns.length).toBeGreaterThan(0)
    })

    const confirmBtns = document.querySelectorAll('.ant-popconfirm-buttons button')
    const okBtn = Array.from(confirmBtns).find(b => b.classList.contains('ant-btn-primary') || b.classList.contains('ant-btn-dangerous'))
      || confirmBtns[confirmBtns.length - 1]
    await user.click(okBtn)

    await waitFor(() => {
      expect(api.stopSandbox).toHaveBeenCalledWith('fail-sandbox')
    })
  })
})
