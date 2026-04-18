/**
 * Mission Comments Queries
 */
import { useInfiniteQuery, useMutation, useQueryClient } from '@tanstack/react-query'

import { missionCommentService } from '@/services/missionCommentService'
import type { CreateMissionCommentRequest } from '@/types/mission-comments'

import { missionKeys } from './missions'
import { STALE_TIME } from './constants'

// ==================== Query Keys ====================

export const missionCommentKeys = {
  all: ['missionComments'] as const,
  list: (missionId: string, workspaceId: string) =>
    [...missionCommentKeys.all, 'list', missionId, workspaceId] as const,
}

// ==================== Query Hooks ====================

export function useMissionComments(missionId: string, workspaceId: string) {
  return useInfiniteQuery({
    queryKey: missionCommentKeys.list(missionId, workspaceId),
    queryFn: async ({ pageParam }) => {
      return missionCommentService.list(missionId, workspaceId, {
        cursor: pageParam ?? undefined,
        limit: 50,
      })
    },
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? lastPage.next_cursor : undefined,
    enabled: Boolean(missionId) && Boolean(workspaceId),
    staleTime: STALE_TIME.SHORT,
  })
}

// ==================== Mutation Hooks ====================

export function useCreateMissionComment() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({
      missionId,
      workspaceId,
      ...data
    }: CreateMissionCommentRequest & { missionId: string; workspaceId: string }) => {
      return missionCommentService.create(missionId, workspaceId, data)
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({
        queryKey: missionCommentKeys.list(variables.missionId, variables.workspaceId),
      })
      queryClient.invalidateQueries({
        queryKey: missionKeys.detail(variables.missionId, variables.workspaceId),
      })
    },
  })
}

export function useDeleteMissionComment() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({
      missionId,
      commentId,
      workspaceId,
    }: {
      missionId: string
      commentId: string
      workspaceId: string
    }) => {
      return missionCommentService.delete(missionId, commentId, workspaceId)
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({
        queryKey: missionCommentKeys.list(variables.missionId, variables.workspaceId),
      })
    },
  })
}
