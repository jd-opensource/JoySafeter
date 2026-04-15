/**
 * Missions Queries
 *
 * Follow project standards:
 * - Use camelCase for types
 * - API response: { success: true, data: {...} }
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { missionService } from '@/services/missionService'
import type { Mission, CreateMissionRequest, UpdateMissionRequest } from '@/types/missions'

import { STALE_TIME } from './constants'

// ==================== Query Keys ====================

export const missionKeys = {
  all: ['missions'] as const,
  list: (workspaceId: string, filters?: { status?: string; limit?: number }) =>
    [...missionKeys.all, 'list', workspaceId, filters?.status || '', filters?.limit || 50] as const,
  detail: (missionId: string, workspaceId: string) =>
    [...missionKeys.all, 'detail', missionId, workspaceId] as const,
}

// ==================== Query Hooks ====================

export function useMissions(
  workspaceId: string,
  filters?: { status?: string; limit?: number },
  options?: { enabled?: boolean },
) {
  return useQuery({
    queryKey: missionKeys.list(workspaceId, filters),
    queryFn: async (): Promise<Mission[]> => {
      const missions = await missionService.list(workspaceId, filters)
      return missions || []
    },
    enabled: Boolean(workspaceId) && options?.enabled !== false,
    staleTime: STALE_TIME.SHORT,
    refetchOnWindowFocus: true,
    placeholderData: keepPreviousData,
  })
}

export function useMission(
  missionId: string,
  workspaceId: string,
  options?: { enabled?: boolean },
) {
  return useQuery({
    queryKey: missionKeys.detail(missionId, workspaceId),
    queryFn: () => missionService.get(missionId, workspaceId),
    enabled: Boolean(missionId) && Boolean(workspaceId) && options?.enabled !== false,
    staleTime: STALE_TIME.SHORT,
  })
}

// ==================== Mutation Hooks ====================

export function useCreateMission() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (data: CreateMissionRequest) => {
      return missionService.create(data)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: missionKeys.all })
    },
  })
}

export function useUpdateMission() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({
      missionId,
      workspaceId,
      ...updates
    }: UpdateMissionRequest & { missionId: string; workspaceId: string }) => {
      return missionService.update(missionId, workspaceId, updates)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: missionKeys.all })
    },
  })
}

export function useAssignMission() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({
      missionId,
      workspaceId,
      agentProfileId,
    }: {
      missionId: string
      workspaceId: string
      agentProfileId: string
    }) => {
      return missionService.assign(missionId, workspaceId, agentProfileId)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: missionKeys.all })
    },
  })
}

export function useDispatchMission() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ missionId, workspaceId }: { missionId: string; workspaceId: string }) => {
      return missionService.dispatch(missionId, workspaceId)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: missionKeys.all })
    },
  })
}

export function useCancelMission() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ missionId, workspaceId }: { missionId: string; workspaceId: string }) => {
      return missionService.cancel(missionId, workspaceId)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: missionKeys.all })
    },
  })
}
