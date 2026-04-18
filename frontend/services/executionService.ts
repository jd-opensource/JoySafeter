'use client'

import { apiGet, apiPost } from '@/lib/api-client'
import type { Execution, ExecutionEventsPage } from '@/types/executions'

export const executionService = {
  list: async (workspaceId: string, params?: { mission_id?: string; status?: string; limit?: number }): Promise<Execution[]> => {
    const searchParams = new URLSearchParams({ workspace_id: workspaceId })
    if (params?.mission_id) searchParams.set('mission_id', params.mission_id)
    if (params?.status) searchParams.set('status', params.status)
    if (params?.limit) searchParams.set('limit', String(params.limit))
    const res = await apiGet<{ items: Execution[] }>(`executions?${searchParams}`)
    return res?.items ?? []
  },

  get: async (executionId: string, workspaceId: string): Promise<Execution> => {
    return apiGet<Execution>(`executions/${executionId}?workspace_id=${workspaceId}`)
  },

  getEvents: async (executionId: string, workspaceId: string, afterSeq?: number): Promise<ExecutionEventsPage> => {
    const searchParams = new URLSearchParams({ workspace_id: workspaceId })
    if (afterSeq !== undefined) searchParams.set('after_seq', String(afterSeq))
    return apiGet<ExecutionEventsPage>(`executions/${executionId}/events?${searchParams}`)
  },

  cancel: async (executionId: string, workspaceId: string): Promise<Execution> => {
    return apiPost<Execution>(`executions/${executionId}/cancel?workspace_id=${workspaceId}`, {})
  },
}
