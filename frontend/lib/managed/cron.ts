'use client'

/**
 * Rich cron utilities for the scheduler UI.
 *
 * Backs the cron editor's three modes (presets / visual builder / advanced):
 * - `isValidCron` — 5-field validation matching the backend (croniter).
 * - `describeCron` — human-readable, i18n (en/zh) description via cronstrue.
 * - `nextRuns` — timezone- and DST-correct list of the next N fire instants,
 *   computed with cron-parser so the preview matches what the Rust worker will
 *   actually do (backend evaluates the cron in the schedule's timezone).
 *
 * Requires deps: `cron-parser` (^4) and `cronstrue` (^2). Add via
 * `pnpm add cron-parser cronstrue`.
 */

import parser from 'cron-parser'
import cronstrue from 'cronstrue'
import 'cronstrue/locales/zh_CN'

export interface CronPreset {
  labelKey: string
  expr: string
}

/** Curated presets surfaced in the editor's "Presets" tab. */
export const CRON_PRESETS: CronPreset[] = [
  { labelKey: 'managed.triggers.cron.presets.everyMinute', expr: '* * * * *' },
  { labelKey: 'managed.triggers.cron.presets.every5Minutes', expr: '*/5 * * * *' },
  { labelKey: 'managed.triggers.cron.presets.every15Minutes', expr: '*/15 * * * *' },
  { labelKey: 'managed.triggers.cron.presets.hourly', expr: '0 * * * *' },
  { labelKey: 'managed.triggers.cron.presets.daily9am', expr: '0 9 * * *' },
  { labelKey: 'managed.triggers.cron.presets.weekdays9am', expr: '0 9 * * 1-5' },
  { labelKey: 'managed.triggers.cron.presets.weeklyMon', expr: '0 9 * * 1' },
  { labelKey: 'managed.triggers.cron.presets.monthly1st', expr: '0 0 1 * *' },
]

/** True if `expr` is a valid 5-field cron expression. */
export function isValidCron(expr: string): boolean {
  const trimmed = expr?.trim()
  if (!trimmed) return false
  // Backend uses 5-field cron (min hour dom month dow); reject other arities.
  if (trimmed.split(/\s+/).length !== 5) return false
  try {
    parser.parseExpression(trimmed)
    return true
  } catch {
    return false
  }
}

/**
 * Human-readable description, e.g. "At 09:00, Monday through Friday".
 * Falls back to the raw expression if it cannot be parsed.
 */
export function describeCron(expr: string, locale: 'en' | 'zh' = 'en'): string {
  const trimmed = expr?.trim()
  if (!trimmed) return ''
  if (!isValidCron(trimmed)) return trimmed
  try {
    return cronstrue.toString(trimmed, {
      locale: locale === 'zh' ? 'zh_CN' : 'en',
      use24HourTimeFormat: true,
      throwExceptionOnParseError: true,
    })
  } catch {
    return trimmed
  }
}

/**
 * The next `count` fire instants for `expr`, evaluated in `timezone`
 * (IANA name), returned as UTC `Date`s. Empty array on invalid input.
 */
export function nextRuns(expr: string, timezone = 'UTC', count = 5): Date[] {
  const trimmed = expr?.trim()
  if (!trimmed || !isValidCron(trimmed)) return []
  try {
    const it = parser.parseExpression(trimmed, { tz: timezone, currentDate: new Date() })
    const out: Date[] = []
    for (let i = 0; i < count; i++) {
      out.push(it.next().toDate())
    }
    return out
  } catch {
    return []
  }
}

/** Common IANA timezones offered in the timezone picker (UTC first). */
export const COMMON_TIMEZONES: string[] = [
  'UTC',
  'Asia/Shanghai',
  'Asia/Tokyo',
  'Asia/Singapore',
  'Asia/Kolkata',
  'Europe/London',
  'Europe/Paris',
  'Europe/Berlin',
  'America/New_York',
  'America/Chicago',
  'America/Los_Angeles',
  'Australia/Sydney',
]

/** Best-effort browser timezone, falling back to UTC. */
export function detectBrowserTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
  } catch {
    return 'UTC'
  }
}
