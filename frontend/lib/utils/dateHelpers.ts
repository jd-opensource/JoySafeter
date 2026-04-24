/**
 * General-purpose date/time formatting utilities.
 */

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type TFn = (key: string, fallback?: any) => string

export function formatDuration(startedAt?: string | null, endedAt?: string | null): string | null {
  if (!startedAt) return null
  const start = new Date(startedAt).getTime()
  const end = endedAt ? new Date(endedAt).getTime() : Date.now()
  const secs = Math.floor((end - start) / 1000)
  const m = Math.floor(secs / 60)
  const s = secs % 60
  return `${m}m ${s.toString().padStart(2, '0')}s`
}

export function formatRelativeTime(value: string, t?: TFn): string {
  const date = new Date(value)
  const diffMs = Date.now() - date.getTime()
  const diffMinutes = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMs / 3600000)
  const diffDays = Math.floor(diffMs / 86400000)
  const tr: TFn = t || ((_, f) => f || '')

  if (diffMinutes < 1) return tr('execution.justNow', 'just now')
  if (diffMinutes < 60) return `${diffMinutes}${tr('execution.minutesSuffix', 'm ago')}`
  if (diffHours < 24) return `${diffHours}${tr('execution.hoursSuffix', 'h ago')}`
  if (diffDays < 30) return `${diffDays}${tr('execution.daysSuffix', 'd ago')}`
  return date.toLocaleDateString()
}
