type Translator = (key: string, options?: Record<string, unknown>) => string

export type TriggerLifecycleStatus = 'active' | 'idle' | 'auto_disabled' | 'completed'

export interface TriggerLifecycleInput {
  type: string
  enabled: boolean
  auto_disabled_at?: string | null
  run_at?: string | null
  next_run_at?: string | null
  last_fired_slot?: string | null
}

export function triggerLifecycleStatus(trigger: TriggerLifecycleInput): TriggerLifecycleStatus {
  if (trigger.auto_disabled_at) return 'auto_disabled'
  if (
    trigger.enabled &&
    trigger.type === 'cron' &&
    !!trigger.run_at &&
    !!trigger.last_fired_slot &&
    !trigger.next_run_at
  ) {
    return 'completed'
  }
  return trigger.enabled ? 'active' : 'idle'
}

/** Map a fire/run result `status` to a localized toast i18n key. */
export function fireResultToastKey(status: string): string {
  switch (status) {
    case 'fired':
      return 'managed.triggers.fireFired'
    case 'queued':
    case 'scheduled':
      return 'managed.triggers.fireQueued'
    case 'skipped':
      return 'managed.triggers.fireSkipped'
    case 'deduped':
      return 'managed.triggers.fireDeduped'
    default:
      return 'managed.triggers.fireQueued'
  }
}

export function fireResultToastMessage(
  t: Translator,
  status: string,
  name: string,
  reason?: string | null,
): string {
  const key = status === 'skipped' && reason ? 'managed.triggers.fireSkippedWithReason' : fireResultToastKey(status)
  return t(key, { name, reason: reason ?? '' })
}

/** Human-readable "Run once @ <time>" summary for a one-off cron trigger. */
export function formatRunOnce(t: Translator, runAt: string): string {
  const d = new Date(runAt)
  const when = Number.isNaN(d.getTime())
    ? runAt
    : d.toLocaleString(undefined, {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      })
  return t('managed.triggers.runOnceSummary', { when })
}
