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
  list: async (agentId: string, workspaceId: string): Promise<Thread[]> => {
    const res = await apiGet<Thread[]>(
      `threads?agent_id=${agentId}&workspace_id=${workspaceId}`,
    )
    return res ?? []
  },

  get: async (threadId: string, workspaceId: string): Promise<Thread> => {
    return apiGet<Thread>(`threads/${threadId}?workspace_id=${workspaceId}`)
  },

  create: async (
    data: CreateThreadRequest & { workspace_id: string },
  ): Promise<Thread> => {
    const { workspace_id, ...body } = data
    return apiPost<Thread>(`threads?workspace_id=${workspace_id}`, body)
  },

  update: async (
    threadId: string,
    workspaceId: string,
    data: UpdateThreadRequest,
  ): Promise<Thread> => {
    return apiPatch<Thread>(
      `threads/${threadId}?workspace_id=${workspaceId}`,
      data,
    )
  },

  archive: async (threadId: string, workspaceId: string): Promise<void> => {
    await apiDelete(`threads/${threadId}?workspace_id=${workspaceId}`)
  },

  listThreadEvents: async (
    threadId: string,
    workspaceId: string,
    options?: { after?: string; limit?: number },
  ): Promise<{ events: ThreadEvent[]; total: number }> => {
    const params = new URLSearchParams({ workspace_id: workspaceId })
    if (options?.after) params.set('after', options.after)
    if (options?.limit) params.set('limit', String(options.limit))
    return apiGet(`threads/${threadId}/events?${params}`)
  },

  sendChat: async (
    threadId: string,
    workspaceId: string,
    message: string,
    attachments: ChatAttachment[] = [],
  ): Promise<ChatResponse> => {
    return apiPost<ChatResponse>(
      `threads/${threadId}/chat?workspace_id=${workspaceId}`,
      { message, attachments: attachments.length ? attachments : undefined },
    )
  },
}
