import { afterEach, describe, expect, it } from 'vitest'

import type { SessionEvent } from '@/types/managed'

import {
  clearCachedSessionEventState,
  getCachedSessionEventState,
  setCachedSessionEventState,
} from './session-event-cache'

const CACHE_KEY = 'sess:test-scope'

afterEach(() => {
  clearCachedSessionEventState(CACHE_KEY)
})

describe('session event cache', () => {
  it('keeps older pagination enabled when cache trimming drops history', () => {
    const events: SessionEvent[] = Array.from({ length: 10001 }, (_, index) => ({
      type: 'agent.message',
      seq: index + 1,
    }))

    setCachedSessionEventState(CACHE_KEY, events, false)

    const cached = getCachedSessionEventState(CACHE_KEY)
    expect(cached?.events).toHaveLength(10000)
    expect(cached?.minSeq).toBe(2)
    expect(cached?.hasMoreOlder).toBe(true)
  })
})
