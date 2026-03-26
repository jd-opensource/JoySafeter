/**
 * Shared helpers for run-related UI: status formatting, relative time,
 * active-status check, URL building, and summary reducers for WS frames.
 */

import type { RunEventFrame, RunSnapshotFrame, RunStatusFrame } from '@/lib/ws/runs/types'
import type { RunSummary } from '@/services/runService'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type TFn = (key: string, fallback?: any) => string

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const ACTIVE_RUN_STATUSES = new Set(['queued', 'running', 'interrupt_wait'])

// ---------------------------------------------------------------------------
// Formatters
// ---------------------------------------------------------------------------

export function formatRunStatus(status: string, t: TFn): string {
  const map: Record<string, string> = {
    queued: t('runs.statusQueued', 'Queued'),
    running: t('runs.statusRunning', 'Running'),
    interrupt_wait: t('runs.statusInterruptWait', 'Waiting Input'),
    completed: t('runs.statusCompleted', 'Completed'),
    failed: t('runs.statusFailed', 'Failed'),
    cancelled: t('runs.statusCancelled', 'Cancelled'),
  }
  return map[status] || status
}

export function formatRelativeTime(value: string, t?: TFn): string {
  const date = new Date(value)
  const diffMs = Date.now() - date.getTime()
  const diffMinutes = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMs / 3600000)
  const diffDays = Math.floor(diffMs / 86400000)
  const tr: TFn = t || ((_, f) => f || '')

  if (diffMinutes < 1) return tr('runs.justNow', 'just now')
  if (diffMinutes < 60) return `${diffMinutes}${tr('runs.minutesSuffix', 'm ago')}`
  if (diffHours < 24) return `${diffHours}${tr('runs.hoursSuffix', 'h ago')}`
  if (diffDays < 30) return `${diffDays}${tr('runs.daysSuffix', 'd ago')}`
  return date.toLocaleDateString()
}

// ---------------------------------------------------------------------------
// URL helpers
// ---------------------------------------------------------------------------

export function buildRunHref(run: { run_id: string; run_type?: string; agent_name?: string | null }): string {
  if (run.agent_name === 'skill_creator' || run.run_type === 'skill_creator') {
    return `/skills/creator?run=${encodeURIComponent(run.run_id)}`
  }
  return '#'
}

// ---------------------------------------------------------------------------
// RunSummary reducers for WS frames
// ---------------------------------------------------------------------------

export function applyRunSnapshot(current: RunSummary, frame: RunSnapshotFrame): RunSummary {
  return {
    ...current,
    status: typeof frame.data?.status === 'string' ? frame.data.status : current.status,
    thread_id: typeof frame.data?.thread_id === 'string' ? frame.data.thread_id : current.thread_id,
    title: typeof frame.data?.title === 'string' ? frame.data.title : current.title,
    last_seq: frame.last_seq,
  }
}

export function applyRunEvent(current: RunSummary, frame: RunEventFrame): RunSummary {
  return {
    ...current,
    last_seq: frame.seq,
    updated_at: frame.created_at || new Date().toISOString(),
    error_message:
      frame.event_type === 'error' && typeof frame.data?.message === 'string'
        ? frame.data.message
        : current.error_message,
  }
}

export function applyRunStatus(current: RunSummary, frame: RunStatusFrame): RunSummary {
  return {
    ...current,
    status: frame.status,
    error_code: frame.error_code ?? current.error_code,
    error_message: frame.error_message ?? current.error_message,
    updated_at: new Date().toISOString(),
  }
}
