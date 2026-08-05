import { describe, expect, it } from 'vitest'

import type { SessionEvent } from '@/types/managed'

import { getEventIdentity, mergeSessionEvents } from './session-events'

function event(id: string, seq: number, type = 'agent.message'): SessionEvent {
  return { id, seq, type, content: [{ type: 'text', text: id }] }
}

describe('session event data merging', () => {
  it('normalizes REST ids and SSE ids for the same persisted event', () => {
    expect(getEventIdentity(event('123', 7))).toBe(getEventIdentity(event('evt_123', 7)))
  })

  it('lets SSE replay fill seq gaps left by the persisted history bucket', () => {
    const merged = mergeSessionEvents(
      [event('evt-1', 1), event('evt-3', 3)],
      [event('evt_evt-2', 2), event('evt_evt-3', 3), event('evt_evt-4', 4)],
    )

    expect(merged.map((e) => e.seq)).toEqual([1, 2, 3, 4])
  })

  it('keeps seq-less live events instead of dropping them behind the current max seq', () => {
    const liveEvent: SessionEvent = {
      id: 'live-control',
      type: 'agent.tool_use',
      input: { command: 'confirm' },
    }

    const merged = mergeSessionEvents([event('evt-10', 10)], [liveEvent])

    expect(merged).toContain(liveEvent)
  })
})
