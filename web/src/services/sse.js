// SSE 连接管理（含断线恢复：从历史 API 回放丢失事件后重连 SSE）
export class SSEConnection {
  constructor(sessionId, handlers = {}) {
    this.sessionId = sessionId
    this.handlers = handlers
    this.eventSource = null
    this._eventCount = 0
    this._closed = false
    this._reconnectTimer = null
    this._maxReconnects = 3
    this._reconnects = 0
  }

  // 统一创建 EventSource，确保 onmessage / onerror / onopen 三个回调都挂载
  _createEventSource() {
    const skipCount = this._eventCount
    let received = 0
    const es = new EventSource(`/api/v1/events/${this.sessionId}`)

    es.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data)
        received++
        // 后端 SSE 会先重放历史事件，跳过已通过 history API 加载的部分
        if (received <= skipCount) return
        this._eventCount++
        this._reconnects = 0
        this.handlers.onEvent?.(event)
        const handler = this.handlers[event.type]
        if (handler) handler(event)
      } catch (err) {
        console.error('SSE parse error:', err)
      }
    }

    es.onerror = () => {
      if (this._closed) return
      this.eventSource?.close()
      this.eventSource = null

      if (this._reconnects < this._maxReconnects) {
        this._reconnects++
        const delay = Math.min(2000 * this._reconnects, 8000)
        console.log(`SSE disconnected, recovering in ${delay}ms (attempt ${this._reconnects})`)
        this._reconnectTimer = setTimeout(() => this._recoverFromHistory(), delay)
      } else {
        this.handlers.onError?.()
      }
    }

    es.onopen = () => {
      this.handlers.onOpen?.()
    }

    return es
  }

  connect() {
    if (this.eventSource) this.close()
    this._closed = false
    this.eventSource = this._createEventSource()
  }

  async _recoverFromHistory() {
    if (this._closed) return
    try {
      const resp = await fetch(`/api/v1/sessions/${this.sessionId}/events`)
      if (!resp.ok) { this.handlers.onError?.(); return }
      const data = await resp.json()
      const events = data.events || []
      const status = data.status

      const missed = events.slice(this._eventCount)
      for (const evt of missed) {
        this._eventCount++
        this.handlers.onEvent?.(evt)
        const handler = this.handlers[evt.type]
        if (handler) handler(evt)
      }

      if (status === 'running') {
        this.eventSource = this._createEventSource()
      }
    } catch {
      this.handlers.onError?.()
    }
  }

  close() {
    this._closed = true
    if (this._reconnectTimer) { clearTimeout(this._reconnectTimer); this._reconnectTimer = null }
    if (this.eventSource) { this.eventSource.close(); this.eventSource = null }
  }
}
