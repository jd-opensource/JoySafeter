import { describe, expect, it } from 'vitest'

import { enTree, zhTree, resolveKey as resolve } from '@/lib/i18n/test-utils'

import { severityLabelKey } from './skill-severity'

describe('severityLabelKey', () => {
  it('maps the fixed severity enum (case-insensitive) to resolvable i18n keys', () => {
    for (const s of ['CRITICAL', 'High', 'medium', 'LOW', 'INFO', 'INFORMATIONAL']) {
      const key = severityLabelKey(s)
      expect(resolve(enTree, key), `en:${key}`).toBeTruthy()
      expect(resolve(zhTree, key), `zh:${key}`).toBeTruthy()
    }
  })

  it('folds INFORMATIONAL into info', () => {
    expect(severityLabelKey('INFORMATIONAL')).toBe('managed.skills.severityLabel.info')
  })

  it('falls back to unknown for unmapped or empty severity', () => {
    for (const s of ['weird', '', null, undefined]) {
      const key = severityLabelKey(s)
      expect(key).toBe('managed.skills.severityLabel.unknown')
      expect(resolve(enTree, key)).toBeTruthy()
      expect(resolve(zhTree, key)).toBeTruthy()
    }
  })
})
