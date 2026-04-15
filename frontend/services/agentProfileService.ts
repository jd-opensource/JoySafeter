'use client'

import { apiGet, apiPost, apiPatch, apiDelete } from '@/lib/api-client'
import type { AgentProfile, CreateAgentRequest, UpdateAgentRequest } from '@/types/agents'

export const agentProfileService = {
  list: async (workspaceId: string): Promise<AgentProfile[]> => {
    return apiGet<AgentProfile[]>(`agent-profiles?workspace_id=${workspaceId}`)
  },

  get: async (agentId: string, workspaceId: string): Promise<AgentProfile> => {
    return apiGet<AgentProfile>(`agent-profiles/${agentId}?workspace_id=${workspaceId}`)
  },

  create: async (data: CreateAgentRequest): Promise<AgentProfile> => {
    return apiPost<AgentProfile>('agent-profiles', data)
  },

  update: async (agentId: string, workspaceId: string, data: UpdateAgentRequest): Promise<AgentProfile> => {
    return apiPatch<AgentProfile>(`agent-profiles/${agentId}?workspace_id=${workspaceId}`, data)
  },

  delete: async (agentId: string, workspaceId: string): Promise<void> => {
    await apiDelete(`agent-profiles/${agentId}?workspace_id=${workspaceId}`)
  },
}
