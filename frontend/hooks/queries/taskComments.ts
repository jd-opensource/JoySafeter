/**
 * Task Comments Queries
 */
import { useInfiniteQuery, useMutation, useQueryClient } from '@tanstack/react-query'

import { taskCommentService } from '@/services/taskCommentService'
import type { CreateMissionCommentRequest } from '@/types/mission-comments'

import { taskKeys } from './tasks'
import { STALE_TIME } from './constants'

// ==================== Query Keys ====================

export const taskCommentKeys = {
  all: ['taskComments'] as const,
  list: (taskId: string, workspaceId: string) =>
    [...taskCommentKeys.all, 'list', taskId, workspaceId] as const,
}

// ==================== Query Hooks ====================

export function useTaskComments(taskId: string, workspaceId: string) {
  return useInfiniteQuery({
    queryKey: taskCommentKeys.list(taskId, workspaceId),
    queryFn: async ({ pageParam }) => {
      return taskCommentService.list(taskId, workspaceId, {
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

export function useCreateTaskComment() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({
      taskId,
      workspaceId,
      ...data
    }: CreateMissionCommentRequest & { taskId: string; workspaceId: string }) => {
      return taskCommentService.create(taskId, workspaceId, data)
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({
        queryKey: taskCommentKeys.list(variables.taskId, variables.workspaceId),
      })
      queryClient.invalidateQueries({
        queryKey: taskKeys.detail(variables.taskId, variables.workspaceId),
      })
    },
  })
}

export function useDeleteTaskComment() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({
      taskId,
      commentId,
      workspaceId,
    }: {
      taskId: string
      commentId: string
      workspaceId: string
    }) => {
      return taskCommentService.delete(taskId, commentId, workspaceId)
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({
        queryKey: taskCommentKeys.list(variables.taskId, variables.workspaceId),
      })
    },
  })
}
