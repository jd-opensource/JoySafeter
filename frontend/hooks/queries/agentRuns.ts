/**
 * Agent Run Queries
 *
 * React Query hooks for AgentRun and Execution.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { agentRunService } from '@/services/agentRunService'
import type {
  AgentRun,
  CreateAgentRunRequest,
  Execution,
  ExecutionEvent,
} from '@/types/agent-run'
import { TERMINAL_RUN_STATUSES, TERMINAL_EXECUTION_STATUSES } from '@/types/agent-run'

import { STALE_TIME } from './constants'

// ==================== Query Keys ====================

export const agentRunKeys = {
  all: ['agent-runs'] as const,
  list: (filters?: { workspace_id?: string; release_id?: string; task_id?: string }) =>
    [
      ...agentRunKeys.all,
      'list',
      filters?.workspace_id || '',
      filters?.release_id || '',
      filters?.task_id || '',
    ] as const,
  detail: (runId: string) => [...agentRunKeys.all, 'detail', runId] as const,
  executions: (runId: string) => [...agentRunKeys.all, 'executions', runId] as const,
  execution: (executionId: string) => [...agentRunKeys.all, 'execution', executionId] as const,
  events: (executionId: string) => [...agentRunKeys.all, 'events', executionId] as const,
}

// ==================== Query Hooks ====================

export function useAgentRuns(
  filters?: { workspace_id?: string; release_id?: string; task_id?: string },
  options?: { enabled?: boolean },
) {
  return useQuery({
    queryKey: agentRunKeys.list(filters),
    queryFn: async (): Promise<AgentRun[]> => {
      const runs = await agentRunService.list(filters || {})
      return runs || []
    },
    enabled: options?.enabled !== false,
    staleTime: STALE_TIME.SHORT,
    refetchInterval: 15000,
    refetchOnWindowFocus: true,
  })
}

export function useAgentRun(runId: string, options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: agentRunKeys.detail(runId),
    queryFn: () => agentRunService.get(runId),
    enabled: Boolean(runId) && options?.enabled !== false,
    staleTime: STALE_TIME.SHORT,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      if (status && TERMINAL_RUN_STATUSES.includes(status)) return false
      return 10_000
    },
  })
}

export function useRunExecutions(runId: string, options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: agentRunKeys.executions(runId),
    queryFn: async (): Promise<Execution[]> => {
      const executions = await agentRunService.listExecutions(runId)
      return executions || []
    },
    enabled: Boolean(runId) && options?.enabled !== false,
    staleTime: STALE_TIME.SHORT,
    refetchInterval: 10_000,
  })
}

export function useExecution(executionId: string, options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: agentRunKeys.execution(executionId),
    queryFn: () => agentRunService.getExecution(executionId),
    enabled: Boolean(executionId) && options?.enabled !== false,
    staleTime: STALE_TIME.SHORT,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      if (status && TERMINAL_EXECUTION_STATUSES.includes(status)) return false
      return 10_000
    },
  })
}

export function useExecutionEvents(executionId: string, options?: { enabled?: boolean }) {
  return useQuery<ExecutionEvent[]>({
    queryKey: agentRunKeys.events(executionId),
    queryFn: () => agentRunService.listExecutionEvents(executionId),
    enabled: Boolean(executionId) && options?.enabled !== false,
    staleTime: STALE_TIME.SHORT,
    refetchInterval: 5_000,
  })
}

// ==================== Mutation Hooks ====================

export function useCreateAgentRun() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (data: CreateAgentRunRequest) => {
      return agentRunService.create(data)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: agentRunKeys.all })
    },
  })
}

export function useCancelAgentRun() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (runId: string) => {
      return agentRunService.cancel(runId)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: agentRunKeys.all })
    },
  })
}

export function useRetryAgentRun() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (runId: string) => {
      return agentRunService.retry(runId)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: agentRunKeys.all })
    },
  })
}
