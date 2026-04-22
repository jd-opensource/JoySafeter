/**
 * Thread Queries
 *
 * React Query hooks for Thread and ThreadMessage entities.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { threadService } from '@/services/threadService'
import type {
  CreateMessageRequest,
  CreateThreadRequest,
  UpdateThreadRequest,
} from '@/types/thread'

import { STALE_TIME } from './constants'

// ==================== Query Keys ====================

export const threadKeys = {
  all: ['threads'] as const,
  list: (agentId: string, workspaceId: string) =>
    [...threadKeys.all, 'list', agentId, workspaceId] as const,
  detail: (threadId: string, workspaceId: string) =>
    [...threadKeys.all, 'detail', threadId, workspaceId] as const,
  messages: (threadId: string, workspaceId: string) =>
    [...threadKeys.all, 'messages', threadId, workspaceId] as const,
}

// ==================== Query Hooks ====================

export function useThreads(
  agentId: string,
  workspaceId: string,
  options?: { enabled?: boolean },
) {
  return useQuery({
    queryKey: threadKeys.list(agentId, workspaceId),
    queryFn: () => threadService.list(agentId, workspaceId),
    enabled:
      Boolean(agentId) && Boolean(workspaceId) && options?.enabled !== false,
    staleTime: STALE_TIME.SHORT,
    refetchOnWindowFocus: true,
    placeholderData: keepPreviousData,
  })
}

export function useThread(
  threadId: string,
  workspaceId: string,
  options?: { enabled?: boolean },
) {
  return useQuery({
    queryKey: threadKeys.detail(threadId, workspaceId),
    queryFn: () => threadService.get(threadId, workspaceId),
    enabled:
      Boolean(threadId) && Boolean(workspaceId) && options?.enabled !== false,
    staleTime: STALE_TIME.SHORT,
  })
}

export function useThreadMessages(
  threadId: string,
  workspaceId: string,
  options?: { enabled?: boolean },
) {
  return useQuery({
    queryKey: threadKeys.messages(threadId, workspaceId),
    queryFn: () => threadService.listMessages(threadId, workspaceId),
    enabled:
      Boolean(threadId) && Boolean(workspaceId) && options?.enabled !== false,
    staleTime: STALE_TIME.SHORT,
  })
}

// ==================== Mutation Hooks ====================

export function useCreateThread() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: CreateThreadRequest & { workspace_id: string }) =>
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
      workspaceId,
      ...updates
    }: UpdateThreadRequest & { threadId: string; workspaceId: string }) =>
      threadService.update(threadId, workspaceId, updates),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: threadKeys.all })
    },
  })
}

export function useArchiveThread() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({
      threadId,
      workspaceId,
    }: {
      threadId: string
      workspaceId: string
    }) => threadService.archive(threadId, workspaceId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: threadKeys.all })
    },
  })
}

export function useCreateMessage() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({
      threadId,
      workspaceId,
      ...data
    }: CreateMessageRequest & { threadId: string; workspaceId: string }) =>
      threadService.createMessage(threadId, workspaceId, data),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({
        queryKey: threadKeys.detail(variables.threadId, variables.workspaceId),
      })
      queryClient.invalidateQueries({
        queryKey: threadKeys.messages(
          variables.threadId,
          variables.workspaceId,
        ),
      })
    },
  })
}
