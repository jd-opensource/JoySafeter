'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { managedDelete, managedGet, managedPatch, managedPost } from '@/lib/api-client'
import { apiCollectionPath, apiResourceId, apiResourcePath } from '@/lib/managed/api-paths'
import { hasManagedRequestScope, managedRequestOptions, useManagedRequestScope } from '@/lib/managed/request-scope'

export type TriggerSessionMode = 'fresh' | 'reuse' | 'pinned'

export interface AgentTrigger {
  id: string
  name: string
  description: string | null
  type: 'cron' | 'webhook' | 'manual'
  agent_id: string
  prompt_template: string
  system_prompt: string | null
  environment_ref: string | null
  enabled: boolean
  session_mode: TriggerSessionMode
  pinned_session_id: string | null
  reusable_session_id: string | null
  filter: Record<string, unknown>
  timeout_sec: number
  max_retries: number
  cron_expr?: string | null
  timezone?: string | null
  concurrency_policy?: 'allow' | 'forbid' | 'replace' | null
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
  last_task_id: string | null
  last_session_id: string | null
  last_payload: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface AgentTriggerCreate {
  name: string
  type?: 'cron' | 'webhook'
  agent_id: string
  prompt_template: string
  secret_ref?: string | null
  secret_key?: string | null
  system_prompt?: string | null
  environment_ref?: string | null
  description?: string | null
  enabled?: boolean
  session_mode?: TriggerSessionMode
  pinned_session_id?: string | null
  filter?: Record<string, unknown>
  timeout_sec?: number
  max_retries?: number
  cron_expr?: string | null
  timezone?: string | null
  concurrency_policy?: 'allow' | 'forbid' | 'replace' | null
}

export type AgentTriggerUpdate = Partial<Omit<AgentTriggerCreate, 'type' | 'agent_id'>>

export function useAgentTriggers() {
  const scope = useManagedRequestScope()
  return useQuery({
    queryKey: ['triggers', scope.key],
    queryFn: () => managedGet<AgentTrigger[]>(apiCollectionPath('triggers'), managedRequestOptions(scope)),
    enabled: hasManagedRequestScope(scope),
  })
}

export function useCreateAgentTrigger() {
  const qc = useQueryClient()
  const scope = useManagedRequestScope()
  return useMutation({
    mutationFn: (body: AgentTriggerCreate) => managedPost<AgentTrigger>(apiCollectionPath('triggers'), {
      ...body,
      agent_id: apiResourceId(body.agent_id),
      pinned_session_id: body.pinned_session_id ? apiResourceId(body.pinned_session_id) : null,
    }, managedRequestOptions(scope)),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['triggers', scope.key] }),
  })
}

export function useUpdateAgentTrigger() {
  const qc = useQueryClient()
  const scope = useManagedRequestScope()
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: AgentTriggerUpdate }) => managedPatch<AgentTrigger>(apiResourcePath('triggers', id), {
      ...body,
      pinned_session_id: body.pinned_session_id ? apiResourceId(body.pinned_session_id) : body.pinned_session_id,
    }, managedRequestOptions(scope)),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['triggers', scope.key] }),
  })
}

export function useDeleteAgentTrigger() {
  const qc = useQueryClient()
  const scope = useManagedRequestScope()
  return useMutation({
    mutationFn: (id: string) => managedDelete(apiResourcePath('triggers', id), managedRequestOptions(scope)),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['triggers', scope.key] }),
  })
}
