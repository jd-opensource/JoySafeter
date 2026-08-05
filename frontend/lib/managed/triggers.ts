'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { managedDelete, managedGet, managedPatch, managedPost } from '@/lib/api-client'
import { usePaginatedList } from '@/hooks/managed/use-paginated-list'
import { apiCollectionPath, apiResourceId, apiResourcePath } from '@/lib/managed/api-paths'
import {
  hasManagedRequestScope,
  managedRequestOptions,
  useManagedRequestScope,
} from '@/lib/managed/request-scope'

export type TriggerType = 'cron' | 'webhook' | 'manual'
export type TriggerSessionMode = 'fresh' | 'reuse' | 'pinned' | 'keyed'
export type TriggerConcurrencyPolicy = 'allow' | 'forbid' | 'replace'
export type WebhookAuthMethod = 'hmac' | 'bearer' | 'token'

export interface AgentTrigger {
  id: string
  name: string
  description: string | null
  type: TriggerType
  agent_id: string
  prompt_template: string
  system_prompt: string | null
  environment_ref: string | null
  enabled: boolean
  session_mode: TriggerSessionMode
  pinned_session_id: string | null
  reusable_session_id: string | null
  session_key: string | null
  filter: Record<string, unknown>
  timeout_sec: number
  max_retries: number
  cron_expr?: string | null
  timezone?: string | null
  run_at?: string | null
  concurrency_policy?: TriggerConcurrencyPolicy | null
  next_run_at?: string | null
  last_fired_slot?: string | null
  secret_ref?: string | null
  secret_key?: string | null
  config?: Record<string, unknown>
  project_id: string | null
  webhook_url: string | null
  last_attempt_at: string | null
  last_success_at: string | null
  last_error: string | null
  consecutive_failures: number
  auto_disabled_at?: string | null
  disabled_reason?: string | null
  last_task_id: string | null
  last_session_id: string | null
  last_payload: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface AgentTriggerCreate {
  name: string
  type?: TriggerType
  agent_id: string
  prompt_template: string
  secret_ref?: string | null
  secret_key?: string | null
  environment_ref?: string | null
  description?: string | null
  enabled?: boolean
  session_mode?: TriggerSessionMode
  pinned_session_id?: string | null
  session_key?: string | null
  filter?: Record<string, unknown>
  timeout_sec?: number
  max_retries?: number
  cron_expr?: string | null
  timezone?: string | null
  run_at?: string | null
  concurrency_policy?: TriggerConcurrencyPolicy | null
  auth_methods?: WebhookAuthMethod[]
  dedupe_header?: string | null
}

export type AgentTriggerUpdate = Partial<Omit<AgentTriggerCreate, 'type' | 'agent_id'>>

/** A single execution row for a trigger (`/triggers/{id}/runs`). */
export interface TriggerRun {
  id: string
  trigger_id: string | null
  status: string
  retry_count: number
  max_retries: number
  chat_session_id: string | null
  error: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
}

/** Result of a manual run / test-fire. */
export interface TriggerFireResult {
  status: string
  task_id: string | null
  session_id: string | null
  reason?: string | null
  deduped?: boolean
}

/** Copy-paste signed-request sample for a webhook trigger. */
export interface WebhookSample {
  url: string
  signature_header: string
  sample_body: Record<string, unknown>
  curl: string
}

/** Run statuses that are still in flight — used to drive live polling. */
const ACTIVE_RUN_STATUSES = new Set(['pending', 'scheduling', 'rescheduling', 'running'])

export function useAgentTriggers(params?: {
  type?: TriggerType
  enabled?: boolean
  limit?: number
  offset?: number
}) {
  const scope = useManagedRequestScope()
  const path = apiCollectionPath('triggers', {
    type: params?.type,
    enabled: params?.enabled,
    limit: params?.limit,
    offset: params?.offset,
  })
  return useQuery({
    queryKey: ['triggers', scope.key, path],
    queryFn: () => managedGet<AgentTrigger[]>(path, managedRequestOptions(scope)),
    enabled: hasManagedRequestScope(scope),
  })
}

export function useAgentTrigger(triggerId: string | undefined) {
  const scope = useManagedRequestScope()
  return useQuery({
    queryKey: ['trigger', scope.key, triggerId],
    queryFn: () =>
      managedGet<AgentTrigger>(
        apiResourcePath('triggers', triggerId),
        managedRequestOptions(scope),
      ),
    enabled: !!triggerId && hasManagedRequestScope(scope),
  })
}

/** Normalize a create/update body: strip id prefixes off referenced resources. */
function normalizeTriggerBody(
  body: AgentTriggerCreate | AgentTriggerUpdate,
): Record<string, unknown> {
  const wire: Record<string, unknown> = { ...body }
  if ('pinned_session_id' in body) {
    wire.pinned_session_id = body.pinned_session_id
      ? apiResourceId(body.pinned_session_id)
      : body.pinned_session_id
  }
  return wire
}

export function useCreateAgentTrigger() {
  const qc = useQueryClient()
  const scope = useManagedRequestScope()
  return useMutation({
    mutationFn: (body: AgentTriggerCreate) =>
      managedPost<AgentTrigger>(
        apiCollectionPath('triggers'),
        {
          ...normalizeTriggerBody(body),
          agent_id: apiResourceId(body.agent_id),
        },
        managedRequestOptions(scope),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['triggers', scope.key] }),
  })
}

export function useUpdateAgentTrigger() {
  const qc = useQueryClient()
  const scope = useManagedRequestScope()
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: AgentTriggerUpdate }) =>
      managedPatch<AgentTrigger>(
        apiResourcePath('triggers', id),
        normalizeTriggerBody(body),
        managedRequestOptions(scope),
      ),
    onSuccess: (_data, { id }) => {
      qc.invalidateQueries({ queryKey: ['triggers', scope.key] })
      qc.invalidateQueries({ queryKey: ['trigger', scope.key, apiResourceId(id)] })
    },
  })
}

/**
 * Optimistically flip a single trigger's `enabled` in the list caches so only
 * the toggled row reacts instantly; rolls back on error and reconciles on
 * settle (backend recomputes next_run_at / clears auto-disable on re-enable).
 */
export function useToggleAgentTrigger() {
  const qc = useQueryClient()
  const scope = useManagedRequestScope()
  return useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      managedPatch<AgentTrigger>(
        apiResourcePath('triggers', id),
        { enabled },
        managedRequestOptions(scope),
      ),
    onMutate: async ({ id, enabled }) => {
      await qc.cancelQueries({ queryKey: ['triggers', scope.key] })
      const snapshots = qc.getQueriesData<AgentTrigger[]>({ queryKey: ['triggers', scope.key] })
      for (const [key, list] of snapshots) {
        if (!list) continue
        qc.setQueryData<AgentTrigger[]>(
          key,
          list.map((t) => (apiResourceId(t.id) === apiResourceId(id) ? { ...t, enabled } : t)),
        )
      }
      return { snapshots }
    },
    onError: (_err, _vars, context) => {
      for (const [key, list] of context?.snapshots ?? []) {
        qc.setQueryData(key, list)
      }
    },
    onSettled: (_data, _error, { id }) => {
      qc.invalidateQueries({ queryKey: ['triggers', scope.key] })
      qc.invalidateQueries({ queryKey: ['trigger', scope.key, apiResourceId(id)] })
    },
  })
}

export function useDeleteAgentTrigger() {
  const qc = useQueryClient()
  const scope = useManagedRequestScope()
  return useMutation({
    mutationFn: (id: string) =>
      managedDelete(apiResourcePath('triggers', id), managedRequestOptions(scope)),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['triggers', scope.key] }),
  })
}

export function useTriggerRuns(triggerId: string | undefined, limit = 10) {
  const path = triggerId ? `/triggers/${apiResourceId(triggerId)}/runs` : '/triggers/runs'
  return usePaginatedList<TriggerRun>({
    queryKey: 'trigger-runs',
    path,
    limit,
    pageSizeOptions: [10, 25, 50, 100],
    enabled: !!triggerId,
    // Poll only while a run is still in flight so a just-fired run advances to
    // its terminal state without a manual refresh. Idle when all are terminal.
    refetchInterval: (page) => {
      const runs = page?.data ?? []
      return runs.some((r) => ACTIVE_RUN_STATUSES.has(r.status)) ? 5000 : false
    },
  })
}

/** Manually run a trigger (POST /run). Optional idempotency key is honored by the backend. */
export function useRunTrigger(defaultId = '') {
  const qc = useQueryClient()
  const scope = useManagedRequestScope()
  return useMutation({
    mutationFn: ({
      id = defaultId,
      idempotencyKey,
    }: { id?: string; idempotencyKey?: string } = {}) => {
      const options = managedRequestOptions(scope)
      const headers = idempotencyKey
        ? { ...options.headers, 'Idempotency-Key': idempotencyKey }
        : options.headers
      return managedPost<TriggerFireResult>(
        apiResourcePath('triggers', id, 'run'),
        {},
        { ...options, headers },
      )
    },
    onSuccess: () =>
      qc.invalidateQueries({
        queryKey: ['trigger-runs', scope.key],
      }),
  })
}

/** Test-fire a webhook trigger (POST /test) — fires even when disabled. */
export function useTestFireWebhook(triggerId: string) {
  const qc = useQueryClient()
  const scope = useManagedRequestScope()
  return useMutation({
    mutationFn: () =>
      managedPost<TriggerFireResult>(
        apiResourcePath('triggers', triggerId, 'test'),
        {},
        managedRequestOptions(scope),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['trigger-runs', scope.key] }),
  })
}

/** Copy-paste signed-request sample (GET /webhook-sample). Webhook triggers only. */
export function useWebhookSample(triggerId: string | undefined, enabled: boolean) {
  const scope = useManagedRequestScope()
  return useQuery({
    queryKey: ['trigger-webhook-sample', scope.key, triggerId],
    queryFn: () =>
      managedGet<WebhookSample>(
        apiResourcePath('triggers', triggerId, 'webhook-sample'),
        managedRequestOptions(scope),
      ),
    enabled: enabled && !!triggerId && hasManagedRequestScope(scope),
  })
}
