'use client'

import { apiGet, apiPost, apiPatch } from '@/lib/api-client'
import type {
  AgentVersion,
  CreateAgentVersionRequest,
  UpdateAgentVersionRequest,
} from '@/types/agent'

export const agentVersionService = {
  list: async (agentId: string): Promise<AgentVersion[]> => {
    const res = await apiGet<AgentVersion[]>(
      `agents/${agentId}/versions`,
    )
    return res ?? []
  },

  get: async (agentId: string, versionId: string): Promise<AgentVersion> => {
    return apiGet<AgentVersion>(
      `agents/${agentId}/versions/${versionId}`,
    )
  },

  create: async (
    agentId: string,
    data: CreateAgentVersionRequest,
  ): Promise<AgentVersion> => {
    return apiPost<AgentVersion>(`agents/${agentId}/versions`, data)
  },

  update: async (
    agentId: string,
    versionId: string,
    data: UpdateAgentVersionRequest,
  ): Promise<AgentVersion> => {
    return apiPatch<AgentVersion>(
      `agents/${agentId}/versions/${versionId}`,
      data,
    )
  },
}
