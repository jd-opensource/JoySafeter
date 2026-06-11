'use client'

import { apiGet, apiPost } from '@/lib/api-client'
import type { AgentRelease } from '@/types/agent-release'

export const agentPublishService = {
  async publish(agentId: string) {
    const res = await apiPost<{ agent: any; release: AgentRelease }>(
      `agents/${agentId}/publish`,
    )
    return res
  },

  async rollback(agentId: string, releaseId: string) {
    const res = await apiPost<{ agent: any }>(
      `agents/${agentId}/rollback`,
      { release_id: releaseId },
    )
    return res
  },

  async retire(agentId: string, releaseId: string) {
    const res = await apiPost<AgentRelease>(
      `agents/${agentId}/releases/${releaseId}/retire`,
    )
    return res
  },

  async unpublish(agentId: string) {
    const res = await apiPost<{ agent: any; release: AgentRelease | null }>(
      `agents/${agentId}/unpublish`,
    )
    return res
  },

  async list(agentId: string): Promise<AgentRelease[]> {
    const res = await apiGet<AgentRelease[]>(
      `agents/${agentId}/releases`,
    )
    return res
  },
}
