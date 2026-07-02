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

import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'

import { managedPost } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import { toastError, toastSuccess } from '@/lib/utils/toast'
import { Button } from '@/components/ui/button'
import type { SkillLifecycleStatus } from '@/types/managed'

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
  // Optional invalidation keys — list views can pass their list key
  // to force a refetch after a transition lands.
  invalidateKeys?: Array<readonly unknown[]>
}

export function SkillLifecycleActions({
  skillId,
  currentStatus,
  invalidateKeys = [],
}: SkillLifecycleActionsProps) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const [busyEndpoint, setBusyEndpoint] = useState<string | null>(null)

  // ``managedPost`` strips the resource prefix from the id before
  // hitting the endpoint. The backend route uses the bare UUID under
  // ``/skills/{id}/<action>``, matching the existing skill routes.
  const bareId = skillId.startsWith('skill_') ? skillId.slice('skill_'.length) : skillId

  const mutation = useMutation({
    mutationFn: async (endpoint: string) => {
      setBusyEndpoint(endpoint)
      try {
        const result = await managedPost<TransitionResponse>(`/skills/${bareId}/${endpoint}`)
        return result
      } finally {
        setBusyEndpoint(null)
      }
    },
    onSuccess: (data) => {
      toastSuccess(
        t('managed.skills.transition.success', {
          from: data.from_status,
          to: data.to_status,
        }),
      )
      // Invalidate caller-provided queries (skill list, detail, etc.)
      for (const key of invalidateKeys) {
        qc.invalidateQueries({ queryKey: key })
      }
    },
    onError: (error: unknown) => {
      const msg = error instanceof Error ? error.message : t('managed.skills.transition.failed')
      toastError(msg)
    },
  })

  const available = TRANSITIONS.filter((t) => t.from === currentStatus)

  if (available.length === 0) {
    return null
  }

  return (
    <div className="inline-flex flex-wrap items-center gap-2">
      {available.map((edge) => (
        <Button
          key={edge.endpoint}
          variant={edge.variant}
          size="sm"
          disabled={busyEndpoint !== null}
          onClick={() => mutation.mutate(edge.endpoint)}
        >
          {t(edge.labelKey)}
        </Button>
      ))}
    </div>
  )
}
