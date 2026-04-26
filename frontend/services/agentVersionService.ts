'use client'

import { apiGet, apiPost, apiPatch } from '@/lib/api-client'
import type {
  AgentVersion,
  CreateAgentVersionRequest,
  UpdateAgentVersionRequest,
} from '@/types/agent'

export const agentVersionService = {
  list: async (agentId: string, workspaceId: string): Promise<AgentVersion[]> => {
    const res = await apiGet<AgentVersion[]>(
      `agents/${agentId}/versions?workspace_id=${workspaceId}`,
    )
    return res ?? []
  },

  get: async (
    agentId: string,
    versionId: string,
    workspaceId: string,
  ): Promise<AgentVersion> => {
    return apiGet<AgentVersion>(
      `agents/${agentId}/versions/${versionId}?workspace_id=${workspaceId}`,
    )
  },

  create: async (
    agentId: string,
    workspaceId: string,
    data: CreateAgentVersionRequest,
  ): Promise<AgentVersion> => {
    return apiPost<AgentVersion>(
      `agents/${agentId}/versions?workspace_id=${workspaceId}`,
      data,
    )
  },

  update: async (
    agentId: string,
    versionId: string,
    workspaceId: string,
    data: UpdateAgentVersionRequest,
  ): Promise<AgentVersion> => {
    return apiPatch<AgentVersion>(
      `agents/${agentId}/versions/${versionId}?workspace_id=${workspaceId}`,
      data,
    )
  },

}
