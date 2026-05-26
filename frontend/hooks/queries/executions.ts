/**
 * Executions Queries
 *
 * Follow project standards:
 * - Use camelCase for types
 * - API response: { success: true, data: {...} }
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { executionService } from '@/services/executionService'
import type { Execution, ExecutionEventsPage } from '@/types/executions'
import { TERMINAL_EXECUTION_STATUSES } from '@/types/executions'

import { STALE_TIME } from './constants'
import { missionKeys } from './missions'

// ==================== Query Keys ====================

export const executionKeys = {
  all: ['executions'] as const,
  list: (workspaceId: string, filters?: { mission_id?: string; status?: string; limit?: number }) =>
    [
      ...executionKeys.all,
      'list',
      workspaceId,
      filters?.mission_id || '',
      filters?.status || '',
      filters?.limit || 50,
    ] as const,
  detail: (executionId: string, workspaceId: string) =>
    [...executionKeys.all, 'detail', executionId, workspaceId] as const,
  events: (executionId: string, workspaceId: string) =>
    [...executionKeys.all, 'events', executionId, workspaceId] as const,
}

// ==================== Query Hooks ====================

export function useExecutions(
  workspaceId: string,
  filters?: { mission_id?: string; status?: string; limit?: number },
  options?: { enabled?: boolean },
) {
  return useQuery({
    queryKey: executionKeys.list(workspaceId, filters),
    queryFn: async (): Promise<Execution[]> => {
      const executions = await executionService.list(workspaceId, filters)
      return executions || []
    },
    enabled: Boolean(workspaceId) && options?.enabled !== false,
    staleTime: STALE_TIME.SHORT,
    refetchInterval: 15000,
    refetchOnWindowFocus: true,
  })
}

export function useExecution(
  executionId: string,
  workspaceId: string,
  options?: { enabled?: boolean },
) {
  return useQuery({
    queryKey: executionKeys.detail(executionId, workspaceId),
    queryFn: () => executionService.get(executionId, workspaceId),
    enabled: Boolean(executionId) && Boolean(workspaceId) && options?.enabled !== false,
    staleTime: STALE_TIME.SHORT,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      if (status && TERMINAL_EXECUTION_STATUSES.includes(status)) return false
      return 10_000
    },
  })
}

export function useExecutionEvents(
  executionId: string,
  workspaceId: string,
  afterSeq?: number,
  options?: { enabled?: boolean },
) {
  return useQuery<ExecutionEventsPage>({
    queryKey: [...executionKeys.events(executionId, workspaceId), afterSeq],
    queryFn: () => executionService.getEvents(executionId, workspaceId, afterSeq),
    enabled: Boolean(executionId) && Boolean(workspaceId) && options?.enabled !== false,
    staleTime: STALE_TIME.SHORT,
    refetchInterval: 5_000,
  })
}

// ==================== Mutation Hooks ====================

export function useCancelExecution() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({
      executionId,
      workspaceId,
    }: {
      executionId: string
      workspaceId: string
    }) => {
      return executionService.cancel(executionId, workspaceId)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: executionKeys.all })
      queryClient.invalidateQueries({ queryKey: missionKeys.all })
    },
  })
}
