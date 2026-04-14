'use client'

import { generateUUID } from '@/lib/utils/uuid'
import { getWsChatUrl } from '@/lib/utils/wsUrl'
import type { ChatStreamEvent } from '@/services/chatBackend'

import { BaseWsClient } from '../base'
import { ChatWsError } from './errors'
import type {
  ChatExtension,
  ChatResumeParams,
  ChatSendParams,
  ChatTerminalResult,
  ChatWsClient,
  ConnectionState,
  CopilotExtension,
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

class SharedChatWsClient extends BaseWsClient<ConnectionState> implements ChatWsClient {
  private static readonly MAX_PARSE_FAILURES = 10
  private consecutiveParseFailures = 0
  private pending = new Map<string, PendingRequest>()
  private threadToRequest = new Map<string, string>()

  constructor() {
    super({
      maxReconnectAttempts: 20,
      name: '[ChatWS]',
    })
  }

  protected createInitialState(): ConnectionState {
    return { isConnected: false }
  }

  protected async getWsUrl(): Promise<string> {
    return getWsChatUrl()
  }

  protected handleMessage(evt: IncomingChatWsEvent): void {
    this.consecutiveParseFailures = 0
    this.handleInboundMessage(evt)
  }

  protected override onParseError(): void {
    this.consecutiveParseFailures++
    console.warn(`[ChatWS] Malformed frame (${this.consecutiveParseFailures} consecutive)`)
    if (this.consecutiveParseFailures >= SharedChatWsClient.MAX_PARSE_FAILURES) {
      console.error('[ChatWS] Too many consecutive parse failures, reconnecting')
      this.consecutiveParseFailures = 0
      this.ws?.close()
    }
  }

  protected override onAuthExpired(): void {
    this.rejectAllPending(new ChatWsError('WS_CONNECTION_LOST', 'Authentication expired'))
  }

  protected override onUnexpectedClose(): void {
    this.rejectAllPending(new ChatWsError('WS_CONNECTION_LOST', 'WebSocket disconnected'))
  }

  protected override onReconnectExhausted(): void {
    this.rejectAllPending(new ChatWsError('WS_CONNECTION_LOST', 'Connection lost. Please refresh the page.'))
  }

  protected override onDispose(): void {
    this.rejectAllPending(new ChatWsError('WS_CONNECTION_LOST', 'Chat session closed'))
  }

  protected override createConnectionError(message: string): Error {
    return new ChatWsError('WS_CONNECTION_FAILED', message)
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
      // Ignore stop failures
    }
  }

  private handleInboundMessage(evt: IncomingChatWsEvent) {
    const type: string | undefined = evt.type
    if (!type) return

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
      const message = (typeof evt.data?.message === 'string' ? evt.data.message : null) || 'Unknown error'
      if (message === 'Stream stopped' || message.includes('stopped')) {
        this.resolvePending(requestId, 'stopped')
      } else {
        this.resolvePending(requestId, 'error')
      }
    }
  }

  private resolvePending(requestId: string, terminal: ChatTerminalResult['terminal']) {
    const pending = this.pending.get(requestId)
    if (!pending) return
    this.clearPending(requestId)
    pending.resolve({ requestId, threadId: pending.threadId, terminal })
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
  if (input.provider_name) {
    result.provider_name = input.provider_name
  }
  if (input.model_name) {
    result.model_name = input.model_name
  }
  return result
}

function serializeExtension(extension?: SkillCreatorExtension | ChatExtension | CopilotExtension | null): Record<string, unknown> | null {
  if (!extension) return null
  if (extension.kind === 'skill_creator') {
    return { kind: extension.kind, run_id: extension.runId ?? null, edit_skill_id: extension.editSkillId ?? null }
  }
  if (extension.kind === 'chat') {
    return { kind: extension.kind, run_id: extension.runId ?? null }
  }
  if (extension.kind === 'copilot') {
    return {
      kind: extension.kind, run_id: extension.runId ?? null,
      graph_context: extension.graphContext,
      conversation_history: extension.conversationHistory,
      mode: extension.mode,
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
