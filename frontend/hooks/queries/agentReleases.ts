/**
 * Agent Release Queries
 *
 * React Query hooks for AgentRelease, nested under Agent.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { agentReleaseService } from '@/services/agentReleaseService'
import type { CreateAgentReleaseRequest } from '@/types/agent-release'

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

export function useReleases(
  agentId: string,
  workspaceId: string,
  options?: { enabled?: boolean },
) {
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

// ==================== Mutation Hooks ====================

export function usePublishRelease() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({
      agentId,
      workspaceId,
      ...data
    }: CreateAgentReleaseRequest & { agentId: string; workspaceId: string }) => {
      return agentReleaseService.publish(agentId, workspaceId, data)
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({
        queryKey: releaseKeys.all(variables.agentId, variables.workspaceId),
      })
      queryClient.invalidateQueries({
        queryKey: agentKeys.detail(variables.agentId, variables.workspaceId),
      })
    },
  })
}

export function useActivateRelease() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({
      agentId,
      releaseId,
      workspaceId,
    }: {
      agentId: string
      releaseId: string
      workspaceId: string
    }) => {
      return agentReleaseService.activate(agentId, releaseId, workspaceId)
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({
        queryKey: releaseKeys.all(variables.agentId, variables.workspaceId),
      })
      queryClient.invalidateQueries({
        queryKey: agentKeys.detail(variables.agentId, variables.workspaceId),
      })
    },
  })
}

export function useRetireRelease() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({
      agentId,
      releaseId,
      workspaceId,
    }: {
      agentId: string
      releaseId: string
      workspaceId: string
    }) => {
      return agentReleaseService.retire(agentId, releaseId, workspaceId)
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({
        queryKey: releaseKeys.all(variables.agentId, variables.workspaceId),
      })
      queryClient.invalidateQueries({
        queryKey: agentKeys.detail(variables.agentId, variables.workspaceId),
      })
    },
  })
}
