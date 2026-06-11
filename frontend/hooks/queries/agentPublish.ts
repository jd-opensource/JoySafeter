'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { agentPublishService } from '@/services/agentPublishService'
import { agentKeys } from './agents'
import { STALE_TIME } from './constants'

export const publishKeys = {
  all: (agentId: string) => [...agentKeys.all, 'releases', agentId] as const,
  list: (agentId: string, projectId: string) =>
    [...publishKeys.all(agentId), 'list', projectId] as const,
}

export function useReleaseHistory(
  agentId: string,
  projectId: string,
  options?: { enabled?: boolean },
) {
  return useQuery({
    queryKey: publishKeys.list(agentId, projectId),
    queryFn: () => agentPublishService.list(agentId),
    enabled: !!agentId && !!projectId && options?.enabled !== false,
    staleTime: STALE_TIME.STANDARD,
  })
}

export function usePublishAgent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ agentId }: { agentId: string; projectId: string }) =>
      agentPublishService.publish(agentId),
    onSuccess: (_, { agentId, projectId }) => {
      qc.invalidateQueries({ queryKey: publishKeys.all(agentId) })
      qc.invalidateQueries({ queryKey: agentKeys.detail(agentId, projectId) })
    },
  })
}

export function useRollbackAgent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      agentId,
      releaseId,
    }: {
      agentId: string
      releaseId: string
      projectId: string
    }) => agentPublishService.rollback(agentId, releaseId),
    onSuccess: (_, { agentId, projectId }) => {
      qc.invalidateQueries({ queryKey: publishKeys.all(agentId) })
      qc.invalidateQueries({ queryKey: agentKeys.detail(agentId, projectId) })
    },
  })
}

export function useRetireRelease() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      agentId,
      releaseId,
    }: {
      agentId: string
      releaseId: string
      projectId: string
    }) => agentPublishService.retire(agentId, releaseId),
    onSuccess: (_, { agentId, projectId }) => {
      qc.invalidateQueries({ queryKey: publishKeys.all(agentId) })
      qc.invalidateQueries({ queryKey: agentKeys.detail(agentId, projectId) })
    },
  })
}

export function useUnpublishAgent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ agentId }: { agentId: string; projectId: string }) =>
      agentPublishService.unpublish(agentId),
    onSuccess: (_, { agentId, projectId }) => {
      qc.invalidateQueries({ queryKey: publishKeys.all(agentId) })
      qc.invalidateQueries({ queryKey: agentKeys.detail(agentId, projectId) })
    },
  })
}
