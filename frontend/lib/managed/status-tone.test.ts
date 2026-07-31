import { describe, expect, it } from 'vitest'

import { enTree, zhTree, resolveKey as resolve } from '@/lib/i18n/test-utils'

import {
  STATUS_TONE,
  statusBadgeClass,
  statusDotClass,
  statusLabelKey,
  statusToTone,
} from './status-tone'

describe('statusToTone', () => {
  it('maps success-family statuses', () => {
    for (const s of ['active', 'running', 'passed', 'approved', 'completed', 'added']) {
      expect(statusToTone(s)).toBe('success')
    }
  })

  it('maps warning-family statuses', () => {
    for (const s of ['warning', 'pending_review', 'timeout', 'modified']) {
      expect(statusToTone(s)).toBe('warning')
    }
  })

  it('maps danger-family statuses', () => {
    for (const s of ['blocked', 'failed', 'rejected', 'error', 'removed']) {
      expect(statusToTone(s)).toBe('danger')
    }
  })

  it('maps info-family statuses', () => {
    for (const s of ['scanning', 'provisioning', 'public', 'organization']) {
      expect(statusToTone(s)).toBe('info')
    }
  })

  it('falls back to neutral for unknown / idle / archived', () => {
    for (const s of ['idle', 'terminated', 'archived', 'draft', 'not_scanned', 'whatever']) {
      expect(statusToTone(s)).toBe('neutral')
    }
  })

  it('is case-insensitive', () => {
    expect(statusToTone('RUNNING')).toBe('success')
    expect(statusToTone('Failed')).toBe('danger')
  })
})

describe('class helpers', () => {
  it('statusBadgeClass returns the tone badge class', () => {
    expect(statusBadgeClass('running')).toBe(STATUS_TONE.success.badge)
    expect(statusBadgeClass('failed')).toBe(STATUS_TONE.danger.badge)
  })

  it('statusDotClass returns the tone dot class', () => {
    expect(statusDotClass('timeout')).toBe(STATUS_TONE.warning.dot)
    expect(statusDotClass('cancelled')).toBe(STATUS_TONE.neutral.dot)
  })
})

describe('statusLabelKey', () => {
  it('maps every task/session lifecycle status to an i18n key that resolves in both locales', () => {
    for (const s of [
      'active',
      'running',
      'idle',
      'terminated',
      'archived',
      'pending',
      'scheduling',
      'rescheduling',
      'completed',
      'aborted',
      'timeout',
      'cancelled',
      'failed',
      'error',
    ]) {
      const key = statusLabelKey(s)
      expect(key, s).toBeTruthy()
      expect(resolve(enTree, key!), `en:${key}`).toBeTruthy()
      expect(resolve(zhTree, key!), `zh:${key}`).toBeTruthy()
    }
  })

  it('is case-insensitive', () => {
    expect(statusLabelKey('COMPLETED')).toBe('common.completed')
    expect(statusLabelKey('Cancelled')).toBe('common.cancelled')
  })

  it('returns undefined for unmapped codes so callers fall back to the raw string', () => {
    expect(statusLabelKey('some_unknown_code')).toBeUndefined()
  })
})
