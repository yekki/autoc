import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConfigProvider } from 'antd'
import WelcomePage from '../../components/WelcomePage'
import useStore from '../../stores/useStore'

vi.mock('../../services/api', () => ({
  fetchProjects: vi.fn().mockResolvedValue([]),
  fetchConfig: vi.fn().mockResolvedValue(null),
  fetchModelConfig: vi.fn().mockResolvedValue(null),
}))

vi.mock('../../services/sse', () => ({
  SSEConnection: vi.fn().mockImplementation(() => ({
    connect: vi.fn(), close: vi.fn(),
  })),
}))

function renderWithAntd(ui) {
  return render(<ConfigProvider>{ui}</ConfigProvider>)
}

describe('WelcomePage', () => {
  beforeEach(() => {
    useStore.setState({
      projects: [],
      theme: 'dark',
      selectedProjectName: null,
      viewMode: 'welcome',
    })
  })

  it('shows empty state with welcome message and quick start form when no projects', () => {
    renderWithAntd(<WelcomePage />)
    expect(screen.getByText('欢迎使用 AutoC')).toBeInTheDocument()
    // S-001: 首屏直接展示快速启动面板（一键启动按钮）
    expect(screen.getByText('一键启动')).toBeInTheDocument()
    // 仍有兜底创建空项目入口
    expect(screen.getByText('或者先创建空项目，稍后填写需求')).toBeInTheDocument()
  })

  it('fallback empty project link opens modal', async () => {
    const user = userEvent.setup()
    renderWithAntd(<WelcomePage />)

    const fallbackBtn = screen.getByText('或者先创建空项目，稍后填写需求')
    await user.click(fallbackBtn)

    expect(useStore.getState().createProjectOpen).toBe(true)
  })

  it('renders project cards when projects exist', () => {
    useStore.setState({
      projects: [
        { name: 'My App', folder: 'my-app', description: 'A todo app', tech_stack: ['React'], status: 'completed', total_tasks: 5, verified_tasks: 5 },
        { name: 'Backend', folder: 'backend', description: 'API service', tech_stack: ['Node.js'], status: 'idle', total_tasks: 0, verified_tasks: 0 },
      ],
    })

    renderWithAntd(<WelcomePage />)
    expect(screen.getByText('My App')).toBeInTheDocument()
    expect(screen.getByText('Backend')).toBeInTheDocument()
    expect(screen.getByText('共 2 个项目')).toBeInTheDocument()
  })

  it('filters projects by search query', async () => {
    useStore.setState({
      projects: [
        { name: 'React Todo', folder: 'react-todo', description: '', tech_stack: ['React'], status: 'idle' },
        { name: 'Vue Shop', folder: 'vue-shop', description: '', tech_stack: ['Vue'], status: 'idle' },
      ],
    })

    const user = userEvent.setup()
    renderWithAntd(<WelcomePage />)

    const searchInput = screen.getByPlaceholderText('搜索项目名称、描述或技术栈...')
    await user.type(searchInput, 'React')

    expect(screen.getByText('React Todo')).toBeInTheDocument()
    expect(screen.queryByText('Vue Shop')).not.toBeInTheDocument()
  })

  it('filters by tech_stack keyword', async () => {
    useStore.setState({
      projects: [
        { name: 'A', folder: 'a', description: '', tech_stack: ['Python', 'FastAPI'], status: 'idle' },
        { name: 'B', folder: 'b', description: '', tech_stack: ['Java'], status: 'idle' },
      ],
    })

    const user = userEvent.setup()
    renderWithAntd(<WelcomePage />)

    await user.type(screen.getByPlaceholderText('搜索项目名称、描述或技术栈...'), 'Python')
    expect(screen.getByText('A')).toBeInTheDocument()
    expect(screen.queryByText('B')).not.toBeInTheDocument()
  })

  it('filters by description', async () => {
    useStore.setState({
      projects: [
        { name: 'X', folder: 'x', description: '电商系统', tech_stack: [], status: 'idle' },
        { name: 'Y', folder: 'y', description: '博客平台', tech_stack: [], status: 'idle' },
      ],
    })

    const user = userEvent.setup()
    renderWithAntd(<WelcomePage />)

    await user.type(screen.getByPlaceholderText('搜索项目名称、描述或技术栈...'), '电商')
    expect(screen.getByText('X')).toBeInTheDocument()
    expect(screen.queryByText('Y')).not.toBeInTheDocument()
  })

  it('shows "没有匹配的项目" when search has no results', async () => {
    useStore.setState({
      projects: [{ name: 'Foo', folder: 'foo', description: '', tech_stack: [], status: 'idle' }],
    })

    const user = userEvent.setup()
    renderWithAntd(<WelcomePage />)

    await user.type(screen.getByPlaceholderText('搜索项目名称、描述或技术栈...'), 'zzzzz')
    expect(screen.getByText('没有匹配的项目')).toBeInTheDocument()
  })

  it('enters batch select mode and selects projects', async () => {
    useStore.setState({
      projects: [
        { name: 'A', folder: 'a', description: '', tech_stack: [], status: 'idle' },
        { name: 'B', folder: 'b', description: '', tech_stack: [], status: 'idle' },
      ],
    })

    const user = userEvent.setup()
    renderWithAntd(<WelcomePage />)

    await user.click(screen.getByText('批量删除'))

    const checkboxes = screen.getAllByRole('checkbox')
    expect(checkboxes).toHaveLength(2)

    expect(screen.getByText('取消')).toBeInTheDocument()
  })

  it('displays project status tags correctly', () => {
    useStore.setState({
      projects: [
        { name: 'Done', folder: 'done', status: 'completed', tech_stack: [] },
        { name: 'Running', folder: 'running', status: 'developing', tech_stack: [] },
      ],
    })

    renderWithAntd(<WelcomePage />)
    expect(screen.getByText('已完成')).toBeInTheDocument()
    expect(screen.getByText('开发中')).toBeInTheDocument()
  })

  it('displays task progress on cards', () => {
    useStore.setState({
      projects: [
        { name: 'P', folder: 'p', status: 'completed', tech_stack: [], total_tasks: 10, verified_tasks: 8 },
      ],
    })

    renderWithAntd(<WelcomePage />)
    expect(screen.getByText('8/10 任务')).toBeInTheDocument()
  })
})
