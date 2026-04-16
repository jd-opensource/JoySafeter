'use client'

import { apiGet, apiPost } from '@/lib/api-client'
import type { Execution, ExecutionEvent, ExecutionSnapshot } from '@/types/executions'

export interface ExecutionEventsPage {
  execution_id: string
  events: ExecutionEvent[]
  next_after_seq: number
}

export const executionService = {
  list: async (workspaceId: string, params?: { mission_id?: string; status?: string; limit?: number }): Promise<Execution[]> => {
    const searchParams = new URLSearchParams({ workspace_id: workspaceId })
    if (params?.mission_id) searchParams.set('mission_id', params.mission_id)
    if (params?.status) searchParams.set('status', params.status)
    if (params?.limit) searchParams.set('limit', String(params.limit))
    return apiGet<Execution[]>(`executions?${searchParams}`)
  },

  get: async (executionId: string, workspaceId: string): Promise<Execution> => {
    return apiGet<Execution>(`executions/${executionId}?workspace_id=${workspaceId}`)
  },

  getEvents: async (executionId: string, workspaceId: string, afterSeq?: number): Promise<ExecutionEventsPage> => {
    const searchParams = new URLSearchParams({ workspace_id: workspaceId })
    if (afterSeq !== undefined) searchParams.set('after_seq', String(afterSeq))
    return apiGet<ExecutionEventsPage>(`executions/${executionId}/events?${searchParams}`)
  },

  getSnapshot: async (executionId: string, workspaceId: string): Promise<ExecutionSnapshot> => {
    return apiGet<ExecutionSnapshot>(`executions/${executionId}/snapshot?workspace_id=${workspaceId}`)
  },

  cancel: async (executionId: string, workspaceId: string): Promise<Execution> => {
    return apiPost<Execution>(`executions/${executionId}/cancel?workspace_id=${workspaceId}`, {})
  },

  injectMessage: async (executionId: string, message: string): Promise<void> => {
    await apiPost(`executions/${executionId}/message`, { message })
  },

  approveAction: async (executionId: string, approved: boolean, message?: string): Promise<void> => {
    await apiPost(`executions/${executionId}/approve`, { approved, message })
  },
}
