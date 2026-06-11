'use client'

import { apiGet, apiPost, apiPatch, apiDelete } from '@/lib/api-client'
import type {
  Thread,
  ThreadEvent,
  ChatAttachment,
  ChatResponse,
  CreateThreadRequest,
  UpdateThreadRequest,
} from '@/types/thread'

export const threadService = {
  list: async (agentId: string): Promise<Thread[]> => {
    const res = await apiGet<Thread[]>(`threads?agent_id=${agentId}`)
    return res ?? []
  },

  get: async (threadId: string): Promise<Thread> => {
    return apiGet<Thread>(`threads/${threadId}`)
  },

  create: async (data: CreateThreadRequest): Promise<Thread> => {
    return apiPost<Thread>(`threads`, data)
  },

  update: async (
    threadId: string,
    data: UpdateThreadRequest,
  ): Promise<Thread> => {
    return apiPatch<Thread>(`threads/${threadId}`, data)
  },

  archive: async (threadId: string): Promise<void> => {
    await apiDelete(`threads/${threadId}`)
  },

  listThreadEvents: async (
    threadId: string,
    options?: { after?: string; limit?: number },
  ): Promise<{ events: ThreadEvent[]; total: number }> => {
    const params = new URLSearchParams()
    if (options?.after) params.set('after', options.after)
    if (options?.limit) params.set('limit', String(options.limit))
    return apiGet(`threads/${threadId}/events?${params}`)
  },

  sendChat: async (
    threadId: string,
    message: string,
    attachments: ChatAttachment[] = [],
  ): Promise<ChatResponse> => {
    return apiPost<ChatResponse>(`threads/${threadId}/chat`, {
      message,
      attachments: attachments.length ? attachments : undefined,
    })
  },
}
