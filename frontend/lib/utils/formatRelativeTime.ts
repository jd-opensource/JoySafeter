/**
 * Format a date string as a relative time string (e.g. "5m ago", "2h ago").
 * Uses i18n translation keys under `settings.tokens.*`.
 */
export function formatRelativeTime(
  dateStr: string | null,
  t: (key: string, opts?: any) => string,
): string {
  if (!dateStr) return t('settings.tokens.neverUsed')
  const diff = Date.now() - new Date(dateStr).getTime()
  const minutes = Math.floor(diff / 60_000)
  if (minutes < 1) return t('settings.tokens.justNow')
  if (minutes < 60) return t('settings.tokens.minutesAgo', { count: minutes })
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return t('settings.tokens.hoursAgo', { count: hours })
  const days = Math.floor(hours / 24)
  return t('settings.tokens.daysAgo', { count: days })
}
