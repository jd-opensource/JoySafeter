'use client'

import { getChatWsClient } from '@/lib/ws/chat/chatWsClient'

import type { ChatStreamEvent } from '@/services/chatBackend'

class WorkspaceChatWsService {
  private client = getChatWsClient()

  async ensureConnected(): Promise<void> {
    await this.client.connect()
  }

  async sendChat(params: {
    message: string
    threadId?: string | null
    graphId?: string | null
    metadata?: Record<string, any>
    onEvent?: (evt: ChatStreamEvent) => void
  }): Promise<{ requestId: string; threadId?: string }> {
    const result = await this.client.sendChat({
      threadId: params.threadId,
      graphId: params.graphId,
      input: { message: params.message },
      extension: null,
      metadata: params.metadata ?? {},
      onEvent: params.onEvent,
    })
    return { requestId: result.requestId, threadId: result.threadId }
  }

  async sendResume(params: {
    threadId: string
    command: { update?: Record<string, unknown>; goto?: string }
    onEvent?: (evt: ChatStreamEvent) => void
  }): Promise<{ requestId: string; threadId?: string }> {
    const result = await this.client.sendResume(params)
    return { requestId: result.requestId, threadId: result.threadId }
  }

  stopByThreadId(threadId: string): void {
    this.client.stopByThreadId(threadId)
  }
}

export const workspaceChatWsService = new WorkspaceChatWsService()
