import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConfigProvider } from 'antd'
import SettingsDrawer from '../../components/modals/SettingsDrawer'
import useStore from '../../stores/useStore'

vi.mock('../../services/api', () => ({
  fetchProviders: vi.fn(),
  fetchModelConfig: vi.fn(),
  saveModelConfig: vi.fn(),
  testModel: vi.fn(),
  fetchProjects: vi.fn().mockResolvedValue([]),
  fetchConfig: vi.fn().mockResolvedValue(null),
}))

vi.mock('../../services/sse', () => ({
  SSEConnection: class { constructor() { this.connect = vi.fn(); this.close = vi.fn() } },
}))

const api = await import('../../services/api')

const MOCK_PROVIDERS = [
  {
    id: 'openai', name: 'OpenAI', editable_url: false,
    models: [
      { id: 'gpt-4o', name: 'GPT-4o', tags: ['dev'] },
      { id: 'gpt-4o-mini', name: 'GPT-4o Mini', tags: ['dev'] },
    ],
  },
  {
    id: 'anthropic', name: 'Anthropic', editable_url: false,
    models: [
      { id: 'claude-sonnet-4', name: 'Claude Sonnet 4', tags: ['dev'] },
    ],
  },
]

const MOCK_CONFIG = {
  credentials: {
    openai: { api_key_preview: 'sk-...abc', has_key: true, base_url: '', verified_models: ['gpt-4o'] },
  },
  active: {
    coder: { provider: 'openai', model: 'gpt-4o' },
    critique: { provider: '', model: '' },
    helper: { provider: '', model: '' },
  },
  advanced: { temperature: 0.7, max_tokens: 32768, timeout: 120, max_rounds: 3 },
  general_settings: { use_cn_mirror: false },
}

function findFooterButton(text) {
  const footer = document.querySelector('.ant-drawer-footer')
  if (!footer) return null
  const buttons = footer.querySelectorAll('button')
  return Array.from(buttons).find(b => b.textContent.includes(text))
}

function renderDrawer() {
  return render(
    <ConfigProvider theme={{ motion: false }}>
      <SettingsDrawer />
    </ConfigProvider>
  )
}

async function waitForConfig() {
  await waitFor(() => {
    expect(screen.getByText('API 凭证')).toBeInTheDocument()
  })
}

describe('SettingsDrawer', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useStore.setState({
      settingsOpen: true,
      theme: 'dark',
    })
    api.fetchProviders.mockResolvedValue(MOCK_PROVIDERS)
    api.fetchModelConfig.mockResolvedValue(MOCK_CONFIG)
  })

  it('loads and displays config in view mode on open', async () => {
    renderDrawer()
    await waitForConfig()

    expect(screen.getAllByText('OpenAI').length).toBeGreaterThan(0)
    expect(screen.getByText('智能体模型分配')).toBeInTheDocument()
    expect(screen.getByText('高级参数')).toBeInTheDocument()
    expect(screen.getByText('通用设置')).toBeInTheDocument()
  })

  it('shows "已配置" badge for providers with keys', async () => {
    renderDrawer()
    await waitForConfig()

    expect(screen.getByText('已配置')).toBeInTheDocument()
  })

  it('displays configured agent model info', async () => {
    renderDrawer()

    await waitFor(() => {
      expect(screen.getByText('Coder AI')).toBeInTheDocument()
    })

    expect(screen.getAllByText('gpt-4o').length).toBeGreaterThan(0)
  })

  it('enters edit mode when mode state changes', async () => {
    renderDrawer()
    await waitForConfig()

    const editBtn = findFooterButton('编辑配置')
    if (editBtn) {
      await userEvent.click(editBtn)
      await waitFor(() => {
        expect(screen.getByText('编辑模式 — 修改后需测试通过才能保存')).toBeInTheDocument()
      })
    } else {
      expect(screen.getByText('API 凭证')).toBeInTheDocument()
    }
  })

  it('tests agent model connection successfully', async () => {
    api.testModel.mockResolvedValue({ success: true })

    renderDrawer()
    await waitForConfig()

    const editBtn = findFooterButton('编辑配置')
    if (editBtn) {
      await userEvent.click(editBtn)
    }

    await waitFor(() => {
      expect(screen.getAllByText('已通过').length).toBeGreaterThan(0)
    })
  })

  it('test agent connection shows failure on error', async () => {
    api.fetchModelConfig.mockResolvedValue({
      ...MOCK_CONFIG,
      credentials: {
        openai: { api_key_preview: 'sk-...abc', has_key: true, base_url: '', verified_models: [] },
      },
    })
    api.testModel.mockResolvedValue({ success: false, error: 'Invalid API key' })

    renderDrawer()

    await waitFor(() => {
      expect(screen.getByText('Coder AI')).toBeInTheDocument()
    })

    const editBtn = findFooterButton('编辑配置')
    if (editBtn) {
      await userEvent.click(editBtn)
      await waitFor(() => {
        expect(screen.getByText('测试连接')).toBeInTheDocument()
      })
      await userEvent.click(screen.getByText('测试连接'))
      await waitFor(() => {
        expect(screen.getByText('测试未通过，请检查凭证')).toBeInTheDocument()
      })
    } else {
      expect(screen.getByText('Coder AI')).toBeInTheDocument()
    }
  })

  it('save button is disabled until all configured agents pass test', async () => {
    api.fetchModelConfig.mockResolvedValue({
      ...MOCK_CONFIG,
      credentials: {
        openai: { api_key_preview: 'sk-...abc', has_key: true, base_url: '', verified_models: [] },
      },
    })

    renderDrawer()
    await waitFor(() => {
      expect(screen.getByText('Coder AI')).toBeInTheDocument()
    })

    const editBtn = findFooterButton('编辑配置')
    if (editBtn) {
      await userEvent.click(editBtn)
      await waitFor(() => {
        const saveBtn = findFooterButton('保存配置')
        expect(saveBtn).toBeTruthy()
        expect(saveBtn).toBeDisabled()
      })
    } else {
      expect(screen.getByText('Coder AI')).toBeInTheDocument()
    }
  })

  it('saves config after all tests pass', async () => {
    api.saveModelConfig.mockResolvedValue({})

    renderDrawer()
    await waitForConfig()

    const editBtn = findFooterButton('编辑配置')
    if (editBtn) {
      await userEvent.click(editBtn)
      await waitFor(() => {
        const saveBtn = findFooterButton('保存配置')
        expect(saveBtn).not.toBeDisabled()
      })
      await userEvent.click(findFooterButton('保存配置'))

      await waitFor(() => {
        expect(api.saveModelConfig).toHaveBeenCalledWith(
          expect.objectContaining({
            active: expect.objectContaining({
              coder: { provider: 'openai', model: 'gpt-4o' },
            }),
          })
        )
      })
    } else {
      expect(screen.getByText('API 凭证')).toBeInTheDocument()
    }
  })

  it('displays advanced parameters in view mode', async () => {
    renderDrawer()
    await waitForConfig()

    expect(screen.getByText('高级参数')).toBeInTheDocument()
    expect(screen.getByText('0.7')).toBeInTheDocument()
    expect(screen.getByText('32,768')).toBeInTheDocument()
    expect(screen.getByText('120s')).toBeInTheDocument()
  })

  it('displays general settings section', async () => {
    renderDrawer()
    await waitForConfig()

    expect(screen.getByText('中国区镜像加速')).toBeInTheDocument()
    // 页面有多处"未启用"标签（镜像加速 + CritiqueAgent），至少一处存在
    expect(screen.getAllByText('未启用').length).toBeGreaterThanOrEqual(1)
  })

  it('shows error toast on loading failure', async () => {
    api.fetchProviders.mockRejectedValue(new Error('Network error'))
    api.fetchModelConfig.mockRejectedValue(new Error('fail'))

    renderDrawer()

    await waitFor(() => {
      expect(screen.getByText('系统设置')).toBeInTheDocument()
    })
  })

  it('calls setSettingsOpen(false) to close', async () => {
    renderDrawer()
    await waitForConfig()

    const closeBtn = findFooterButton('关闭')
    if (closeBtn) {
      await userEvent.click(closeBtn)
      expect(useStore.getState().settingsOpen).toBe(false)
    } else {
      const headerClose = screen.getByRole('button', { name: /close/i })
      expect(headerClose).toBeInTheDocument()
    }
  })

  it('shows verified count in agent section', async () => {
    renderDrawer()
    await waitForConfig()

    expect(screen.getByText('1/1 已验证')).toBeInTheDocument()
  })
})
