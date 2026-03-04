import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ConfigProvider } from 'antd'
import CostTab from '../../components/workspace/CostTab'
import useStore from '../../stores/useStore'
import { EMPTY_STATS } from '../../stores/helpers/constants'

vi.mock('../../services/api', () => ({
  fetchProjects: vi.fn().mockResolvedValue([]),
  fetchConfig: vi.fn().mockResolvedValue(null),
  fetchModelConfig: vi.fn().mockResolvedValue(null),
}))

vi.mock('../../services/sse', () => ({
  SSEConnection: class { constructor() { this.connect = vi.fn(); this.close = vi.fn() } },
}))

function renderCostTab() {
  return render(<ConfigProvider><CostTab /></ConfigProvider>)
}

describe('CostTab', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useStore.setState({
      theme: 'dark',
      isRunning: false,
      executionStats: { ...EMPTY_STATS },
      executionTokenRuns: [],
      executionAgentTokens: null,
      aiAssistTokens: { total: 0, calls: 0, records: [] },
      modelConfig: null,
      iterationHistory: [],
    })
  })

  it('shows empty state when no cost data', () => {
    renderCostTab()
    expect(screen.getByText('暂无成本数据，运行项目后将在此展示消耗分析')).toBeInTheDocument()
  })

  it('shows agent distribution with correct percentages', () => {
    useStore.setState({
      executionAgentTokens: { helper: 3000, coder: 5000, critique: 2000 },
      executionTokenRuns: [{ total_tokens: 10000, timestamp: Date.now(), success: true }],
    })
    renderCostTab()

    expect(screen.getByText(/智能体消耗分布/)).toBeInTheDocument()
    expect(screen.getAllByText(/辅助 AI/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/Coder AI/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/Critique AI/).length).toBeGreaterThan(0)

    expect(screen.getByText(/3,000 \(30%\)/)).toBeInTheDocument()
    expect(screen.getByText(/5,000 \(50%\)/)).toBeInTheDocument()
    expect(screen.getByText(/2,000 \(20%\)/)).toBeInTheDocument()
  })

  it('shows project cumulative statistics card', () => {
    useStore.setState({
      executionAgentTokens: { helper: 1000, coder: 4000 },
      executionTokenRuns: [
        { total_tokens: 5000, timestamp: Date.now(), success: true },
        { total_tokens: 3000, timestamp: Date.now() - 86400000, success: false },
      ],
    })
    renderCostTab()

    expect(screen.getByText(/项目统计/)).toBeInTheDocument()
    expect(screen.getByText('项目累计')).toBeInTheDocument()
    expect(screen.getByText('2')).toBeInTheDocument()
  })

  it('shows execution history list', () => {
    useStore.setState({
      executionTokenRuns: [
        { total_tokens: 5000, timestamp: Date.now(), success: true, elapsed_seconds: 60 },
        { total_tokens: 3000, timestamp: Date.now() - 86400000, success: false, elapsed_seconds: 30 },
      ],
    })
    renderCostTab()

    expect(screen.getByText(/执行历史消耗/)).toBeInTheDocument()
    expect(screen.getByText('成功')).toBeInTheDocument()
    expect(screen.getByText('失败')).toBeInTheDocument()
    expect(screen.getByText('5,000')).toBeInTheDocument()
    expect(screen.getByText('3,000')).toBeInTheDocument()
  })

  it('shows I/O token distribution when available', () => {
    useStore.setState({
      executionAgentTokens: { helper: 1000, coder: 4000 },
      executionTokenRuns: [{
        total_tokens: 10000,
        prompt_tokens: 7000,
        completion_tokens: 3000,
        cached_tokens: 2000,
        timestamp: Date.now(),
        success: true,
      }],
    })
    renderCostTab()

    expect(screen.getByText(/Token 分布/)).toBeInTheDocument()
    expect(screen.getByText(/新输入 Token/)).toBeInTheDocument()
    expect(screen.getByText(/输出 Token/)).toBeInTheDocument()
    expect(screen.getByText(/缓存命中 Token/)).toBeInTheDocument()
  })

  it('shows cache savings card when cached tokens exist', () => {
    useStore.setState({
      executionAgentTokens: { coder: 5000 },
      executionTokenRuns: [{
        total_tokens: 10000,
        prompt_tokens: 8000,
        completion_tokens: 2000,
        cached_tokens: 5000,
        timestamp: Date.now(),
        success: true,
      }],
      modelConfig: { active: { coder: { provider: 'zhipu', model: 'glm-4.7' } } },
    })
    renderCostTab()

    expect(screen.getByText(/Prompt Caching 节省/)).toBeInTheDocument()
  })

  it('shows model pricing table', () => {
    useStore.setState({
      executionAgentTokens: { helper: 1000, coder: 5000, critique: 2000 },
      executionTokenRuns: [{ total_tokens: 8000, timestamp: Date.now(), success: true }],
      modelConfig: {
        active: {
          coder: { provider: 'zhipu', model: 'glm-4.7' },
          critique: { provider: 'zhipu', model: 'glm-4.7' },
          helper: { provider: 'zhipu', model: 'glm-4.5-flash' },
        },
      },
    })
    renderCostTab()

    expect(screen.getByText(/模型单价与估算/)).toBeInTheDocument()
    expect(screen.getAllByText('glm-4.7').length).toBeGreaterThan(0)
    expect(screen.getAllByText('glm-4.5-flash').length).toBeGreaterThan(0)
  })

  it('shows free tag for free models', () => {
    useStore.setState({
      executionAgentTokens: { helper: 1000 },
      executionTokenRuns: [{ total_tokens: 1000, timestamp: Date.now(), success: true }],
      modelConfig: {
        active: {
          coder: { provider: '', model: '' },
          critique: { provider: '', model: '' },
          helper: { provider: 'zhipu', model: 'glm-4.5-flash' },
        },
      },
    })
    renderCostTab()

    expect(screen.getAllByText('免费').length).toBeGreaterThan(0)
  })

  it('shows AI assist tokens when used', () => {
    useStore.setState({
      executionTokenRuns: [{ total_tokens: 5000, timestamp: Date.now(), success: true }],
      executionAgentTokens: { coder: 5000 },
      aiAssistTokens: {
        total: 1200, calls: 3,
        records: [
          { action: 'polish', total_tokens: 500, timestamp: Date.now() },
          { action: 'recommend_tech', total_tokens: 700, timestamp: Date.now() },
        ],
      },
    })
    renderCostTab()

    expect(screen.getByText(/AI 辅助消耗/)).toBeInTheDocument()
    expect(screen.getByText('1,200')).toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()
    expect(screen.getByText('描述润色')).toBeInTheDocument()
    expect(screen.getByText('技术栈推荐')).toBeInTheDocument()
  })

  it('shows real-time stats during execution', () => {
    useStore.setState({
      isRunning: true,
      executionStats: {
        ...EMPTY_STATS,
        tokens: 8500,
        elapsed: 45,
      },
      executionTokenRuns: [],
      iterationHistory: [{ phase: 'dev', tokensUsed: 5000 }],
    })
    renderCostTab()

    expect(screen.getByText(/实时消耗/)).toBeInTheDocument()
    expect(screen.getByText('45s')).toBeInTheDocument()
  })

  it('calculates output/input ratio correctly', () => {
    useStore.setState({
      executionAgentTokens: { coder: 5000 },
      executionTokenRuns: [{
        total_tokens: 10000,
        prompt_tokens: 8000,
        completion_tokens: 2000,
        timestamp: Date.now(),
        success: true,
      }],
    })
    renderCostTab()

    expect(screen.getAllByText(/0\.25x/).length).toBeGreaterThan(0)
  })

  it('shows "最近一次" label when idle with history', () => {
    useStore.setState({
      executionTokenRuns: [{ total_tokens: 5000, timestamp: Date.now(), success: true }],
    })
    renderCostTab()

    expect(screen.getByText('最近一次')).toBeInTheDocument()
  })

  it('shows "本次执行" label with 执行中 tag when running', () => {
    useStore.setState({
      isRunning: true,
      executionStats: { ...EMPTY_STATS, tokens: 5000 },
      executionTokenRuns: [],
      iterationHistory: [{ phase: 'dev', tokensUsed: 3000 }],
    })
    renderCostTab()

    expect(screen.getByText('本次执行')).toBeInTheDocument()
    expect(screen.getByText('执行中')).toBeInTheDocument()
  })

  it('shows per-agent cost when models configured', () => {
    useStore.setState({
      executionAgentTokens: { helper: 2000, coder: 8000 },
      executionTokenRuns: [{
        total_tokens: 10000,
        prompt_tokens: 8000,
        completion_tokens: 2000,
        agent_tokens: { helper: 2000, coder: 8000 },
        timestamp: Date.now(),
        success: true,
      }],
      modelConfig: {
        active: {
          helper: { provider: 'zhipu', model: 'glm-4.5-flash' },
          coder: { provider: 'zhipu', model: 'glm-4.7' },
        },
      },
    })
    renderCostTab()

    expect(screen.getAllByText(/\$0\.\d{4}/).length).toBeGreaterThan(0)
  })

  it('shows cache rate in execution history when available', () => {
    useStore.setState({
      executionTokenRuns: [{
        total_tokens: 10000,
        prompt_tokens: 8000,
        completion_tokens: 2000,
        cached_tokens: 6400,
        timestamp: Date.now(),
        success: true,
      }],
    })
    renderCostTab()

    expect(screen.getByText(/缓存80%/)).toBeInTheDocument()
  })
})
