import { describe, expect, it } from 'vitest'

import {
  fireResultToastKey,
  fireResultToastMessage,
  formatRunOnce,
  triggerLifecycleStatus,
} from './trigger-format'

describe('fireResultToastKey', () => {
  it('maps known fire statuses to their toast keys', () => {
    expect(fireResultToastKey('fired')).toBe('managed.triggers.fireFired')
    expect(fireResultToastKey('queued')).toBe('managed.triggers.fireQueued')
    expect(fireResultToastKey('scheduled')).toBe('managed.triggers.fireQueued')
    expect(fireResultToastKey('skipped')).toBe('managed.triggers.fireSkipped')
    expect(fireResultToastKey('deduped')).toBe('managed.triggers.fireDeduped')
  })

  it('falls back to the queued key for unknown statuses (no raw code leak)', () => {
    expect(fireResultToastKey('something_else')).toBe('managed.triggers.fireQueued')
  })
})

describe('formatRunOnce', () => {
  const t = (key: string, opts?: Record<string, unknown>) =>
    `${key}:${opts ? JSON.stringify(opts) : ''}`

  it('renders a localized run-once summary with a formatted time', () => {
    const out = formatRunOnce(t, '2030-01-02T03:04:00Z')
    expect(out.startsWith('managed.triggers.runOnceSummary:')).toBe(true)
    expect(out).toContain('when')
  })

  it('passes the raw value through when the timestamp is unparseable', () => {
    const out = formatRunOnce(t, 'not-a-date')
    expect(out).toContain('not-a-date')
  })
})

describe('fireResultToastMessage', () => {
  const t = (key: string, opts?: Record<string, unknown>) =>
    `${key}:${opts ? JSON.stringify(opts) : ''}`

  it('includes skipped reasons instead of using the generic in-progress copy', () => {
    const out = fireResultToastMessage(
      t,
      'skipped',
      'Nightly',
      'triggers are paused for this project',
    )

    expect(out).toContain('managed.triggers.fireSkippedWithReason')
    expect(out).toContain('triggers are paused for this project')
  })
})

describe('triggerLifecycleStatus', () => {
  it('classifies parked one-off cron triggers as completed, not active', () => {
    expect(
      triggerLifecycleStatus({
        type: 'cron',
        enabled: true,
        run_at: '2030-01-01T00:00:00Z',
        last_fired_slot: '2030-01-01T00:00:00Z',
        next_run_at: null,
      }),
    ).toBe('completed')
  })

  it('keeps recurring enabled triggers active even before their next slot is shown', () => {
    expect(
      triggerLifecycleStatus({
        type: 'cron',
        enabled: true,
        run_at: null,
        last_fired_slot: null,
        next_run_at: null,
      }),
    ).toBe('active')
  })

  it('prioritizes auto-disabled over completed', () => {
    expect(
      triggerLifecycleStatus({
        type: 'cron',
        enabled: true,
        auto_disabled_at: '2030-01-02T00:00:00Z',
        run_at: '2030-01-01T00:00:00Z',
        last_fired_slot: '2030-01-01T00:00:00Z',
        next_run_at: null,
      }),
    ).toBe('auto_disabled')
  })
})
