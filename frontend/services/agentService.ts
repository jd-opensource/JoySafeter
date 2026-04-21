'use client'

import { apiGet, apiPost, apiPatch, apiDelete } from '@/lib/api-client'
import type { Agent, CreateAgentRequest, UpdateAgentRequest } from '@/types/agent'

export const agentService = {
  list: async (workspaceId: string): Promise<Agent[]> => {
    const res = await apiGet<Agent[]>(`agents?workspace_id=${workspaceId}`)
    return res ?? []
  },

  get: async (agentId: string, workspaceId: string): Promise<Agent> => {
    return apiGet<Agent>(`agents/${agentId}?workspace_id=${workspaceId}`)
  },

  create: async (data: CreateAgentRequest & { workspace_id: string }): Promise<Agent> => {
    const { workspace_id, ...body } = data
    return apiPost<Agent>(`agents?workspace_id=${workspace_id}`, body)
  },

  update: async (
    agentId: string,
    workspaceId: string,
    data: UpdateAgentRequest,
  ): Promise<Agent> => {
    return apiPatch<Agent>(`agents/${agentId}?workspace_id=${workspaceId}`, data)
  },

  archive: async (agentId: string, workspaceId: string): Promise<void> => {
    await apiDelete(`agents/${agentId}?workspace_id=${workspaceId}`)
  },
}
