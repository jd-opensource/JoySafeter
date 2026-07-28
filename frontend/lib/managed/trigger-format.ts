type Translator = (key: string, options?: Record<string, unknown>) => string

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
