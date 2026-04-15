'use client'

import { apiGet, apiPost, apiPatch } from '@/lib/api-client'
import type { Mission, CreateMissionRequest, UpdateMissionRequest } from '@/types/missions'

export interface MissionListResponse {
  items: Mission[]
}

export const missionService = {
  list: async (workspaceId: string, params?: { status?: string; limit?: number }): Promise<Mission[]> => {
    const searchParams = new URLSearchParams({ workspace_id: workspaceId })
    if (params?.status) searchParams.set('status', params.status)
    if (params?.limit) searchParams.set('limit', String(params.limit))
    return apiGet<Mission[]>(`missions?${searchParams}`)
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
}
