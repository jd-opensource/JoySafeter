'use client'

import { apiGet } from '@/lib/api-client'
import type { AgentRelease } from '@/types/agent-release'

export const agentReleaseService = {
  list: async (agentId: string): Promise<AgentRelease[]> => {
    const res = await apiGet<AgentRelease[]>(
      `agents/${agentId}/releases`,
    )
    return res ?? []
  },

  get: async (agentId: string, releaseId: string): Promise<AgentRelease> => {
    return apiGet<AgentRelease>(
      `agents/${agentId}/releases/${releaseId}`,
    )
  },
}
