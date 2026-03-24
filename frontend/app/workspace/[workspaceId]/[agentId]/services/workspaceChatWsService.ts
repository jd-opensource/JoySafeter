'use client'

import { getWsChatUrl } from '@/lib/utils/wsUrl'

import type { ChatStreamEvent } from '@/services/chatBackend'

type IncomingWsEvent = Partial<ChatStreamEvent> & {
  type?: string
  request_id?: string
  message?: string
  thread_id?: string
  data?: any
}

interface RequestHandlers {
  onEvent?: (evt: ChatStreamEvent) => void
  resolve: (result: { requestId: string; threadId?: string }) => void
  reject: (error: Error) => void
  threadId?: string
}

class WorkspaceChatWsService {
  private ws: WebSocket | null = null
  private connectPromise: Promise<void> | null = null
  private pending = new Map<string, RequestHandlers>()
  private threadToRequest = new Map<string, string>()
  private reconnectAttempts = 0
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null

  private cleanupSocket() {
    if (this.ws) {
      this.ws.onopen = null
      this.ws.onmessage = null
      this.ws.onclose = null
      this.ws.onerror = null
      if (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING) {
        this.ws.close()
      }
      this.ws = null
    }
    this.connectPromise = null
  }

  private scheduleReconnect() {
    if (this.reconnectTimer !== null) return
    const delay = Math.min(1000 * 2 ** this.reconnectAttempts, 15000)
    this.reconnectAttempts += 1
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      this.ensureConnected().catch(() => {
        // will retry on next call
      })
    }, delay)
  }

  private handleMessage = (event: MessageEvent<string>) => {
    let evt: IncomingWsEvent | null = null
    try {
      evt = JSON.parse(event.data)
    } catch {
      return
    }
    if (!evt) return

    const type = evt.type as string | undefined
    if (type === 'pong') return

    if (type === 'ws_error') {
      const requestId = evt.request_id
      if (requestId && this.pending.has(requestId)) {
        this.pending.get(requestId)?.reject(new Error(evt.message || 'WebSocket protocol error'))
        this.pending.delete(requestId)
      }
      return
    }

    const requestId = evt.request_id
    if (!requestId) return
    const entry = this.pending.get(requestId)
    if (!entry) return

    if (evt.thread_id) {
      entry.threadId = evt.thread_id
      this.threadToRequest.set(evt.thread_id, requestId)
    }

    entry.onEvent?.(evt as ChatStreamEvent)

    if (type === 'done' || type === 'interrupt') {
      this.pending.delete(requestId)
      if (entry.threadId) {
        this.threadToRequest.delete(entry.threadId)
      }
      entry.resolve({ requestId, threadId: entry.threadId })
      return
    }

    if (type === 'error') {
      const message = (evt.data as { message?: string })?.message || 'Unknown error'
      if (message === 'Stream stopped' || message.includes('stopped')) {
        this.pending.delete(requestId)
        if (entry.threadId) {
          this.threadToRequest.delete(entry.threadId)
        }
        entry.resolve({ requestId, threadId: entry.threadId })
      } else {
        this.pending.delete(requestId)
        if (entry.threadId) {
          this.threadToRequest.delete(entry.threadId)
        }
        entry.reject(new Error(message))
      }
    }
  }

  async ensureConnected(): Promise<void> {
    if (this.ws?.readyState === WebSocket.OPEN) return
    if (this.connectPromise) return this.connectPromise

    this.connectPromise = getWsChatUrl().then((wsUrl) => new Promise<void>((resolve, reject) => {
      const ws = new WebSocket(wsUrl)
      this.ws = ws

      ws.onopen = () => {
        this.reconnectAttempts = 0
        resolve()
        this.connectPromise = null
      }
      ws.onmessage = this.handleMessage
      ws.onerror = () => {
        reject(new Error('WebSocket connection failed'))
        this.cleanupSocket()
      }
      ws.onclose = () => {
        const disconnectError = new Error('WebSocket disconnected')
        for (const entry of this.pending.values()) {
          entry.reject(disconnectError)
        }
        this.pending.clear()
        this.threadToRequest.clear()
        this.cleanupSocket()
        this.scheduleReconnect()
      }
    }))

    return this.connectPromise
  }

  async sendChat(params: {
    message: string
    threadId?: string | null
    graphId?: string | null
    metadata?: Record<string, any>
    onEvent?: (evt: ChatStreamEvent) => void
  }): Promise<{ requestId: string; threadId?: string }> {
    await this.ensureConnected()
    const requestId = crypto.randomUUID()
    return new Promise((resolve, reject) => {
      if (this.ws?.readyState !== WebSocket.OPEN) {
        reject(new Error('WebSocket not connected'))
        return
      }
      this.pending.set(requestId, {
        onEvent: params.onEvent,
        resolve,
        reject,
        threadId: params.threadId || undefined,
      })
      try {
        this.ws.send(
          JSON.stringify({
            type: 'chat',
            request_id: requestId,
            thread_id: params.threadId || null,
            graph_id: params.graphId || null,
            message: params.message,
            metadata: params.metadata || {},
          }),
        )
      } catch (err) {
        this.pending.delete(requestId)
        reject(err instanceof Error ? err : new Error(String(err)))
      }
    })
  }

  async sendResume(params: {
    threadId: string
    command: { update?: Record<string, unknown>; goto?: string }
    onEvent?: (evt: ChatStreamEvent) => void
  }): Promise<{ requestId: string; threadId?: string }> {
    await this.ensureConnected()
    const requestId = crypto.randomUUID()
    return new Promise((resolve, reject) => {
      if (this.ws?.readyState !== WebSocket.OPEN) {
        reject(new Error('WebSocket not connected'))
        return
      }
      this.pending.set(requestId, {
        onEvent: params.onEvent,
        resolve,
        reject,
        threadId: params.threadId,
      })
      this.threadToRequest.set(params.threadId, requestId)
      try {
        this.ws.send(
          JSON.stringify({
            type: 'resume',
            request_id: requestId,
            thread_id: params.threadId,
            command: params.command,
          }),
        )
      } catch (err) {
        this.pending.delete(requestId)
        this.threadToRequest.delete(params.threadId)
        reject(err instanceof Error ? err : new Error(String(err)))
      }
    })
  }

  stopByThreadId(threadId: string): void {
    const requestId = this.threadToRequest.get(threadId)
    if (!requestId || this.ws?.readyState !== WebSocket.OPEN) return
    this.ws.send(JSON.stringify({ type: 'stop', request_id: requestId }))
  }
}

export const workspaceChatWsService = new WorkspaceChatWsService()
