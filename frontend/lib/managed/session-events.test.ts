import { describe, expect, it } from 'vitest'

import type { SessionEvent } from '@/types/managed'
import { parseEventId } from '@/types/entity-id'

import { getEventIdentity, mergeSessionEvents } from './session-events'

function event(id: string, seq: number, type = 'agent.message'): SessionEvent {
  return { id: parseEventId(id), seq, type, content: [{ type: 'text', text: id }] }
}

const EVENT_1 = 'evt_018f6f42-0a51-7cc4-98c8-4f6f0ca5f071'
const EVENT_2 = 'evt_018f6f42-0a51-7cc4-98c8-4f6f0ca5f072'
const EVENT_3 = 'evt_018f6f42-0a51-7cc4-98c8-4f6f0ca5f073'
const EVENT_4 = 'evt_018f6f42-0a51-7cc4-98c8-4f6f0ca5f074'

describe('session event data merging', () => {
  it('uses canonical event identity directly', () => {
    expect(getEventIdentity(event(EVENT_1, 7))).toBe(`seq:7:agent.message`)
  })

  it('lets SSE replay fill seq gaps left by the persisted history bucket', () => {
    const merged = mergeSessionEvents(
      [event(EVENT_1, 1), event(EVENT_3, 3)],
      [event(EVENT_2, 2), event(EVENT_3, 3), event(EVENT_4, 4)],
    )

    expect(merged.map((e) => e.seq)).toEqual([1, 2, 3, 4])
  })

  it('keeps seq-less live events instead of dropping them behind the current max seq', () => {
    const liveEvent: SessionEvent = {
      type: 'agent.tool_use',
      input: { command: 'confirm' },
    }

    const merged = mergeSessionEvents([event(EVENT_1, 10)], [liveEvent])

    expect(merged).toContain(liveEvent)
  })
})
