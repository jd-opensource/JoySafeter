/**
 * Lifecycle transition controls for a single skill.
 *
 * Renders only the buttons that correspond to legal edges from the
 * current ``lifecycle_status``. Each button fires a POST to the
 * matching backend endpoint and refreshes the parent's query cache.
 *
 * Backend contract: ``SkillLifecycleService`` in
 * ``backend/app/joysafeter_domain/services/skill_lifecycle_service.py``
 * defines the same six transitions and rejects anything else with
 * ``SKILL_LIFECYCLE_INVALID_TRANSITION``.
 */

'use client'

import { useEffect, useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'

import { managedPost } from '@/lib/api-client'
import { apiResourcePath } from '@/lib/managed/api-paths'
import { managedRequestOptions, type ManagedRequestScope } from '@/lib/managed/request-scope'
import { useTranslation } from '@/lib/i18n'
import { toastError, toastSuccess } from '@/lib/utils/toast'
import { Button } from '@/components/ui/button'
import type { SkillImpactSummary, SkillLifecycleStatus } from '@/types/managed'
import { currentProjectAllowsWrite } from '@/hooks/managed/use-current-project-read-only'

interface TransitionResponse {
  skill_id: string
  from_status: string
  to_status: string
}

// One row per legal edge — keep in sync with ``_ALLOWED_EDGES`` in the
// backend's ``skill_lifecycle_service``. Anything else 400s with
// ``SKILL_LIFECYCLE_INVALID_TRANSITION`` on the wire, so the frontend
// pre-filters to avoid that round trip.
const TRANSITIONS: Array<{
  from: SkillLifecycleStatus
  endpoint: string
  labelKey: string
  // ``rejected`` ↔ ``draft`` re-edit is the destructive-feeling edge;
  // colour it neutral. ``approve`` / ``reject`` carry their own weight.
  variant: 'default' | 'destructive' | 'outline'
}> = [
  {
    from: 'draft',
    endpoint: 'submit-review',
    labelKey: 'managed.skills.transition.submitForReview',
    variant: 'default',
  },
  {
    from: 'pending_review',
    endpoint: 'approve',
    labelKey: 'managed.skills.transition.approve',
    variant: 'default',
  },
  {
    from: 'pending_review',
    endpoint: 'reject',
    labelKey: 'managed.skills.transition.reject',
    variant: 'destructive',
  },
  {
    from: 'rejected',
    endpoint: 'reopen',
    labelKey: 'managed.skills.transition.reopen',
    variant: 'outline',
  },
  {
    from: 'approved',
    endpoint: 'archive',
    labelKey: 'managed.skills.transition.archive',
    variant: 'outline',
  },
  {
    from: 'archived',
    endpoint: 'unarchive',
    labelKey: 'managed.skills.transition.unarchive',
    variant: 'outline',
  },
]

interface SkillLifecycleActionsProps {
  skillId: string
  currentStatus: SkillLifecycleStatus | string | undefined
  requestScope: ManagedRequestScope
  operationScope: string
  canSubmitTransition?: (
    endpoint: string,
    currentStatus: SkillLifecycleStatus | string | undefined,
  ) => boolean
  // Optional invalidation keys — list views can pass their list key
  // to force a refetch after a transition lands.
  invalidateKeys?: Array<readonly unknown[]>
  impact?: SkillImpactSummary | null
}

export function SkillLifecycleActions({
  skillId,
  currentStatus,
  requestScope,
  operationScope,
  canSubmitTransition,
  invalidateKeys = [],
  impact = null,
}: SkillLifecycleActionsProps) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const [busyEndpoint, setBusyEndpoint] = useState<string | null>(null)
  const operationScopeRef = useRef(operationScope)
  const requestScopeRef = useRef(requestScope)
  const mutationRunRef = useRef(0)

  useEffect(() => {
    if (operationScopeRef.current === operationScope) return
    operationScopeRef.current = operationScope
    requestScopeRef.current = requestScope
    mutationRunRef.current += 1
    setBusyEndpoint(null)
  }, [operationScope, requestScope])

  useEffect(
    () => () => {
      mutationRunRef.current += 1
    },
    [],
  )

  const nextMutation = (endpoint: string) => {
    if (!currentProjectAllowsWrite()) return null
    const runId = mutationRunRef.current + 1
    mutationRunRef.current = runId
    return {
      endpoint,
      skillId,
      invalidateKeys: [...invalidateKeys],
      requestScope: requestScopeRef.current,
      runId,
      scope: operationScopeRef.current,
    }
  }
  const isCurrentMutation = (runId: number, scope: string) =>
    mutationRunRef.current === runId &&
    operationScopeRef.current === scope &&
    currentProjectAllowsWrite()

  const mutation = useMutation({
    mutationFn: async ({
      skillId,
      endpoint,
      requestScope,
      runId,
      scope,
    }: {
      skillId: string
      endpoint: string
      invalidateKeys: Array<readonly unknown[]>
      requestScope: ManagedRequestScope
      runId: number
      scope: string
    }) => {
      if (!currentProjectAllowsWrite()) {
        throw new Error('Archived project skill lifecycle transition ignored')
      }
      setBusyEndpoint(endpoint)
      try {
        const result = await managedPost<TransitionResponse>(
          apiResourcePath('skills', skillId, endpoint),
          {},
          managedRequestOptions(requestScope),
        )
        return result
      } finally {
        if (isCurrentMutation(runId, scope)) {
          setBusyEndpoint(null)
        }
      }
    },
    onSuccess: (data, variables) => {
      if (!isCurrentMutation(variables.runId, variables.scope)) return
      toastSuccess(
        t('managed.skills.transition.success', {
          from: data.from_status,
          to: data.to_status,
        }),
      )
      // Invalidate caller-provided queries (skill list, detail, etc.)
      for (const key of variables.invalidateKeys) {
        qc.invalidateQueries({ queryKey: key })
      }
    },
    onError: (error: unknown, variables) => {
      if (!isCurrentMutation(variables.runId, variables.scope)) return
      const msg = error instanceof Error ? error.message : t('managed.skills.transition.failed')
      toastError(msg)
    },
  })

  const available = TRANSITIONS.filter((t) => t.from === currentStatus)

  if (available.length === 0) {
    return null
  }

  return (
    <div className="inline-flex items-center gap-1.5">
      {available.map((edge) => {
        const canSubmit = canSubmitTransition
          ? canSubmitTransition(edge.endpoint, currentStatus)
          : currentProjectAllowsWrite()
        return (
          <Button
            key={edge.endpoint}
            variant={edge.variant}
            size="sm"
            disabled={busyEndpoint !== null || !canSubmit}
            onClick={() => {
              if (!canSubmit) return
              if (edge.endpoint === 'archive' && impact?.counts.total) {
                const ok = window.confirm(
                  t('managed.skills.archiveImpactConfirm', {
                    count: impact.counts.total,
                    agents: impact.counts.agents,
                    schedules: impact.counts.schedules,
                    activeTasks: impact.counts.active_tasks,
                    defaultValue: `Archive this skill? It is referenced by ${impact.counts.total} item(s): ${impact.counts.agents} agent(s), ${impact.counts.schedules} schedule(s), ${impact.counts.active_tasks} active task(s).`,
                  }),
                )
                if (!ok) return
              }
              const next = nextMutation(edge.endpoint)
              if (next) mutation.mutate(next)
            }}
          >
            {t(edge.labelKey)}
          </Button>
        )
      })}
    </div>
  )
}
