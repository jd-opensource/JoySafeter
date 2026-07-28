import { describe, expect, it } from 'vitest'

import { fireResultToastKey, formatRunOnce } from './trigger-format'

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
