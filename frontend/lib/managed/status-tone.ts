/**
 * Single source of truth for status → semantic tone → Tailwind classes.
 *
 * Before this, six+ files each hand-rolled a `Record<string, colorClasses>`
 * encoding the same intents (success = emerald/green, warning = amber, danger =
 * rose/red, neutral = slate/gray, info = sky/indigo) with slightly different
 * shades — a design-consistency bug, not just duplication. All status pills,
 * dots and delta colors should classify through `statusToTone()` and read the
 * class tuples from `STATUS_TONE`.
 */

export type StatusTone = 'success' | 'warning' | 'danger' | 'neutral' | 'info'

export interface ToneClasses {
  /** Border + translucent bg + text — dark-mode aware. For outline badges/pills. */
  badge: string
  /** Solid background dot/bar, e.g. legends and progress bars. */
  dot: string
  /** Text-only color, e.g. deltas and inline emphasis. */
  text: string
}

/**
 * Canonical tone → class tuples. The `badge` variant uses opacity + dark:
 * variants (the status-badge house style) so it works in both themes.
 */
export const STATUS_TONE: Record<StatusTone, ToneClasses> = {
  success: {
    badge: 'border-emerald-500/50 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400',
    dot: 'bg-emerald-500',
    text: 'text-emerald-600 dark:text-emerald-400',
  },
  warning: {
    badge: 'border-amber-500/50 bg-amber-500/10 text-amber-700 dark:text-amber-400',
    dot: 'bg-amber-500',
    text: 'text-amber-600 dark:text-amber-400',
  },
  danger: {
    badge: 'border-rose-500/50 bg-rose-500/10 text-rose-700 dark:text-rose-400',
    dot: 'bg-rose-500',
    text: 'text-rose-600 dark:text-rose-400',
  },
  neutral: {
    badge: 'border-slate-400/50 bg-slate-400/10 text-slate-600 dark:text-slate-400',
    dot: 'bg-slate-400',
    text: 'text-slate-600 dark:text-slate-400',
  },
  info: {
    badge: 'border-sky-500/50 bg-sky-500/10 text-sky-700 dark:text-sky-400',
    dot: 'bg-sky-500',
    text: 'text-sky-600 dark:text-sky-400',
  },
}

/**
 * Map a raw status/kind string to a semantic tone. Case-insensitive.
 * Covers session/sandbox lifecycle, skill lifecycle + security scan, skill
 * visibility, diff kinds, and analytics error categories.
 */
export function statusToTone(status: string): StatusTone {
  switch (status.toLowerCase()) {
    // success
    case 'active':
    case 'running':
    case 'passed':
    case 'approved':
    case 'ready':
    case 'added':
    case 'success':
    case 'completed':
      return 'success'
    // warning
    case 'warning':
    case 'pending_review':
    case 'pending':
    case 'timeout':
    case 'modified':
      return 'warning'
    // danger
    case 'blocked':
    case 'failed':
    case 'rejected':
    case 'error':
    case 'removed':
      return 'danger'
    // info
    case 'scanning':
    case 'provisioning':
    case 'organization':
    case 'public':
    case 'project':
      return 'info'
    // neutral (idle, terminated, archived, draft, not_scanned, cancelled, …)
    default:
      return 'neutral'
  }
}

/** Convenience: raw status → the badge class string. */
export function statusBadgeClass(status: string): string {
  return STATUS_TONE[statusToTone(status)].badge
}

/** Convenience: raw status → the solid dot class string. */
export function statusDotClass(status: string): string {
  return STATUS_TONE[statusToTone(status)].dot
}

/**
 * Raw status/kind → i18n key for its human label. Values are i18n keys (not
 * translated strings) so this module stays framework-free; callers translate
 * via ``t()`` and fall back to the raw code when a status is unmapped. This is
 * the single label map shared by every status surface (``StatusBadge`` pills,
 * the analytics error legend, …) so they never drift out of sync.
 */
const STATUS_LABEL_KEY: Record<string, string> = {
  active: 'common.active',
  // A session that is "running" reads as "Agent running" — intentionally not common.*.
  running: 'managed.sessions.agentRunning',
  idle: 'common.idle',
  terminated: 'common.terminated',
  archived: 'common.archived',
  private: 'common.private',
  passed: 'common.passed',
  warning: 'common.warning',
  blocked: 'common.blocked',
  failed: 'common.failed',
  not_scanned: 'common.notScanned',
  pending: 'common.pending',
  scheduling: 'common.scheduling',
  rescheduling: 'common.rescheduling',
  completed: 'common.completed',
  aborted: 'common.aborted',
  timeout: 'common.timeout',
  cancelled: 'common.cancelled',
  error: 'common.error',
}

/**
 * Raw status → i18n key for its label, or ``undefined`` when unmapped (caller
 * falls back to the raw string). Case-insensitive.
 */
export function statusLabelKey(status: string): string | undefined {
  return STATUS_LABEL_KEY[status.toLowerCase()]
}
