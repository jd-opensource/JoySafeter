'use client'

import { apiGet, apiPost, apiPatch } from '@/lib/api-client'
import type { ExecutionSnapshot } from '@/types/executions'
import type { Mission, CreateMissionRequest, UpdateMissionRequest } from '@/types/missions'
import type { ExecutionEventsPage } from '@/services/executionService'

export interface MissionListResponse {
  items: Mission[]
}

export const missionService = {
  list: async (workspaceId: string, params?: { status?: string; limit?: number }): Promise<Mission[]> => {
    const searchParams = new URLSearchParams({ workspace_id: workspaceId })
    if (params?.status) searchParams.set('status', params.status)
    if (params?.limit) searchParams.set('limit', String(params.limit))
    const res = await apiGet<{ items: Mission[] }>(`missions?${searchParams}`)
    return res?.items ?? []
  },

  get: async (missionId: string, workspaceId: string): Promise<Mission> => {
    return apiGet<Mission>(`missions/${missionId}?workspace_id=${workspaceId}`)
  },

  create: async (data: CreateMissionRequest): Promise<Mission> => {
    return apiPost<Mission>('missions', data)
  },

  update: async (missionId: string, workspaceId: string, data: UpdateMissionRequest): Promise<Mission> => {
    return apiPatch<Mission>(`missions/${missionId}?workspace_id=${workspaceId}`, data)
  },

  assign: async (missionId: string, workspaceId: string, agentProfileId: string): Promise<Mission> => {
    return apiPost<Mission>(`missions/${missionId}/assign?workspace_id=${workspaceId}`, {
      agent_profile_id: agentProfileId,
    })
  },

  dispatch: async (missionId: string, workspaceId: string): Promise<Mission> => {
    return apiPost<Mission>(`missions/${missionId}/dispatch?workspace_id=${workspaceId}`, {})
  },

  cancel: async (missionId: string, workspaceId: string): Promise<Mission> => {
    return apiPost<Mission>(`missions/${missionId}/cancel?workspace_id=${workspaceId}`, {})
  },

  getTransitions: async (workspaceId: string): Promise<Record<string, string[]>> => {
    return apiGet<Record<string, string[]>>(
      `missions/meta/transitions?workspace_id=${workspaceId}`,
    )
  },

  // --- Mission-scoped execution operations ---

  getExecutionEvents: async (
    missionId: string, workspaceId: string, afterSeq?: number,
  ): Promise<ExecutionEventsPage> => {
    const params = new URLSearchParams({ workspace_id: workspaceId })
    if (afterSeq !== undefined) params.set('after_seq', String(afterSeq))
    return apiGet<ExecutionEventsPage>(
      `missions/${missionId}/execution/events?${params}`,
    )
  },

  getExecutionSnapshot: async (
    missionId: string, workspaceId: string,
  ): Promise<ExecutionSnapshot> => {
    return apiGet<ExecutionSnapshot>(
      `missions/${missionId}/execution/snapshot?workspace_id=${workspaceId}`,
    )
  },

  injectExecutionMessage: async (
    missionId: string, workspaceId: string, message: string,
  ): Promise<void> => {
    await apiPost(
      `missions/${missionId}/execution/message?workspace_id=${workspaceId}`,
      { message },
    )
  },

  approveExecutionAction: async (
    missionId: string, workspaceId: string, approved: boolean,
  ): Promise<void> => {
    await apiPost(
      `missions/${missionId}/execution/approve?workspace_id=${workspaceId}`,
      { approved },
    )
  },
}
