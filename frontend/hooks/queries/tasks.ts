/**
 * Tasks Queries
 *
 * Follow project standards:
 * - Use camelCase for types
 * - API response: { success: true, data: {...} }
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { taskService } from '@/services/taskService'
import type { Task, CreateTaskRequest, UpdateTaskRequest, TaskStatus } from '@/types/tasks'
import { INACTIVE_TASK_STATUSES, DEFAULT_MANUAL_TRANSITIONS } from '@/types/tasks'

import { STALE_TIME } from './constants'
import { agentRunKeys } from './agentRuns'

// ==================== Query Keys ====================

export const taskKeys = {
  all: ['tasks'] as const,
  list: (projectId: string, filters?: { status?: string; limit?: number; agent_id?: string }) =>
    [
      ...taskKeys.all,
      'list',
      projectId,
      filters?.status || '',
      filters?.limit || 50,
      filters?.agent_id || '',
    ] as const,
  detail: (taskId: string, projectId: string) =>
    [...taskKeys.all, 'detail', taskId, projectId] as const,
  transitions: (projectId: string) =>
    [...taskKeys.all, 'meta', 'transitions', projectId] as const,
}

// ==================== Query Hooks ====================

export function useTasks(
  projectId: string,
  filters?: { status?: string; limit?: number; agent_id?: string },
  options?: { enabled?: boolean },
) {
  return useQuery({
    queryKey: taskKeys.list(projectId, filters),
    queryFn: async (): Promise<Task[]> => {
      const tasks = await taskService.list(filters)
      return tasks || []
    },
    enabled: Boolean(projectId) && options?.enabled !== false,
    staleTime: STALE_TIME.SHORT,
    refetchInterval: 15_000,
    refetchOnWindowFocus: true,
    placeholderData: keepPreviousData,
  })
}

export function useTask(taskId: string, projectId: string, options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: taskKeys.detail(taskId, projectId),
    queryFn: () => taskService.get(taskId),
    enabled: Boolean(taskId) && Boolean(projectId) && options?.enabled !== false,
    staleTime: STALE_TIME.SHORT,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      if (status && INACTIVE_TASK_STATUSES.includes(status)) return false
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
      projectId,
      ...updates
    }: UpdateTaskRequest & { taskId: string; projectId: string }) => {
      return taskService.update(taskId, updates)
    },
    onMutate: async (variables) => {
      await queryClient.cancelQueries({ queryKey: taskKeys.all })
      const previous = queryClient.getQueriesData<Task[]>({ queryKey: taskKeys.all })

      const { taskId: _id, projectId: _p, ...updates } = variables

      queryClient.setQueriesData<Task[]>({ queryKey: taskKeys.all }, (old) => {
        if (!old || !Array.isArray(old)) return old
        return old.map((m) => (m.id === variables.taskId ? ({ ...m, ...updates } as Task) : m))
      })

      const previousDetail = queryClient.getQueryData<Task>(
        taskKeys.detail(variables.taskId, variables.projectId),
      )
      if (previousDetail) {
        queryClient.setQueryData<Task>(taskKeys.detail(variables.taskId, variables.projectId), {
          ...previousDetail,
          ...updates,
        } as Task)
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
          taskKeys.detail(variables.taskId, variables.projectId),
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
      agentId,
    }: {
      taskId: string
      agentId: string
    }) => {
      return taskService.assign(taskId, agentId)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: taskKeys.all })
    },
  })
}

export function useDispatchTask() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ taskId, projectId }: { taskId: string; projectId: string }) => {
      return taskService.dispatch(taskId)
    },
    onSuccess: (data, variables) => {
      queryClient.setQueryData(taskKeys.detail(variables.taskId, variables.projectId), data)
      queryClient.invalidateQueries({ queryKey: taskKeys.all })
      queryClient.invalidateQueries({
        queryKey: agentRunKeys.list({
          task_id: variables.taskId,
        }),
      })
    },
  })
}

export function useCancelTask() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ taskId, projectId }: { taskId: string; projectId: string }) => {
      return taskService.cancel(taskId)
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: taskKeys.all })
      queryClient.invalidateQueries({
        queryKey: agentRunKeys.list({
          task_id: variables.taskId,
        }),
      })
    },
  })
}

// ==================== Task Meta ====================

export function useTaskTransitions(projectId: string) {
  return useQuery({
    queryKey: taskKeys.transitions(projectId),
    queryFn: async (): Promise<Record<TaskStatus, TaskStatus[]>> => {
      const res = await taskService.getTransitions()
      return (res ?? DEFAULT_MANUAL_TRANSITIONS) as Record<TaskStatus, TaskStatus[]>
    },
    enabled: Boolean(projectId),
    staleTime: Infinity,
  })
}
