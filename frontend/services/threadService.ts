'use client'

import { apiGet, apiPost, apiPatch, apiDelete } from '@/lib/api-client'
import type {
  Thread,
  ThreadDetail,
  ThreadMessage,
  CreateThreadRequest,
  UpdateThreadRequest,
  CreateMessageRequest,
} from '@/types/thread'

export const threadService = {
  list: async (agentId: string, workspaceId: string): Promise<Thread[]> => {
    const res = await apiGet<Thread[]>(
      `threads?agent_id=${agentId}&workspace_id=${workspaceId}`,
    )
    return res ?? []
  },

  get: async (threadId: string, workspaceId: string): Promise<ThreadDetail> => {
    return apiGet<ThreadDetail>(`threads/${threadId}?workspace_id=${workspaceId}`)
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

  // Messages
  listMessages: async (
    threadId: string,
    workspaceId: string,
  ): Promise<ThreadMessage[]> => {
    const res = await apiGet<ThreadMessage[]>(
      `threads/${threadId}/messages?workspace_id=${workspaceId}`,
    )
    return res ?? []
  },

  createMessage: async (
    threadId: string,
    workspaceId: string,
    data: CreateMessageRequest,
  ): Promise<ThreadMessage> => {
    return apiPost<ThreadMessage>(
      `threads/${threadId}/messages?workspace_id=${workspaceId}`,
      data,
    )
  },
}
