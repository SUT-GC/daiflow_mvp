/**
 * Singleton WebSocket client with multiplexed channel subscriptions.
 *
 * Provides two communication patterns:
 * 1. subscribe(channel, handler) — receive events published to a channel
 * 2. sendChat(stage, entityId, message, onEvent) — bidirectional chat streaming
 */

/** All known WebSocket event types from the backend. */
export type WSEventType =
  | 'text_delta'
  | 'thinking'
  | 'tool_call'
  | 'tool_result'
  | 'done'
  | 'error'
  | 'status_change'
  | 'plan_updated'
  | 'todo_updated'
  | 'code_updated'
  | 'skill_loaded'
  | 'session_status'
  | 'user_message'
  | 'compact'

export interface WSEvent {
  type: WSEventType
  content?: string
  tool_name?: string
  args?: Record<string, any>
  tool_call_id?: string
  status?: number
  error?: string
  session_id?: string
  ts?: string
  usage?: { input_tokens: number; output_tokens: number }
}

interface ServerMessage {
  // Channel event
  channel?: string
  event?: WSEvent
  // Control messages
  type?: 'subscribed' | 'pong' | 'error'
  id?: string
  code?: string
  message?: string
}

type EventHandler = (event: WSEvent) => void

/** Interval (ms) between WebSocket keepalive pings. */
const WS_PING_INTERVAL_MS = 25_000
/** Maximum delay (ms) between reconnect attempts (exponential backoff cap). */
const WS_MAX_RECONNECT_DELAY_MS = 30_000
/** Delay (ms) for low-frequency fallback reconnect after max attempts exhausted. */
const WS_FALLBACK_RECONNECT_MS = 60_000

class WebSocketClient {
  private ws: WebSocket | null = null
  private subscriptions = new Map<string, Set<EventHandler>>()
  private chatHandlers = new Map<string, EventHandler>()
  private requestIdCounter = 0
  private reconnectAttempts = 0
  private maxReconnectAttempts = 5
  private pingInterval: ReturnType<typeof setInterval> | null = null
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private intentionalClose = false
  private pendingSubscribes: string[] = []

  private getWsUrl(): string {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${protocol}//${window.location.host}/api/ws`
  }

  connect(): void {
    if (this.ws?.readyState === WebSocket.OPEN || this.ws?.readyState === WebSocket.CONNECTING) {
      return
    }

    this.intentionalClose = false

    try {
      this.ws = new WebSocket(this.getWsUrl())
    } catch {
      this.scheduleReconnect()
      return
    }

    this.ws.onopen = () => {
      this.reconnectAttempts = 0
      this.startPing()

      // Re-subscribe to all active channels
      for (const channel of this.subscriptions.keys()) {
        this.send({ action: 'subscribe', channel })
      }

      // Subscribe to any channels queued while disconnected
      for (const channel of this.pendingSubscribes) {
        if (!this.subscriptions.has(channel)) continue
        this.send({ action: 'subscribe', channel })
      }
      this.pendingSubscribes = []
    }

    this.ws.onmessage = (e: MessageEvent) => {
      try {
        const msg: ServerMessage = JSON.parse(e.data)
        this.handleMessage(msg)
      } catch {
        console.warn('WS: failed to parse message', e.data)
      }
    }

    this.ws.onclose = () => {
      this.stopPing()
      if (!this.intentionalClose) {
        this.scheduleReconnect()
      }
    }

    this.ws.onerror = () => {
      // onclose will fire after onerror, which handles reconnection
    }
  }

  disconnect(): void {
    this.intentionalClose = true
    this.stopPing()
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    this.ws?.close()
    this.ws = null
  }

  /**
   * Subscribe to a channel. Returns an unsubscribe function.
   */
  subscribe(channel: string, handler: EventHandler): () => void {
    let handlers = this.subscriptions.get(channel)
    if (!handlers) {
      handlers = new Set()
      this.subscriptions.set(channel, handlers)
      // Send subscribe to server
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.send({ action: 'subscribe', channel })
      } else {
        this.pendingSubscribes.push(channel)
      }
    }
    handlers.add(handler)

    return () => {
      handlers!.delete(handler)
      if (handlers!.size === 0) {
        this.subscriptions.delete(channel)
        if (this.ws?.readyState === WebSocket.OPEN) {
          this.send({ action: 'unsubscribe', channel })
        }
      }
    }
  }

  /**
   * Send a chat message over WS. Returns a cancel function.
   */
  sendChat(
    stage: string,
    entityId: string,
    message: string,
    onEvent: EventHandler,
  ): () => void {
    const reqId = `req_${++this.requestIdCounter}_${Date.now()}`
    const channel = `chat:${reqId}`

    this.chatHandlers.set(channel, onEvent)

    this.send({
      action: 'chat',
      id: reqId,
      chat_path: stage,
      entity_id: entityId,
      message,
    })

    return () => {
      this.chatHandlers.delete(channel)
    }
  }

  private handleMessage(msg: ServerMessage): void {
    // Control messages
    if (msg.type === 'pong') return
    if (msg.type === 'subscribed') return

    if (msg.type === 'error') {
      // Route error to chat handler if it has an id
      if (msg.id) {
        const channel = `chat:${msg.id}`
        const handler = this.chatHandlers.get(channel)
        if (handler) {
          handler({ type: 'error', content: msg.message || 'Unknown error' })
          this.chatHandlers.delete(channel)
          return
        }
      }
      console.error('WS error:', msg.code, msg.message)
      return
    }

    // Channel events
    if (msg.channel && msg.event) {
      // Try chat handlers first (chat:req_xxx channels)
      const chatHandler = this.chatHandlers.get(msg.channel)
      if (chatHandler) {
        chatHandler(msg.event)
        if (msg.event.type === 'done') {
          this.chatHandlers.delete(msg.channel)
        }
        return
      }

      // Then subscription handlers
      const handlers = this.subscriptions.get(msg.channel)
      if (handlers) {
        for (const handler of handlers) {
          handler(msg.event)
        }
      }
    }
  }

  private send(data: Record<string, any>): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data))
    }
  }

  private startPing(): void {
    this.stopPing()
    this.pingInterval = setInterval(() => {
      this.send({ action: 'ping' })
    }, WS_PING_INTERVAL_MS)
  }

  private stopPing(): void {
    if (this.pingInterval) {
      clearInterval(this.pingInterval)
      this.pingInterval = null
    }
  }

  private scheduleReconnect(): void {
    // After exhausting fast retries, fall back to low-frequency reconnect
    // so the connection can recover without requiring a page refresh.
    const delay = this.reconnectAttempts >= this.maxReconnectAttempts
      ? WS_FALLBACK_RECONNECT_MS
      : Math.min(1000 * Math.pow(2, this.reconnectAttempts), WS_MAX_RECONNECT_DELAY_MS)
    this.reconnectAttempts++

    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      this.connect()
    }, delay)
  }
}

export const wsClient = new WebSocketClient()
