/**
 * Tasks Queries
 *
 * Follow project standards:
 * - Use camelCase for types
 * - API response: { success: true, data: {...} }
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { taskService } from '@/services/taskService'
import type {
  Task,
  CreateTaskRequest,
  UpdateTaskRequest,
  TaskStatus,
} from '@/types/tasks'
import { TERMINAL_TASK_STATUSES, DEFAULT_MANUAL_TRANSITIONS } from '@/types/tasks'

import { STALE_TIME } from './constants'
import { agentRunKeys } from './agentRuns'

// ==================== Query Keys ====================

export const taskKeys = {
  all: ['tasks'] as const,
  list: (workspaceId: string, filters?: { status?: string; limit?: number; agent_id?: string }) =>
    [
      ...taskKeys.all,
      'list',
      workspaceId,
      filters?.status || '',
      filters?.limit || 50,
      filters?.agent_id || '',
    ] as const,
  detail: (taskId: string, workspaceId: string) =>
    [...taskKeys.all, 'detail', taskId, workspaceId] as const,
  transitions: (workspaceId: string) =>
    [...taskKeys.all, 'meta', 'transitions', workspaceId] as const,
}

// ==================== Query Hooks ====================

export function useTasks(
  workspaceId: string,
  filters?: { status?: string; limit?: number; agent_id?: string },
  options?: { enabled?: boolean },
) {
  return useQuery({
    queryKey: taskKeys.list(workspaceId, filters),
    queryFn: async (): Promise<Task[]> => {
      const tasks = await taskService.list(workspaceId, filters)
      return tasks || []
    },
    enabled: Boolean(workspaceId) && options?.enabled !== false,
    staleTime: STALE_TIME.SHORT,
    refetchInterval: 15_000,
    refetchOnWindowFocus: true,
    placeholderData: keepPreviousData,
  })
}

export function useTask(
  taskId: string,
  workspaceId: string,
  options?: { enabled?: boolean },
) {
  return useQuery({
    queryKey: taskKeys.detail(taskId, workspaceId),
    queryFn: () => taskService.get(taskId, workspaceId),
    enabled: Boolean(taskId) && Boolean(workspaceId) && options?.enabled !== false,
    staleTime: STALE_TIME.SHORT,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      if (status && TERMINAL_TASK_STATUSES.includes(status)) return false
      return 10_000
    },
  })
}

// ==================== Mutation Hooks ====================

export function useCreateTask() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (data: CreateTaskRequest) => {
      return taskService.create(data)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: taskKeys.all })
    },
  })
}

export function useUpdateTask() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({
      taskId,
      workspaceId,
      ...updates
    }: UpdateTaskRequest & { taskId: string; workspaceId: string }) => {
      return taskService.update(taskId, workspaceId, updates)
    },
    onMutate: async (variables) => {
      await queryClient.cancelQueries({ queryKey: taskKeys.all })
      const previous = queryClient.getQueriesData<Task[]>({ queryKey: taskKeys.all })

      const { taskId: _id, workspaceId: _ws, ...updates } = variables

      queryClient.setQueriesData<Task[]>({ queryKey: taskKeys.all }, (old) => {
        if (!old || !Array.isArray(old)) return old
        return old.map((m) =>
          m.id === variables.taskId ? ({ ...m, ...updates } as Task) : m,
        )
      })

      const previousDetail = queryClient.getQueryData<Task>(
        taskKeys.detail(variables.taskId, variables.workspaceId),
      )
      if (previousDetail) {
        queryClient.setQueryData<Task>(
          taskKeys.detail(variables.taskId, variables.workspaceId),
          { ...previousDetail, ...updates } as Task,
        )
      }

      return { previous, previousDetail }
    },
    onError: (_err, variables, context) => {
      if (context?.previous) {
        for (const [key, data] of context.previous) {
          queryClient.setQueryData(key, data)
        }
      }
      if (context?.previousDetail) {
        queryClient.setQueryData(
          taskKeys.detail(variables.taskId, variables.workspaceId),
          context.previousDetail,
        )
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: taskKeys.all })
    },
  })
}

export function useAssignTask() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({
      taskId,
      workspaceId,
      agentId,
    }: {
      taskId: string
      workspaceId: string
      agentId: string
    }) => {
      return taskService.assign(taskId, workspaceId, agentId)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: taskKeys.all })
    },
  })
}

export function useDispatchTask() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ taskId, workspaceId }: { taskId: string; workspaceId: string }) => {
      return taskService.dispatch(taskId, workspaceId)
    },
    onSuccess: (data, variables) => {
      queryClient.setQueryData(taskKeys.detail(variables.taskId, variables.workspaceId), data)
      queryClient.invalidateQueries({ queryKey: taskKeys.all })
      queryClient.invalidateQueries({
        queryKey: agentRunKeys.list({ workspace_id: variables.workspaceId, task_id: variables.taskId }),
      })
    },
  })
}

export function useCancelTask() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ taskId, workspaceId }: { taskId: string; workspaceId: string }) => {
      return taskService.cancel(taskId, workspaceId)
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: taskKeys.all })
      queryClient.invalidateQueries({
        queryKey: agentRunKeys.list({ workspace_id: variables.workspaceId, task_id: variables.taskId }),
      })
    },
  })
}

// ==================== Task Meta ====================

export function useTaskTransitions(workspaceId: string) {
  return useQuery({
    queryKey: taskKeys.transitions(workspaceId),
    queryFn: async (): Promise<Record<TaskStatus, TaskStatus[]>> => {
      const res = await taskService.getTransitions(workspaceId)
      return (res ?? DEFAULT_MANUAL_TRANSITIONS) as Record<TaskStatus, TaskStatus[]>
    },
    enabled: Boolean(workspaceId),
    staleTime: Infinity,
  })
}
