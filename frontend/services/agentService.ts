'use client'

import { apiGet, apiPost, apiPatch, apiDelete } from '@/lib/api-client'
import type { Agent, CreateAgentRequest, UpdateAgentRequest } from '@/types/agent'

export const agentService = {
  list: async (): Promise<Agent[]> => {
    const res = await apiGet<Agent[]>(`agents`)
    return res ?? []
  },

  get: async (agentId: string): Promise<Agent> => {
    return apiGet<Agent>(`agents/${agentId}`)
  },

  create: async (data: CreateAgentRequest): Promise<Agent> => {
    return apiPost<Agent>(`agents`, data)
  },

  update: async (
    agentId: string,
    data: UpdateAgentRequest,
  ): Promise<Agent> => {
    return apiPatch<Agent>(`agents/${agentId}`, data)
  },

  delete: async (agentId: string): Promise<void> => {
    await apiDelete(`agents/${agentId}`)
  },
}
