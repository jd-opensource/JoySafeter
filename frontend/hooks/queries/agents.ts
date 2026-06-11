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
  list: (projectId: string) => [...agentKeys.all, 'list', projectId] as const,
  detail: (agentId: string, projectId: string) =>
    [...agentKeys.all, 'detail', agentId, projectId] as const,
}

// ==================== Query Hooks ====================

export function useAgents(projectId: string, options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: agentKeys.list(projectId),
    queryFn: async (): Promise<Agent[]> => {
      const agents = await agentService.list()
      return agents || []
    },
    enabled: Boolean(projectId) && options?.enabled !== false,
    staleTime: STALE_TIME.STANDARD,
    refetchOnWindowFocus: true,
    placeholderData: keepPreviousData,
  })
}

export function useAgent(agentId: string, projectId: string, options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: agentKeys.detail(agentId, projectId),
    queryFn: () => agentService.get(agentId),
    enabled: Boolean(agentId) && Boolean(projectId) && options?.enabled !== false,
    staleTime: STALE_TIME.STANDARD,
  })
}

export function useAgentNameMap(projectId: string) {
  const { data: agents = [] } = useAgents(projectId)
  return useMemo(
    () => Object.fromEntries(agents.map((a) => [a.id, a.name])) as Record<string, string>,
    [agents],
  )
}

export function useReleaseAgentNameMap(projectId: string) {
  const { data: agents = [] } = useAgents(projectId)
  return useMemo(
    () =>
      Object.fromEntries(
        agents.filter((a) => a.active_release_id).map((a) => [a.active_release_id!, a.name]),
      ) as Record<string, string>,
    [agents],
  )
}

// ==================== Mutation Hooks ====================

export function useCreateAgent() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (data: CreateAgentRequest) => {
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
      ...updates
    }: UpdateAgentRequest & { agentId: string }) => {
      return agentService.update(agentId, updates)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: agentKeys.all })
    },
  })
}

export function useDeleteAgent() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ agentId }: { agentId: string }) => {
      await agentService.delete(agentId)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: agentKeys.all })
    },
  })
}
