/**
 * Single source of truth for presenting analytics health anomalies to users.
 *
 * The backend contract is intentionally machine-only: each alert/suggestion is
 * a ``type`` (what kind of anomaly) plus a ``params`` bag of numeric values.
 * ALL human-facing, localized copy lives in the i18n locales — never baked into
 * the backend. Callers translate ``t(alertDetailKey(type), alert.params)``.
 */

// alert type (backend machine code) → i18n leaf under analytics.alerts.detail.*
const ALERT_DETAIL_SLUG: Record<string, string> = {
  consecutive_failures: 'consecutiveFailures',
  slow_agent: 'slowAgent',
  token_spike: 'tokenSpike',
  high_retries: 'highRetries',
  zombie_session: 'zombieSession',
}

/** Alert type → i18n key for its localized detail line. Unknown types fall back to a generic key. */
export function alertDetailKey(type: string): string {
  const slug = ALERT_DETAIL_SLUG[type] || 'unknown'
  return `analytics.alerts.detail.${slug}`
}

// suggestion type (backend machine code) → i18n leaf under analytics.tokenSummary.suggestionMessages.*
const SUGGESTION_SLUG: Record<string, string> = {
  low_cache_hit: 'lowCacheHit',
  high_output_ratio: 'highOutputRatio',
  high_queue_wait: 'highQueueWait',
}

/** Suggestion type → i18n key for its localized message. Unknown types fall back to a generic key. */
export function suggestionMessageKey(type: string): string {
  const slug = SUGGESTION_SLUG[type] || 'unknown'
  return `analytics.tokenSummary.suggestionMessages.${slug}`
}
