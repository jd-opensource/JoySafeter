'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { agentPublishService } from '@/services/agentPublishService'
import { agentKeys } from './agents'
import { STALE_TIME } from './constants'

export const publishKeys = {
  all: (agentId: string) => [...agentKeys.all, 'releases', agentId] as const,
  list: (agentId: string, workspaceId: string) =>
    [...publishKeys.all(agentId), 'list', workspaceId] as const,
}

export function useReleaseHistory(agentId: string, workspaceId: string) {
  return useQuery({
    queryKey: publishKeys.list(agentId, workspaceId),
    queryFn: () => agentPublishService.list(agentId, workspaceId),
    enabled: !!agentId && !!workspaceId,
    staleTime: STALE_TIME.STANDARD,
  })
}

export function usePublishAgent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ agentId, workspaceId }: { agentId: string; workspaceId: string }) =>
      agentPublishService.publish(agentId, workspaceId),
    onSuccess: (_, { agentId, workspaceId }) => {
      qc.invalidateQueries({ queryKey: publishKeys.all(agentId) })
      qc.invalidateQueries({ queryKey: agentKeys.detail(agentId, workspaceId) })
    },
  })
}

export function useRollbackAgent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      agentId,
      releaseId,
      workspaceId,
    }: {
      agentId: string
      releaseId: string
      workspaceId: string
    }) => agentPublishService.rollback(agentId, releaseId, workspaceId),
    onSuccess: (_, { agentId, workspaceId }) => {
      qc.invalidateQueries({ queryKey: publishKeys.all(agentId) })
      qc.invalidateQueries({ queryKey: agentKeys.detail(agentId, workspaceId) })
    },
  })
}

export function useRetireRelease() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      agentId,
      releaseId,
      workspaceId,
    }: {
      agentId: string
      releaseId: string
      workspaceId: string
    }) => agentPublishService.retire(agentId, releaseId, workspaceId),
    onSuccess: (_, { agentId, workspaceId }) => {
      qc.invalidateQueries({ queryKey: publishKeys.all(agentId) })
      qc.invalidateQueries({ queryKey: agentKeys.detail(agentId, workspaceId) })
    },
  })
}
