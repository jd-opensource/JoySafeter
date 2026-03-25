'use client'

import { getWsChatUrl } from '@/lib/utils/wsUrl'
import type { ChatStreamEvent } from '@/services/chatBackend'

import { ChatWsError } from './errors'
import type {
  ChatResumeParams,
  ChatSendParams,
  ChatTerminalResult,
  ChatWsClient,
  ConnectionState,
  IncomingChatWsEvent,
} from './types'

interface PendingRequest {
  requestId: string
  threadId?: string
  onEvent?: (evt: ChatStreamEvent) => void
  resolve: (value: ChatTerminalResult) => void
  reject: (error: Error) => void
}

const HEARTBEAT_INTERVAL_MS = 30000
const MAX_RECONNECT_DELAY_MS = 15000

class SharedChatWsClient implements ChatWsClient {
  private ws: WebSocket | null = null
  private connectPromise: Promise<void> | null = null
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null
  private reconnectAttempts = 0
  private isDisposed = false
  private pending = new Map<string, PendingRequest>()
  private threadToRequest = new Map<string, string>()
  private state: ConnectionState = { isConnected: false }
  private stateListeners = new Set<(state: ConnectionState) => void>()

  connect(): Promise<void> {
    if (this.isDisposed) {
      this.isDisposed = false
    }
    if (this.ws?.readyState === WebSocket.OPEN) {
      return Promise.resolve()
    }
    if (this.connectPromise) {
      return this.connectPromise
    }

    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }

    this.connectPromise = getWsChatUrl().then(
      (wsUrl) =>
        new Promise<void>((resolve, reject) => {
          const ws = new WebSocket(wsUrl)
          this.ws = ws

          ws.onopen = () => {
            this.reconnectAttempts = 0
            this.setConnectionState(true)
            this.startHeartbeat()
            this.connectPromise = null
            resolve()
          }

          ws.onmessage = (event) => {
            try {
              this.handleInboundMessage(JSON.parse(event.data) as IncomingChatWsEvent)
            } catch {
              // Ignore malformed frames from the server.
            }
          }

          ws.onerror = () => {
            this.setConnectionState(false)
            if (this.connectPromise) {
              this.connectPromise = null
              reject(new ChatWsError('WS_CONNECTION_FAILED', 'WebSocket connection failed'))
            }
          }

          ws.onclose = (event) => {
            this.stopHeartbeat()
            this.setConnectionState(false)

            if (this.connectPromise) {
              this.connectPromise = null
              reject(new ChatWsError('WS_CONNECTION_FAILED', `WebSocket connection failed (${event.code})`))
            }

            this.ws = null

            if (event.code === 1000 || this.isDisposed) {
              return
            }

            this.rejectAllPending(
              new ChatWsError('WS_CONNECTION_LOST', event.code === 4001 ? 'Authentication expired' : 'WebSocket disconnected'),
            )
            this.scheduleReconnect()
          }
        }),
    )

    return this.connectPromise
  }

  getConnectionState(): ConnectionState {
    return this.state
  }

  subscribeConnectionState(listener: (state: ConnectionState) => void): () => void {
    this.stateListeners.add(listener)
    listener(this.state)
    return () => {
      this.stateListeners.delete(listener)
    }
  }

  async sendChat(params: ChatSendParams): Promise<ChatTerminalResult> {
    if (!params.message.trim()) {
      throw new Error('Message cannot be empty')
    }
    await this.connect()
    const requestId = params.requestId || crypto.randomUUID()
    return new Promise((resolve, reject) => {
      this.pending.set(requestId, {
        requestId,
        threadId: params.threadId || undefined,
        onEvent: params.onEvent,
        resolve,
        reject,
      })
      if (params.threadId) {
        this.threadToRequest.set(params.threadId, requestId)
      }

      try {
        this.sendFrame({
          type: 'chat',
          request_id: requestId,
          thread_id: params.threadId || null,
          graph_id: params.graphId || null,
          message: params.message,
          metadata: params.metadata || {},
        })
      } catch (error) {
        this.clearPending(requestId)
        reject(error instanceof Error ? error : new ChatWsError('WS_NOT_CONNECTED', 'WebSocket not connected'))
      }
    })
  }

  async sendResume(params: ChatResumeParams): Promise<ChatTerminalResult> {
    await this.connect()
    const requestId = params.requestId || crypto.randomUUID()

    return new Promise((resolve, reject) => {
      this.pending.set(requestId, {
        requestId,
        threadId: params.threadId,
        onEvent: params.onEvent,
        resolve,
        reject,
      })
      this.threadToRequest.set(params.threadId, requestId)

      try {
        this.sendFrame({
          type: 'resume',
          request_id: requestId,
          thread_id: params.threadId,
          command: params.command,
        })
      } catch (error) {
        this.clearPending(requestId)
        reject(error instanceof Error ? error : new ChatWsError('WS_NOT_CONNECTED', 'WebSocket not connected'))
      }
    })
  }

  stopByThreadId(threadId: string): void {
    const requestId = this.threadToRequest.get(threadId)
    if (!requestId) return
    this.stopByRequestId(requestId)
  }

  stopByRequestId(requestId: string): void {
    if (!requestId) return
    try {
      this.sendFrame({ type: 'stop', request_id: requestId })
    } catch {
      // Ignore stop failures; caller state will be reconciled on disconnect/error.
    }
  }

  dispose(): void {
    this.isDisposed = true
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    this.stopHeartbeat()
    if (this.ws) {
      this.ws.onopen = null
      this.ws.onmessage = null
      this.ws.onerror = null
      this.ws.onclose = null
      if (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING) {
        this.ws.close()
      }
      this.ws = null
    }
    this.connectPromise = null
    this.setConnectionState(false)
    this.rejectAllPending(new ChatWsError('WS_CONNECTION_LOST', 'Chat session closed'))
  }

  private setConnectionState(isConnected: boolean) {
    this.state = { isConnected }
    this.stateListeners.forEach((listener) => listener(this.state))
  }

  private startHeartbeat() {
    this.stopHeartbeat()
    this.heartbeatTimer = setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: 'ping' }))
      }
    }, HEARTBEAT_INTERVAL_MS)
  }

  private stopHeartbeat() {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer)
      this.heartbeatTimer = null
    }
  }

  private scheduleReconnect() {
    if (this.isDisposed || this.reconnectTimer) return
    const delay = Math.min(1000 * 2 ** this.reconnectAttempts, MAX_RECONNECT_DELAY_MS)
    this.reconnectAttempts += 1
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      void this.connect().catch(() => {
        // Retry continues on next close/connect call.
      })
    }, delay)
  }

  private sendFrame(payload: Record<string, unknown>) {
    if (this.ws?.readyState !== WebSocket.OPEN) {
      throw new ChatWsError('WS_NOT_CONNECTED', 'WebSocket not connected')
    }
    this.ws.send(JSON.stringify(payload))
  }

  private handleInboundMessage(evt: IncomingChatWsEvent) {
    const type: string | undefined = evt.type
    if (!type || type === 'pong') return

    const requestId = evt.request_id
    if (type === 'ws_error') {
      if (requestId) {
        this.rejectPending(
          requestId,
          new ChatWsError('WS_PROTOCOL_ERROR', evt.message || 'WebSocket protocol error', { evt }),
        )
      }
      return
    }

    if (!requestId) return
    const pending = this.pending.get(requestId)
    if (!pending) return

    if (evt.thread_id) {
      pending.threadId = evt.thread_id
      this.threadToRequest.set(evt.thread_id, requestId)
    }

    pending.onEvent?.(evt as ChatStreamEvent)

    if (type === 'interrupt') {
      this.resolvePending(requestId, 'interrupt')
      return
    }

    if (type === 'done') {
      this.resolvePending(requestId, 'done')
      return
    }

    if (type === 'error') {
      const message = (evt.data as { message?: string } | undefined)?.message || 'Unknown error'
      if (message === 'Stream stopped' || message.includes('stopped')) {
        this.resolvePending(requestId, 'stopped')
      } else {
        this.rejectPending(
          requestId,
          new ChatWsError('CHAT_EXECUTION_ERROR', message, { evt }),
        )
      }
    }
  }

  private resolvePending(requestId: string, terminal: ChatTerminalResult['terminal']) {
    const pending = this.pending.get(requestId)
    if (!pending) return
    this.clearPending(requestId)
    pending.resolve({
      requestId,
      threadId: pending.threadId,
      terminal,
    })
  }

  private rejectPending(requestId: string, error: Error) {
    const pending = this.pending.get(requestId)
    if (!pending) return
    this.clearPending(requestId)
    pending.reject(error)
  }

  private clearPending(requestId: string) {
    const pending = this.pending.get(requestId)
    if (!pending) return
    this.pending.delete(requestId)
    if (pending.threadId) {
      this.threadToRequest.delete(pending.threadId)
    }
  }

  private rejectAllPending(error: Error) {
    const requestIds = Array.from(this.pending.keys())
    requestIds.forEach((requestId) => this.rejectPending(requestId, error))
  }
}

let singleton: SharedChatWsClient | null = null

export function getChatWsClient(): ChatWsClient {
  if (!singleton) {
    singleton = new SharedChatWsClient()
  }
  return singleton
}
