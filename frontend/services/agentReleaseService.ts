'use client'

import { apiGet, apiPost } from '@/lib/api-client'
import type { AgentRelease, CreateAgentReleaseRequest } from '@/types/agent-release'

export const agentReleaseService = {
  list: async (agentId: string, workspaceId: string): Promise<AgentRelease[]> => {
    const res = await apiGet<AgentRelease[]>(
      `agents/${agentId}/releases?workspace_id=${workspaceId}`,
    )
    return res ?? []
  },

  get: async (
    agentId: string,
    releaseId: string,
    workspaceId: string,
  ): Promise<AgentRelease> => {
    return apiGet<AgentRelease>(
      `agents/${agentId}/releases/${releaseId}?workspace_id=${workspaceId}`,
    )
  },

  publish: async (
    agentId: string,
    workspaceId: string,
    data: CreateAgentReleaseRequest,
  ): Promise<AgentRelease> => {
    return apiPost<AgentRelease>(
      `agents/${agentId}/releases?workspace_id=${workspaceId}`,
      data,
    )
  },

  activate: async (
    agentId: string,
    releaseId: string,
    workspaceId: string,
  ): Promise<AgentRelease> => {
    return apiPost<AgentRelease>(
      `agents/${agentId}/releases/${releaseId}/activate?workspace_id=${workspaceId}`,
      {},
    )
  },

  retire: async (
    agentId: string,
    releaseId: string,
    workspaceId: string,
  ): Promise<AgentRelease> => {
    return apiPost<AgentRelease>(
      `agents/${agentId}/releases/${releaseId}/retire?workspace_id=${workspaceId}`,
      {},
    )
  },
}
