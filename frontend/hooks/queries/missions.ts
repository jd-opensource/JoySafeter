/**
 * Missions Queries
 *
 * Follow project standards:
 * - Use camelCase for types
 * - API response: { success: true, data: {...} }
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { missionService } from '@/services/missionService'
import type { Mission, CreateMissionRequest, UpdateMissionRequest, MissionStatus } from '@/types/missions'
import { TERMINAL_MISSION_STATUSES, DEFAULT_MANUAL_TRANSITIONS } from '@/types/missions'

import { STALE_TIME } from './constants'
import { executionKeys } from './executions'

// ==================== Query Keys ====================

export const missionKeys = {
  all: ['missions'] as const,
  list: (workspaceId: string, filters?: { status?: string; limit?: number }) =>
    [...missionKeys.all, 'list', workspaceId, filters?.status || '', filters?.limit || 50] as const,
  detail: (missionId: string, workspaceId: string) =>
    [...missionKeys.all, 'detail', missionId, workspaceId] as const,
  transitions: (workspaceId: string) =>
    [...missionKeys.all, 'meta', 'transitions', workspaceId] as const,
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
    refetchInterval: 15_000,
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
    refetchInterval: (query) => {
      const status = query.state.data?.status
      if (status && TERMINAL_MISSION_STATUSES.includes(status)) return false
      return 10_000
    },
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
    onMutate: async (variables) => {
      await queryClient.cancelQueries({ queryKey: missionKeys.all })
      const previous = queryClient.getQueriesData<Mission[]>({ queryKey: missionKeys.all })

      queryClient.setQueriesData<Mission[]>({ queryKey: missionKeys.all }, (old) => {
        if (!old || !Array.isArray(old)) return old
        const { missionId: _id, workspaceId: _ws, ...updates } = variables
        return old.map((m) =>
          m.id === variables.missionId ? ({ ...m, ...updates } as Mission) : m,
        )
      })

      return { previous }
    },
    onError: (_err, _vars, context) => {
      if (context?.previous) {
        for (const [key, data] of context.previous) {
          queryClient.setQueryData(key, data)
        }
      }
    },
    onSettled: () => {
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
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: missionKeys.all })
      queryClient.invalidateQueries({
        queryKey: executionKeys.list(variables.workspaceId, { mission_id: variables.missionId }),
      })
    },
  })
}

export function useCancelMission() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ missionId, workspaceId }: { missionId: string; workspaceId: string }) => {
      return missionService.cancel(missionId, workspaceId)
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: missionKeys.all })
      queryClient.invalidateQueries({
        queryKey: executionKeys.list(variables.workspaceId, { mission_id: variables.missionId }),
      })
    },
  })
}

// ==================== Mission Meta ====================

export function useMissionTransitions(workspaceId: string) {
  return useQuery({
    queryKey: missionKeys.transitions(workspaceId),
    queryFn: async (): Promise<Record<MissionStatus, MissionStatus[]>> => {
      const res = await missionService.getTransitions(workspaceId)
      return (res ?? DEFAULT_MANUAL_TRANSITIONS) as Record<MissionStatus, MissionStatus[]>
    },
    enabled: Boolean(workspaceId),
    staleTime: Infinity,
  })
}
