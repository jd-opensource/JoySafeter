/**
 * Agent Release Queries
 *
 * React Query hooks for AgentRelease, nested under Agent.
 */
import { keepPreviousData, useQuery } from '@tanstack/react-query'

import { agentReleaseService } from '@/services/agentReleaseService'

import { STALE_TIME } from './constants'
import { agentKeys } from './agents'

// ==================== Query Keys ====================

export const releaseKeys = {
  all: (agentId: string, workspaceId: string) =>
    [...agentKeys.detail(agentId, workspaceId), 'releases'] as const,
  list: (agentId: string, workspaceId: string) =>
    [...releaseKeys.all(agentId, workspaceId), 'list'] as const,
}

// ==================== Query Hooks ====================

export function useReleases(agentId: string, workspaceId: string, options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: releaseKeys.list(agentId, workspaceId),
    queryFn: async () => {
      const releases = await agentReleaseService.list(agentId, workspaceId)
      return releases || []
    },
    enabled: Boolean(agentId) && Boolean(workspaceId) && options?.enabled !== false,
    staleTime: STALE_TIME.STANDARD,
    refetchOnWindowFocus: true,
    placeholderData: keepPreviousData,
  })
}
