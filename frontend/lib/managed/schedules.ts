'use client'

/**
 * Schedules API module: types + React Query hooks over the /schedules surface.
 *
 * Mirrors the backend schemas in
 * `app/joysafeter_domain/schemas/joysafeter_schedule.py`. All requests go
 * through the unified managed API client (project-scoped, CSRF, auto-refresh).
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { managedDelete, managedGet, managedPatch, managedPost } from '@/lib/api-client'
import { stripIdPrefix } from '@/lib/managed/id'
import { useProjectStore } from '@/stores/managed/project-store'

export type ScheduleConcurrencyPolicy = 'allow' | 'forbid' | 'replace'

export interface Schedule {
  id: string
  name: string
  description: string | null
  agent_id: string
  prompt: string
  system_prompt: string | null
  environment_ref: string | null
  cron_expr: string
  timezone: string
  enabled: boolean
  concurrency_policy: ScheduleConcurrencyPolicy
  timeout_sec: number
  max_retries: number
  next_run_at: string | null
  last_fired_slot: string | null
  project_id: string | null
  created_at: string
  updated_at: string
}

export interface ScheduleCreate {
  name: string
  agent_id: string
  prompt: string
  cron_expr: string
  timezone?: string
  system_prompt?: string | null
  environment_ref?: string | null
  description?: string | null
  timeout_sec?: number
  max_retries?: number
  concurrency_policy?: ScheduleConcurrencyPolicy
  enabled?: boolean
}

export type ScheduleUpdate = Partial<
  Pick<
    ScheduleCreate,
    | 'name'
    | 'prompt'
    | 'cron_expr'
    | 'timezone'
    | 'system_prompt'
    | 'environment_ref'
    | 'description'
    | 'timeout_sec'
    | 'max_retries'
    | 'concurrency_policy'
    | 'enabled'
  >
>

export interface ScheduleRun {
  id: string
  schedule_id: string | null
  status: string
  retry_count: number
  max_retries: number
  chat_session_id: string | null
  error: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
}

export interface TriggerResult {
  task_id: string
  session_id: string
  status: string
}

/** Run statuses that are still in flight — used to drive live polling. */
const ACTIVE_RUN_STATUSES = new Set(['pending', 'scheduling', 'running'])

/** React Query key namespace, scoped to the active org+project. */
function useScope(): string {
  const orgId = useProjectStore((s) => s.currentOrgId)
  const projectId = useProjectStore((s) => s.currentProjectId)
  return `${orgId ?? ''}:${projectId ?? ''}`
}

export function useSchedules(params?: { enabled?: boolean }) {
  const scope = useScope()
  const query = new URLSearchParams()
  if (params?.enabled !== undefined) query.set('enabled', String(params.enabled))
  const suffix = query.toString() ? `?${query.toString()}` : ''
  return useQuery({
    queryKey: ['schedules', scope, suffix],
    queryFn: () => managedGet<Schedule[]>(`/schedules${suffix}`),
  })
}

export function useSchedule(scheduleId: string | undefined) {
  const scope = useScope()
  return useQuery({
    queryKey: ['schedule', scope, scheduleId],
    queryFn: () => managedGet<Schedule>(`/schedules/${scheduleId}`),
    enabled: !!scheduleId,
  })
}

export function useScheduleRuns(scheduleId: string | undefined, limit = 50) {
  const scope = useScope()
  return useQuery({
    queryKey: ['schedule-runs', scope, scheduleId, limit],
    queryFn: () => managedGet<ScheduleRun[]>(`/schedules/${scheduleId}/runs?limit=${limit}`),
    enabled: !!scheduleId,
    // Poll only while a run is still in flight, so a just-triggered run advances
    // to its terminal state in the UI without a manual refresh. Idle when all
    // runs are terminal (returns false → no polling).
    refetchInterval: (query) => {
      const runs = query.state.data ?? []
      return runs.some((r) => ACTIVE_RUN_STATUSES.has(r.status)) ? 5000 : false
    },
  })
}

export function useCreateSchedule() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: ScheduleCreate) => managedPost<Schedule>('/schedules', body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['schedules'] }),
  })
}

export function useUpdateSchedule() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: ScheduleUpdate }) =>
      managedPatch<Schedule>(`/schedules/${id}`, body),
    onSuccess: (_data, { id }) => {
      qc.invalidateQueries({ queryKey: ['schedules'] })
      qc.invalidateQueries({ queryKey: ['schedule'] })
      void id
    },
  })
}

export function useToggleSchedule() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      managedPost<Schedule>(`/schedules/${id}/${enabled ? 'enable' : 'disable'}`, {}),
    // Optimistically flip the toggled row so only that switch reacts instantly;
    // other rows stay interactive (no global pending disable). Rolls back on
    // error, and reconciles with the server on settle (next_run_at recompute).
    onMutate: async ({ id, enabled }) => {
      await qc.cancelQueries({ queryKey: ['schedules'] })
      const snapshots = qc.getQueriesData<Schedule[]>({ queryKey: ['schedules'] })
      for (const [key, list] of snapshots) {
        if (!list) continue
        qc.setQueryData<Schedule[]>(
          key,
          list.map((s) => (stripIdPrefix(s.id) === id ? { ...s, enabled } : s)),
        )
      }
      return { snapshots }
    },
    onError: (_err, _vars, context) => {
      for (const [key, list] of context?.snapshots ?? []) {
        qc.setQueryData(key, list)
      }
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ['schedules'] }),
  })
}

export function useTriggerSchedule() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => managedPost<TriggerResult>(`/schedules/${id}/trigger`, {}),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: ['schedule-runs'] })
      void id
    },
  })
}

export function useDeleteSchedule() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => managedDelete<void>(`/schedules/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['schedules'] }),
  })
}
