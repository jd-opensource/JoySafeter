/**
 * Agent Version Queries
 *
 * React Query hooks for AgentVersion, nested under Agent.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { agentVersionService } from '@/services/agentVersionService'
import type {
  AgentVersion,
  CreateAgentVersionRequest,
  UpdateAgentVersionRequest,
} from '@/types/agent'

import { STALE_TIME } from './constants'
import { agentKeys } from './agents'

// ==================== Query Keys ====================

export const versionKeys = {
  all: (agentId: string, workspaceId: string) =>
    [...agentKeys.detail(agentId, workspaceId), 'versions'] as const,
  list: (agentId: string, workspaceId: string) =>
    [...versionKeys.all(agentId, workspaceId), 'list'] as const,
  detail: (agentId: string, versionId: string, workspaceId: string) =>
    [...versionKeys.all(agentId, workspaceId), 'detail', versionId] as const,
}

// ==================== Query Hooks ====================

export function useVersions(
  agentId: string,
  workspaceId: string,
  options?: { enabled?: boolean },
) {
  return useQuery({
    queryKey: versionKeys.list(agentId, workspaceId),
    queryFn: async (): Promise<AgentVersion[]> => {
      const versions = await agentVersionService.list(agentId, workspaceId)
      return versions || []
    },
    enabled: Boolean(agentId) && Boolean(workspaceId) && options?.enabled !== false,
    staleTime: STALE_TIME.STANDARD,
    refetchOnWindowFocus: true,
    placeholderData: keepPreviousData,
  })
}

export function useVersion(
  agentId: string,
  versionId: string,
  workspaceId: string,
  options?: { enabled?: boolean },
) {
  return useQuery({
    queryKey: versionKeys.detail(agentId, versionId, workspaceId),
    queryFn: () => agentVersionService.get(agentId, versionId, workspaceId),
    enabled:
      Boolean(agentId) &&
      Boolean(versionId) &&
      Boolean(workspaceId) &&
      options?.enabled !== false,
    staleTime: STALE_TIME.STANDARD,
  })
}

// ==================== Mutation Hooks ====================

export function useCreateVersion() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({
      agentId,
      workspaceId,
      ...data
    }: CreateAgentVersionRequest & { agentId: string; workspaceId: string }) => {
      return agentVersionService.create(agentId, workspaceId, data)
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({
        queryKey: versionKeys.all(variables.agentId, variables.workspaceId),
      })
      queryClient.invalidateQueries({
        queryKey: agentKeys.detail(variables.agentId, variables.workspaceId),
      })
    },
  })
}

export function useUpdateVersion() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({
      agentId,
      versionId,
      workspaceId,
      ...data
    }: UpdateAgentVersionRequest & {
      agentId: string
      versionId: string
      workspaceId: string
    }) => {
      return agentVersionService.update(agentId, versionId, workspaceId, data)
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({
        queryKey: versionKeys.all(variables.agentId, variables.workspaceId),
      })
    },
  })
}

export function useFreezeVersion() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({
      agentId,
      versionId,
      workspaceId,
    }: {
      agentId: string
      versionId: string
      workspaceId: string
    }) => {
      return agentVersionService.freeze(agentId, versionId, workspaceId)
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({
        queryKey: versionKeys.all(variables.agentId, variables.workspaceId),
      })
      queryClient.invalidateQueries({
        queryKey: agentKeys.detail(variables.agentId, variables.workspaceId),
      })
    },
  })
}

export function useUnfreezeVersion() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({
      agentId,
      versionId,
      workspaceId,
    }: {
      agentId: string
      versionId: string
      workspaceId: string
    }) => {
      return agentVersionService.unfreeze(agentId, versionId, workspaceId)
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({
        queryKey: versionKeys.all(variables.agentId, variables.workspaceId),
      })
      queryClient.invalidateQueries({
        queryKey: agentKeys.detail(variables.agentId, variables.workspaceId),
      })
    },
  })
}
