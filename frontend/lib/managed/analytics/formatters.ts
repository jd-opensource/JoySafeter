/**
 * Number and unit formatters for analytics dashboard values.
 */

/**
 * Compact a large number with K/M/B suffix.
 * Examples: 1284 → "1,284", 12900 → "12.9K", 4200000 → "4.2M"
 */
export function formatCompactNumber(value: number): string {
  if (value >= 1_000_000_000) {
    return `${(value / 1_000_000_000).toFixed(1)}B`
  }
  if (value >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(1)}M`
  }
  if (value >= 10_000) {
    return `${(value / 1_000).toFixed(1)}K`
  }
  return value.toLocaleString()
}

/**
 * Format a token count with appropriate suffix.
 */
export function formatTokens(value: number): string {
  return formatCompactNumber(value)
}

/**
 * Format milliseconds as a human-readable duration.
 * Examples: 800 → "800ms", 1200 → "1.2s", 125000 → "2m 5s"
 */
export function formatDuration(ms: number): string {
  if (ms < 1000) {
    return `${Math.round(ms)}ms`
  }
  if (ms < 60_000) {
    return `${(ms / 1000).toFixed(1)}s`
  }
  const minutes = Math.floor(ms / 60_000)
  const seconds = Math.round((ms % 60_000) / 1000)
  return seconds > 0 ? `${minutes}m ${seconds}s` : `${minutes}m`
}

/**
 * Format a cost value in USD.
 * Examples: 0.023 → "$0.023", 142.56 → "$142.56", 1284.5 → "$1,284.50"
 */
export function formatCost(value: number): string {
  if (value >= 100) {
    return `$${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
  }
  if (value >= 1) {
    return `$${value.toFixed(2)}`
  }
  return `$${value.toFixed(3)}`
}

/**
 * Format a percentage value.
 * Examples: 0.963 → "96.3%", 1.0 → "100%"
 */
export function formatPercent(value: number): string {
  const pct = value * 100
  if (pct === 100 || pct === 0) {
    return `${pct}%`
  }
  return `${pct.toFixed(1)}%`
}

/**
 * Format a delta value as a signed percentage string.
 * Examples: 0.123 → "+12.3%", -0.012 → "-1.2%"
 */
export function formatDelta(value: number | null): string | null {
  if (value === null || value === undefined) return null
  const pct = value * 100
  const sign = pct > 0 ? '+' : ''
  return `${sign}${pct.toFixed(1)}%`
}

/**
 * Format Y-axis tick values for token charts (K/M).
 */
export function formatAxisTokens(value: number): string {
  if (value >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(0)}M`
  }
  if (value >= 1_000) {
    return `${(value / 1_000).toFixed(0)}K`
  }
  return String(value)
}

/**
 * Format Y-axis tick values for duration charts (ms/s).
 */
export function formatAxisDuration(ms: number): string {
  if (ms >= 1000) {
    return `${(ms / 1000).toFixed(1)}s`
  }
  return `${Math.round(ms)}ms`
}

/**
 * Format a timestamp for X-axis display based on time range.
 */
export function formatAxisTimestamp(timestamp: string, range: string): string {
  const date = new Date(timestamp)
  if (range === '24h') {
    return date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
  }
  if (range === '7d') {
    return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
  }
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}
