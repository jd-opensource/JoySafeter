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
import {
  apiCollectionPath,
  apiResourceId,
  apiResourcePath,
  apiResourceSubpath,
} from '@/lib/managed/api-paths'
import {
  hasManagedRequestScope,
  type ManagedRequestScope,
  managedRequestOptions,
  useManagedRequestScope,
} from '@/lib/managed/request-scope'

export type ScheduleConcurrencyPolicy = 'allow' | 'forbid' | 'replace'
export type ScheduleSessionMode = 'fresh' | 'reuse' | 'pinned'

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
  session_mode: ScheduleSessionMode
  pinned_session_id: string | null
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
  session_mode?: ScheduleSessionMode
  pinned_session_id?: string | null
  enabled?: boolean
}

type ScheduleCreateInput = ScheduleCreate & { requestScope?: ManagedRequestScope }

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
    | 'session_mode'
    | 'pinned_session_id'
    | 'enabled'
  >
>

type ScheduleUpdateInput = { id: string; body: ScheduleUpdate; requestScope?: ManagedRequestScope }

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

export function useSchedules(params?: { enabled?: boolean }) {
  const scope = useManagedRequestScope()
  const path = apiCollectionPath('schedules', { enabled: params?.enabled })
  return useQuery({
    queryKey: ['schedules', scope.key, path],
    queryFn: () => managedGet<Schedule[]>(path, managedRequestOptions(scope)),
    enabled: hasManagedRequestScope(scope),
  })
}

export function useSchedule(scheduleId: string | undefined) {
  const scope = useManagedRequestScope()
  return useQuery({
    queryKey: ['schedule', scope.key, scheduleId],
    queryFn: () =>
      managedGet<Schedule>(apiResourcePath('schedules', scheduleId), managedRequestOptions(scope)),
    enabled: !!scheduleId && hasManagedRequestScope(scope),
  })
}

export function useScheduleRuns(scheduleId: string | undefined, limit = 50) {
  const scope = useManagedRequestScope()
  return useQuery({
    queryKey: ['schedule-runs', scope.key, scheduleId, limit],
    queryFn: () =>
      managedGet<ScheduleRun[]>(
        apiResourceSubpath('schedules', scheduleId, ['runs'], { limit }),
        managedRequestOptions(scope),
      ),
    enabled: !!scheduleId && hasManagedRequestScope(scope),
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
  const scope = useManagedRequestScope()
  return useMutation({
    mutationFn: (input: ScheduleCreateInput) => {
      const { requestScope = scope, ...body } = input
      return managedPost<Schedule>(
        apiCollectionPath('schedules'),
        {
          ...body,
          agent_id: apiResourceId(body.agent_id),
        },
        managedRequestOptions(requestScope),
      )
    },
    onSuccess: (_data, input) =>
      qc.invalidateQueries({ queryKey: ['schedules', (input.requestScope ?? scope).key] }),
  })
}

export function useUpdateSchedule() {
  const qc = useQueryClient()
  const scope = useManagedRequestScope()
  return useMutation({
    mutationFn: ({ id, body, requestScope = scope }: ScheduleUpdateInput) =>
      managedPatch<Schedule>(
        apiResourcePath('schedules', id),
        body,
        managedRequestOptions(requestScope),
      ),
    onSuccess: (_data, { id, requestScope }) => {
      const scopeKey = (requestScope ?? scope).key
      qc.invalidateQueries({ queryKey: ['schedules', scopeKey] })
      qc.invalidateQueries({ queryKey: ['schedule', scopeKey, id] })
    },
  })
}

export function useToggleSchedule() {
  const qc = useQueryClient()
  const scope = useManagedRequestScope()
  return useMutation({
    mutationFn: ({
      id,
      enabled,
      requestScope = scope,
    }: {
      id: string
      enabled: boolean
      requestScope?: ManagedRequestScope
    }) =>
      managedPost<Schedule>(
        apiResourcePath('schedules', id, enabled ? 'enable' : 'disable'),
        {},
        managedRequestOptions(requestScope),
      ),
    // Optimistically flip the toggled row so only that switch reacts instantly;
    // other rows stay interactive (no global pending disable). Rolls back on
    // error, and reconciles with the server on settle (next_run_at recompute).
    onMutate: async ({ id, enabled, requestScope }) => {
      const scopeKey = (requestScope ?? scope).key
      await qc.cancelQueries({ queryKey: ['schedules', scopeKey] })
      const snapshots = qc.getQueriesData<Schedule[]>({ queryKey: ['schedules', scopeKey] })
      for (const [key, list] of snapshots) {
        if (!list) continue
        qc.setQueryData<Schedule[]>(
          key,
          list.map((s) => (apiResourceId(s.id) === apiResourceId(id) ? { ...s, enabled } : s)),
        )
      }
      return { snapshots }
    },
    onError: (_err, _vars, context) => {
      for (const [key, list] of context?.snapshots ?? []) {
        qc.setQueryData(key, list)
      }
    },
    onSettled: (_data, _error, vars) =>
      qc.invalidateQueries({ queryKey: ['schedules', (vars.requestScope ?? scope).key] }),
  })
}

export function useTriggerSchedule() {
  const qc = useQueryClient()
  const scope = useManagedRequestScope()
  return useMutation({
    mutationFn: (input: string | { id: string; requestScope?: ManagedRequestScope }) => {
      const id = typeof input === 'string' ? input : input.id
      const requestScope = typeof input === 'string' ? scope : (input.requestScope ?? scope)
      return managedPost<TriggerResult>(
        apiResourcePath('schedules', id, 'trigger'),
        {},
        managedRequestOptions(requestScope),
      )
    },
    onSuccess: (_data, input) => {
      const id = typeof input === 'string' ? input : input.id
      const requestScope = typeof input === 'string' ? scope : (input.requestScope ?? scope)
      qc.invalidateQueries({ queryKey: ['schedule-runs', requestScope.key, id] })
    },
  })
}

export function useDeleteSchedule() {
  const qc = useQueryClient()
  const scope = useManagedRequestScope()
  return useMutation({
    mutationFn: (input: string | { id: string; requestScope?: ManagedRequestScope }) => {
      const id = typeof input === 'string' ? input : input.id
      const requestScope = typeof input === 'string' ? scope : (input.requestScope ?? scope)
      return managedDelete<void>(
        apiResourcePath('schedules', id),
        managedRequestOptions(requestScope),
      )
    },
    onSuccess: (_data, input) => {
      const requestScope = typeof input === 'string' ? scope : (input.requestScope ?? scope)
      qc.invalidateQueries({ queryKey: ['schedules', requestScope.key] })
    },
  })
}
