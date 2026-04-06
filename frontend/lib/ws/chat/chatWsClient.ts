'use client'

import { generateUUID } from '@/lib/utils/uuid'
import { getWsChatUrl } from '@/lib/utils/wsUrl'
import type { ChatStreamEvent } from '@/services/chatBackend'

import { ChatWsError } from './errors'
import { HEARTBEAT, UNRECOVERABLE_CLOSE_CODES, WS_CLOSE_CODE } from '../constants'
import type {
  ChatExtension,
  ChatResumeParams,
  ChatSendParams,
  ChatTerminalResult,
  ChatWsClient,
  ConnectionState,
  IncomingChatAcceptedEvent,
  IncomingChatWsEvent,
  SkillCreatorExtension,
} from './types'

interface PendingRequest {
  requestId: string
  threadId?: string
  onEvent?: (evt: ChatStreamEvent) => void
  onAccepted?: (evt: IncomingChatAcceptedEvent) => void
  resolve: (value: ChatTerminalResult) => void
  reject: (error: Error) => void
}

const MAX_RECONNECT_DELAY_MS = 15000

class SharedChatWsClient implements ChatWsClient {
  private ws: WebSocket | null = null
  private connectPromise: Promise<void> | null = null
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null
  private reconnectAttempts = 0
  private isDisposed = false
  private lastPongTime = Date.now()
  private consecutiveParseFailures = 0
  private static readonly MAX_RECONNECT_ATTEMPTS = 20
  private static readonly MAX_PARSE_FAILURES = 10
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
              const parsed = JSON.parse(event.data) as IncomingChatWsEvent
              this.consecutiveParseFailures = 0
              this.handleInboundMessage(parsed)
            } catch {
              this.consecutiveParseFailures++
              console.warn(`[ChatWS] Malformed frame (${this.consecutiveParseFailures} consecutive)`)
              if (this.consecutiveParseFailures >= SharedChatWsClient.MAX_PARSE_FAILURES) {
                console.error('[ChatWS] Too many consecutive parse failures, reconnecting')
                this.consecutiveParseFailures = 0
                this.ws?.close()
              }
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
            this.ws = null

            if (this.connectPromise) {
              this.connectPromise = null
              reject(new ChatWsError('WS_CONNECTION_FAILED', `WebSocket connection failed (${event.code})`))
            }

            if (event.code === WS_CLOSE_CODE.UNAUTHORIZED) {
              this.state = { isConnected: false, authExpired: true }
              this.stateListeners.forEach((l) => l(this.state))
              this.rejectAllPending(new ChatWsError('WS_CONNECTION_LOST', 'Authentication expired'))
              return
            }

            this.setConnectionState(false)

            if (event.code === WS_CLOSE_CODE.NORMAL || this.isDisposed) {
              return
            }

            this.rejectAllPending(
              new ChatWsError('WS_CONNECTION_LOST', 'WebSocket disconnected'),
            )

            if (UNRECOVERABLE_CLOSE_CODES.includes(event.code as (typeof UNRECOVERABLE_CLOSE_CODES)[number])) {
              return
            }

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
    const message = params.input.message
    if (!message.trim()) {
      throw new Error('Message cannot be empty')
    }
    await this.connect()
    const requestId = params.requestId || generateUUID()
    return new Promise((resolve, reject) => {
      this.pending.set(requestId, {
        requestId,
        threadId: params.threadId || undefined,
        onEvent: params.onEvent,
        onAccepted: params.onAccepted,
        resolve,
        reject,
      })
      if (params.threadId) {
        this.threadToRequest.set(params.threadId, requestId)
      }

      try {
        this.sendFrame({
          type: 'chat.start',
          request_id: requestId,
          thread_id: params.threadId || null,
          graph_id: params.graphId || null,
          input: serializeInput(params.input),
          extension: serializeExtension(params.extension),
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
    const requestId = params.requestId || generateUUID()

    return new Promise((resolve, reject) => {
      this.pending.set(requestId, {
        requestId,
        threadId: params.threadId,
        onEvent: params.onEvent,
        onAccepted: params.onAccepted,
        resolve,
        reject,
      })
      this.threadToRequest.set(params.threadId, requestId)

      try {
        this.sendFrame({
          type: 'chat.resume',
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
      this.sendFrame({ type: 'chat.stop', request_id: requestId })
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
    this.lastPongTime = Date.now()
    this.heartbeatTimer = setInterval(() => {
      if (this.ws?.readyState !== WebSocket.OPEN) return

      if (Date.now() - this.lastPongTime > HEARTBEAT.PONG_TIMEOUT_MS) {
        console.warn('[ChatWS] Heartbeat timeout — no pong in 60s, reconnecting')
        this.ws.close()
        return
      }

      this.ws.send(JSON.stringify({ type: 'ping' }))
    }, HEARTBEAT.PING_INTERVAL_MS)
  }

  private stopHeartbeat() {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer)
      this.heartbeatTimer = null
    }
  }

  private scheduleReconnect() {
    if (this.isDisposed || this.reconnectTimer) return

    if (this.reconnectAttempts >= SharedChatWsClient.MAX_RECONNECT_ATTEMPTS) {
      console.error('[ChatWS] Max reconnect attempts reached')
      this.rejectAllPending(new ChatWsError('WS_CONNECTION_LOST', 'Connection lost. Please refresh the page.'))
      return
    }

    const delay = Math.min(1000 * 2 ** this.reconnectAttempts, MAX_RECONNECT_DELAY_MS)
    this.reconnectAttempts += 1
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      void this.connect().catch(() => {})
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
    if (!type) return
    if (type === 'pong') {
      this.lastPongTime = Date.now()
      return
    }

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

    if (type === 'accepted') {
      pending.onAccepted?.(evt as IncomingChatAcceptedEvent)
      return
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

function serializeInput(input: ChatSendParams['input']): Record<string, unknown> {
  const result: Record<string, unknown> = { message: input.message }
  if (input.files && input.files.length > 0) {
    result.files = input.files
  }
  if (input.model) {
    result.model = input.model
  }
  return result
}

function serializeExtension(extension?: SkillCreatorExtension | ChatExtension | null): Record<string, unknown> | null {
  if (!extension) {
    return null
  }

  if (extension.kind === 'skill_creator') {
    return {
      kind: extension.kind,
      run_id: (extension as SkillCreatorExtension).runId ?? null,
      edit_skill_id: (extension as SkillCreatorExtension).editSkillId ?? null,
    }
  }

  if (extension.kind === 'chat') {
    return {
      kind: extension.kind,
      run_id: (extension as ChatExtension).runId ?? null,
    }
  }

  return null
}

let singleton: SharedChatWsClient | null = null

export function getChatWsClient(): ChatWsClient {
  if (!singleton) {
    singleton = new SharedChatWsClient()
  }
  return singleton
}
