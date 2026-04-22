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
  list: (taskId: string, workspaceId: string) =>
    [...taskActivityKeys.all, 'list', taskId, workspaceId] as const,
}

// ==================== Query Hooks ====================

export function useTaskActivities(taskId: string, workspaceId: string) {
  return useInfiniteQuery({
    queryKey: taskActivityKeys.list(taskId, workspaceId),
    queryFn: async ({ pageParam }) => {
      return taskActivityService.list(taskId, workspaceId, {
        cursor: pageParam ?? undefined,
        limit: 50,
      })
    },
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => (lastPage.has_more ? lastPage.next_cursor : undefined),
    enabled: Boolean(taskId) && Boolean(workspaceId),
    staleTime: STALE_TIME.SHORT,
  })
}

// ==================== Mutation Hooks ====================

export function useCreateTaskActivity() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({
      taskId,
      workspaceId,
      ...data
    }: CreateTaskActivityRequest & { taskId: string; workspaceId: string }) => {
      return taskActivityService.create(taskId, workspaceId, data)
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({
        queryKey: taskActivityKeys.list(variables.taskId, variables.workspaceId),
      })
      queryClient.invalidateQueries({
        queryKey: taskKeys.detail(variables.taskId, variables.workspaceId),
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
      workspaceId,
    }: {
      taskId: string
      activityId: string
      workspaceId: string
    }) => {
      return taskActivityService.delete(taskId, activityId, workspaceId)
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({
        queryKey: taskActivityKeys.list(variables.taskId, variables.workspaceId),
      })
    },
  })
}
