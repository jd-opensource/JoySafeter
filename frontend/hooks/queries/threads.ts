/**
 * Thread Queries
 *
 * React Query hooks for Thread entities.
 * Message-related hooks removed — messages are now execution events.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { threadService } from '@/services/threadService'
import type { CreateThreadRequest, UpdateThreadRequest } from '@/types/thread'

import { STALE_TIME } from './constants'

// ==================== Query Keys ====================

export const threadKeys = {
  all: ['threads'] as const,
  list: (agentId: string, projectId: string) =>
    [...threadKeys.all, 'list', agentId, projectId] as const,
  detail: (threadId: string, projectId: string) =>
    [...threadKeys.all, 'detail', threadId, projectId] as const,
}

// ==================== Query Hooks ====================

export function useThreads(agentId: string, projectId: string, options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: threadKeys.list(agentId, projectId),
    queryFn: () => threadService.list(agentId),
    enabled: Boolean(agentId) && Boolean(projectId) && options?.enabled !== false,
    staleTime: STALE_TIME.SHORT,
    refetchOnWindowFocus: true,
    placeholderData: keepPreviousData,
  })
}

export function useThread(threadId: string, projectId: string, options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: threadKeys.detail(threadId, projectId),
    queryFn: () => threadService.get(threadId),
    enabled: Boolean(threadId) && Boolean(projectId) && options?.enabled !== false,
    staleTime: STALE_TIME.SHORT,
  })
}

// ==================== Mutation Hooks ====================

export function useCreateThread() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: CreateThreadRequest) =>
      threadService.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: threadKeys.all })
    },
  })
}

export function useUpdateThread() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({
      threadId,
      ...updates
    }: UpdateThreadRequest & { threadId: string }) =>
      threadService.update(threadId, updates),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: threadKeys.all })
    },
  })
}

export function useArchiveThread() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ threadId }: { threadId: string }) =>
      threadService.archive(threadId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: threadKeys.all })
    },
  })
}
