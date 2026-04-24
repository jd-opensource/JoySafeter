/**
 * General-purpose date/time formatting utilities.
 */

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type TFn = (key: string, fallback?: any) => string

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
