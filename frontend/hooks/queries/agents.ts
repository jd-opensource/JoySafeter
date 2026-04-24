/**
 * Agent Queries
 *
 * React Query hooks for the new Agent entity (replacing AgentProfile).
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo } from 'react'

import { agentService } from '@/services/agentService'
import type { Agent, CreateAgentRequest, UpdateAgentRequest } from '@/types/agent'

import { STALE_TIME } from './constants'

// ==================== Query Keys ====================

export const agentKeys = {
  all: ['agents'] as const,
  list: (workspaceId: string) => [...agentKeys.all, 'list', workspaceId] as const,
  detail: (agentId: string, workspaceId: string) =>
    [...agentKeys.all, 'detail', agentId, workspaceId] as const,
}

// ==================== Query Hooks ====================

export function useAgents(workspaceId: string, options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: agentKeys.list(workspaceId),
    queryFn: async (): Promise<Agent[]> => {
      const agents = await agentService.list(workspaceId)
      return agents || []
    },
    enabled: Boolean(workspaceId) && options?.enabled !== false,
    staleTime: STALE_TIME.STANDARD,
    refetchOnWindowFocus: true,
    placeholderData: keepPreviousData,
  })
}

export function useAgent(
  agentId: string,
  workspaceId: string,
  options?: { enabled?: boolean },
) {
  return useQuery({
    queryKey: agentKeys.detail(agentId, workspaceId),
    queryFn: () => agentService.get(agentId, workspaceId),
    enabled: Boolean(agentId) && Boolean(workspaceId) && options?.enabled !== false,
    staleTime: STALE_TIME.STANDARD,
  })
}

export function useAgentNameMap(workspaceId: string) {
  const { data: agents = [] } = useAgents(workspaceId)
  return useMemo(
    () => Object.fromEntries(agents.map((a) => [a.id, a.name])) as Record<string, string>,
    [agents],
  )
}

export function useReleaseAgentNameMap(workspaceId: string) {
  const { data: agents = [] } = useAgents(workspaceId)
  return useMemo(
    () =>
      Object.fromEntries(
        agents
          .filter((a) => a.active_release_id)
          .map((a) => [a.active_release_id!, a.name]),
      ) as Record<string, string>,
    [agents],
  )
}

// ==================== Mutation Hooks ====================

export function useCreateAgent() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (data: CreateAgentRequest & { workspace_id: string }) => {
      return agentService.create(data)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: agentKeys.all })
    },
  })
}

export function useUpdateAgent() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({
      agentId,
      workspaceId,
      ...updates
    }: UpdateAgentRequest & { agentId: string; workspaceId: string }) => {
      return agentService.update(agentId, workspaceId, updates)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: agentKeys.all })
    },
  })
}

export function useArchiveAgent() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ agentId, workspaceId }: { agentId: string; workspaceId: string }) => {
      await agentService.archive(agentId, workspaceId)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: agentKeys.all })
    },
  })
}
