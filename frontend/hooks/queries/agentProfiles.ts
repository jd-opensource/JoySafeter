/**
 * Agent Profiles Queries
 *
 * Follow project standards:
 * - Use camelCase for types
 * - API response: { success: true, data: {...} }
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { agentProfileService } from '@/services/agentProfileService'
import type { AgentProfile, CreateAgentRequest, UpdateAgentRequest } from '@/types/agents'

import { STALE_TIME } from './constants'

// ==================== Query Keys ====================

export const agentProfileKeys = {
  all: ['agent-profiles'] as const,
  list: (workspaceId: string) => [...agentProfileKeys.all, 'list', workspaceId] as const,
  detail: (agentId: string, workspaceId: string) =>
    [...agentProfileKeys.all, 'detail', agentId, workspaceId] as const,
}

// ==================== Query Hooks ====================

export function useAgentProfiles(workspaceId: string, options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: agentProfileKeys.list(workspaceId),
    queryFn: async (): Promise<AgentProfile[]> => {
      const agents = await agentProfileService.list(workspaceId)
      return agents || []
    },
    enabled: Boolean(workspaceId) && options?.enabled !== false,
    staleTime: STALE_TIME.STANDARD,
    refetchOnWindowFocus: true,
    placeholderData: keepPreviousData,
  })
}

export function useAgentProfile(
  agentId: string,
  workspaceId: string,
  options?: { enabled?: boolean },
) {
  return useQuery({
    queryKey: agentProfileKeys.detail(agentId, workspaceId),
    queryFn: () => agentProfileService.get(agentId, workspaceId),
    enabled: Boolean(agentId) && Boolean(workspaceId) && options?.enabled !== false,
    staleTime: STALE_TIME.STANDARD,
  })
}

// ==================== Mutation Hooks ====================

export function useCreateAgentProfile() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (data: CreateAgentRequest) => {
      return agentProfileService.create(data)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: agentProfileKeys.all })
    },
  })
}

export function useUpdateAgentProfile() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({
      agentId,
      workspaceId,
      ...updates
    }: UpdateAgentRequest & { agentId: string; workspaceId: string }) => {
      return agentProfileService.update(agentId, workspaceId, updates)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: agentProfileKeys.all })
    },
  })
}

export function useDeleteAgentProfile() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ agentId, workspaceId }: { agentId: string; workspaceId: string }) => {
      await agentProfileService.delete(agentId, workspaceId)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: agentProfileKeys.all })
    },
  })
}
