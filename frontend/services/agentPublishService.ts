'use client'

import { apiGet, apiPost } from '@/lib/api-client'
import type { AgentRelease } from '@/types/agent-release'

export const agentPublishService = {
  async publish(agentId: string, workspaceId: string) {
    const res = await apiPost<{ agent: any; release: AgentRelease }>(
      `agents/${agentId}/publish?workspace_id=${workspaceId}`,
    )
    return res
  },

  async rollback(agentId: string, releaseId: string, workspaceId: string) {
    const res = await apiPost<{ agent: any }>(
      `agents/${agentId}/rollback?workspace_id=${workspaceId}`,
      { release_id: releaseId },
    )
    return res
  },

  async retire(agentId: string, releaseId: string, workspaceId: string) {
    const res = await apiPost<AgentRelease>(
      `agents/${agentId}/releases/${releaseId}/retire?workspace_id=${workspaceId}`,
    )
    return res
  },

  async list(agentId: string, workspaceId: string): Promise<AgentRelease[]> {
    const res = await apiGet<AgentRelease[]>(
      `agents/${agentId}/releases?workspace_id=${workspaceId}`,
    )
    return res
  },
}
