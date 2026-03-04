import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, act, fireEvent } from '@testing-library/react'
import { ConfigProvider } from 'antd'
import useStore from '../../stores/useStore'

// ---- xterm mocks: define constructors INSIDE factory to avoid hoisting issues ----

vi.mock('@xterm/xterm', () => ({
  Terminal: vi.fn(function () {
    this.loadAddon = vi.fn(); this.open = vi.fn()
    this.write = vi.fn(); this.writeln = vi.fn()
    this.clear = vi.fn(); this.dispose = vi.fn()
    this.focus = vi.fn(); this.onData = vi.fn()
    this.onResize = vi.fn(); this.cols = 80; this.rows = 24
  })
}))
vi.mock('@xterm/addon-fit', () => ({
  FitAddon: vi.fn(function () { this.fit = vi.fn() })
}))
vi.mock('@xterm/addon-web-links', () => ({
  WebLinksAddon: vi.fn(function () {})
}))
vi.mock('@xterm/xterm/css/xterm.css', () => ({}))
vi.mock('../../services/api', () => ({
  fetchProjects: vi.fn().mockResolvedValue([]),
  fetchConfig: vi.fn().mockResolvedValue(null),
  fetchModelConfig: vi.fn().mockResolvedValue(null),
}))
vi.mock('../../services/sse', () => ({
  SSEConnection: class { constructor() { this.connect = vi.fn(); this.close = vi.fn() } },
}))

// Get the actual mock reference through the mocked import
const { Terminal: TermMock } = await import('@xterm/xterm')
const { default: WebTerminal } = await import('../../components/shared/WebTerminal')

// ---- WebSocket mock ----

let wsList = []
class FakeWS {
  constructor(url) {
    this.url = url; this.readyState = 0
    this.onopen = this.onmessage = this.onclose = this.onerror = null
    this._sent = []; wsList.push(this)
  }
  send(d) { this._sent.push(JSON.parse(d)) }
  close() { this.readyState = 3 }
  _open() { this.readyState = 1; this.onopen?.() }
  _msg(d) { this.onmessage?.({ data: JSON.stringify(d) }) }
  _close() { this.readyState = 3; this.onclose?.() }
}
FakeWS.OPEN = 1; FakeWS.CONNECTING = 0; FakeWS.CLOSING = 2; FakeWS.CLOSED = 3

// ---- Helpers ----

const mount = (props = {}) => render(
  <ConfigProvider>
    <WebTerminal wsUrl={props.wsUrl ?? null} height={props.height ?? 400} />
  </ConfigProvider>
)
const flush = () => act(async () => {})

function getTerm() {
  const instances = TermMock.mock.instances
  return instances[instances.length - 1]
}

async function connectAs(mode = 'local') {
  mount({ wsUrl: 'ws://test/terminal/p' })
  await flush()
  const ws = wsList[wsList.length - 1]
  act(() => { ws._open(); ws._msg({ type: 'status', data: 'connected', mode }) })
  return ws
}

function clickSwap() { fireEvent.click(screen.getAllByRole('button')[0]) }

// ===================================================================

describe('WebTerminal', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    wsList = []
    global.WebSocket = FakeWS
    global.ResizeObserver = class { observe() {} disconnect() {} }
    Object.defineProperty(document, 'fonts', {
      value: { ready: Promise.resolve() }, writable: true, configurable: true,
    })
    useStore.setState({ theme: 'dark' })
  })

  // ---- UI ----

  it('renders disconnected status without wsUrl', async () => {
    mount(); await flush()
    expect(screen.getByText('终端')).toBeInTheDocument()
    expect(screen.getByText('○ 未连接')).toBeInTheDocument()
  })

  // ---- CSS (修复: CDN v5 → 本地 v6) ----

  it('does not inject CDN stylesheet link', async () => {
    mount({ wsUrl: 'ws://test/terminal/p' }); await flush()
    expect(document.querySelectorAll('link[href*="cdn.jsdelivr"]')).toHaveLength(0)
  })

  // ---- 连接生命周期 ----

  it('creates WS with mode=local and Terminal instance', async () => {
    mount({ wsUrl: 'ws://test/terminal/p' }); await flush()
    expect(wsList).toHaveLength(1)
    expect(wsList[0].url).toContain('mode=local')
    expect(TermMock.mock.instances.length).toBeGreaterThan(0)
  })

  it('shows connected + mode label', async () => {
    await connectAs('local')
    expect(screen.getByText('● 已连接')).toBeInTheDocument()
    expect(screen.getByText('本地终端')).toBeInTheDocument()
  })

  it('sends resize when cols/rows > 0', async () => {
    mount({ wsUrl: 'ws://test/terminal/p' }); await flush()
    act(() => wsList[0]._open())
    expect(wsList[0]._sent).toContainEqual({ type: 'resize', cols: 80, rows: 24 })
  })

  it('skips resize when terminal is 0x0 (隐藏 Tab)', async () => {
    mount({ wsUrl: 'ws://test/terminal/p' }); await flush()
    const t = getTerm()
    t.cols = 0; t.rows = 0
    act(() => wsList[0]._open())
    expect(wsList[0]._sent.find(m => m.type === 'resize')).toBeUndefined()
  })

  it('writes shell output to xterm', async () => {
    mount({ wsUrl: 'ws://test/terminal/p' }); await flush()
    const t = getTerm()
    act(() => wsList[0]._open())
    t.write.mockClear()
    act(() => wsList[0]._msg({ type: 'output', data: '$ ' }))
    expect(t.write).toHaveBeenCalledWith('$ ')
  })

  // ---- Stale connection (Bug2 修复) ----

  it('old WS onclose does NOT reset connected state', async () => {
    const ws1 = await connectAs('local')
    clickSwap()
    const ws2 = wsList[1]
    act(() => { ws2._open(); ws2._msg({ type: 'status', data: 'connected', mode: 'docker' }) })
    act(() => ws1._close())
    expect(screen.getByText('● 已连接')).toBeInTheDocument()
  })

  it('old WS onclose does NOT write 连接已关闭', async () => {
    const ws1 = await connectAs('local')
    const t = getTerm()
    clickSwap()
    act(() => { wsList[1]._open(); wsList[1]._msg({ type: 'status', data: 'connected', mode: 'docker' }) })
    t.writeln.mockClear()
    act(() => ws1._close())
    expect(t.writeln.mock.calls.filter(c => c[0]?.includes('连接已关闭'))).toHaveLength(0)
  })

  it('old WS onmessage is ignored after replacement', async () => {
    await connectAs('local')
    const t = getTerm()
    clickSwap()
    act(() => { wsList[1]._open(); wsList[1]._msg({ type: 'status', data: 'connected', mode: 'docker' }) })
    t.write.mockClear()
    act(() => wsList[0]._msg({ type: 'output', data: 'stale' }))
    expect(t.write).not.toHaveBeenCalled()
  })

  // ---- 模式切换 ----

  it('switches from local to docker', async () => {
    await connectAs('local')
    clickSwap()
    expect(wsList[1].url).toContain('mode=docker')
    act(() => { wsList[1]._open(); wsList[1]._msg({ type: 'status', data: 'connected', mode: 'docker' }) })
    expect(screen.getByText('Docker 终端')).toBeInTheDocument()
  })

  it('full round-trip local→docker→local without 连接已关闭', async () => {
    await connectAs('local')
    const t = getTerm()
    clickSwap()
    act(() => { wsList[0]._close(); wsList[1]._open(); wsList[1]._msg({ type: 'status', data: 'connected', mode: 'docker' }) })
    clickSwap()
    act(() => { wsList[1]._close(); wsList[2]._open(); wsList[2]._msg({ type: 'status', data: 'connected', mode: 'local' }) })
    expect(t.writeln.mock.calls.filter(c => c[0]?.includes('连接已关闭'))).toHaveLength(0)
    expect(screen.getByText('本地终端')).toBeInTheDocument()
    expect(screen.getByText('● 已连接')).toBeInTheDocument()
  })

  // ---- I/O ----

  it('forwards keyboard input via onData', async () => {
    mount({ wsUrl: 'ws://test/terminal/p' }); await flush()
    const t = getTerm()
    act(() => wsList[0]._open())
    const cb = t.onData.mock.calls[0]?.[0]
    expect(cb).toBeTypeOf('function')
    act(() => cb('ls\r'))
    expect(wsList[0]._sent).toContainEqual({ type: 'input', data: 'ls\r' })
  })

  it('sends resize when terminal dimensions change', async () => {
    mount({ wsUrl: 'ws://test/terminal/p' }); await flush()
    const t = getTerm()
    act(() => wsList[0]._open())
    wsList[0]._sent = []
    const cb = t.onResize.mock.calls[0]?.[0]
    expect(cb).toBeTypeOf('function')
    act(() => cb({ cols: 120, rows: 40 }))
    expect(wsList[0]._sent).toContainEqual({ type: 'resize', cols: 120, rows: 40 })
  })
})
