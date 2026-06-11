/**
 * Task Activities Queries
 */
import { useInfiniteQuery, useMutation, useQueryClient } from '@tanstack/react-query'

import { taskActivityService } from '@/services/taskActivityService'
import type { CreateTaskActivityRequest } from '@/types/task-activities'

import { taskKeys } from './tasks'
import { STALE_TIME } from './constants'

// ==================== Query Keys ====================

export const taskActivityKeys = {
  all: ['taskActivities'] as const,
  list: (taskId: string, projectId: string) =>
    [...taskActivityKeys.all, 'list', taskId, projectId] as const,
}

// ==================== Query Hooks ====================

export function useTaskActivities(taskId: string, projectId: string) {
  return useInfiniteQuery({
    queryKey: taskActivityKeys.list(taskId, projectId),
    queryFn: async ({ pageParam }) => {
      return taskActivityService.list(taskId, {
        cursor: pageParam ?? undefined,
        limit: 50,
      })
    },
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => (lastPage.has_more ? lastPage.next_cursor : undefined),
    enabled: Boolean(taskId) && Boolean(projectId),
    staleTime: STALE_TIME.SHORT,
  })
}

// ==================== Mutation Hooks ====================

export function useCreateTaskActivity() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({
      taskId,
      projectId,
      ...data
    }: CreateTaskActivityRequest & { taskId: string; projectId: string }) => {
      return taskActivityService.create(taskId, data)
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({
        queryKey: taskActivityKeys.list(variables.taskId, variables.projectId),
      })
      queryClient.invalidateQueries({
        queryKey: taskKeys.detail(variables.taskId, variables.projectId),
      })
    },
  })
}

export function useDeleteTaskActivity() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({
      taskId,
      activityId,
      projectId,
    }: {
      taskId: string
      activityId: string
      projectId: string
    }) => {
      return taskActivityService.delete(taskId, activityId)
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({
        queryKey: taskActivityKeys.list(variables.taskId, variables.projectId),
      })
    },
  })
}
