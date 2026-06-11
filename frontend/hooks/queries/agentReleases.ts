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
  all: (agentId: string, projectId: string) =>
    [...agentKeys.detail(agentId, projectId), 'releases'] as const,
  list: (agentId: string, projectId: string) =>
    [...releaseKeys.all(agentId, projectId), 'list'] as const,
}

// ==================== Query Hooks ====================

export function useReleases(agentId: string, projectId: string, options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: releaseKeys.list(agentId, projectId),
    queryFn: async () => {
      const releases = await agentReleaseService.list(agentId)
      return releases || []
    },
    enabled: Boolean(agentId) && Boolean(projectId) && options?.enabled !== false,
    staleTime: STALE_TIME.STANDARD,
    refetchOnWindowFocus: true,
    placeholderData: keepPreviousData,
  })
}
