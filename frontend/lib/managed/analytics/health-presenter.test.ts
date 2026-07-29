import { describe, expect, it } from 'vitest'

import { enTree, zhTree, resolveKey as resolve, placeholders } from '@/lib/i18n/test-utils'

import { alertDetailKey, suggestionMessageKey } from './health-presenter'

// The cross-stack contract: backend alert `type` → the exact numeric param keys
// it emits (analytics_service._detect_*). i18n templates must interpolate these
// and only these.
const ALERT_PARAMS: Record<string, string[]> = {
  consecutive_failures: ['count', 'threshold'],
  slow_agent: ['avgSec', 'thresholdSec'],
  token_spike: ['changePct', 'thresholdPct'],
  high_retries: ['maxRetries', 'taskCount'],
  zombie_session: ['hours'],
}

const SUGGESTION_PARAMS: Record<string, string[]> = {
  low_cache_hit: ['cacheHitPct'],
  high_output_ratio: ['outputRatioPct'],
  high_queue_wait: ['queueWaitSec'],
}

describe('health-presenter alert keys', () => {
  for (const [type, params] of Object.entries(ALERT_PARAMS)) {
    it(`${type} resolves in both locales with matching placeholders`, () => {
      const key = alertDetailKey(type)
      for (const [name, tree] of [['en', enTree], ['zh', zhTree]] as const) {
        const template = resolve(tree, key)
        expect(template, `${name}:${key}`).toBeTruthy()
        expect([...placeholders(template!)].sort(), `${name}:${key} placeholders`).toEqual([...params].sort())
      }
    })
  }

  it('unknown alert type falls back to an existing generic key', () => {
    const key = alertDetailKey('made_up')
    expect(resolve(enTree, key)).toBeTruthy()
    expect(resolve(zhTree, key)).toBeTruthy()
  })
})

describe('health-presenter suggestion keys', () => {
  for (const [type, params] of Object.entries(SUGGESTION_PARAMS)) {
    it(`${type} resolves in both locales with matching placeholders`, () => {
      const key = suggestionMessageKey(type)
      for (const [name, tree] of [['en', enTree], ['zh', zhTree]] as const) {
        const template = resolve(tree, key)
        expect(template, `${name}:${key}`).toBeTruthy()
        expect([...placeholders(template!)].sort(), `${name}:${key} placeholders`).toEqual([...params].sort())
      }
    })
  }

  it('unknown suggestion type falls back to an existing generic key', () => {
    const key = suggestionMessageKey('made_up')
    expect(resolve(enTree, key)).toBeTruthy()
    expect(resolve(zhTree, key)).toBeTruthy()
  })
})
