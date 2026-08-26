import { describe, expect, it } from 'vitest'

import { eventIdTimestamp, shortEntityId } from './entity-id-display'
import { parseAgentId, parseEventId } from '@/types/entity-id'

const UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f001'

describe('entity ID display helpers', () => {
  it('shortens canonical IDs without exposing a raw UUID API', () => {
    expect(shortEntityId(parseAgentId(`agent_${UUID}`), 'agent', 6)).toBe(
      `agent_${UUID.slice(0, 6)}`,
    )
  })

  it('extracts a plausible timestamp from UUIDv7 event IDs', () => {
    expect(eventIdTimestamp(parseEventId(`evt_${UUID}`))).toBe(1715558550097)
  })

  it('rejects UUID timestamps outside the supported epoch range', () => {
    expect(eventIdTimestamp(parseEventId('evt_00000000-0000-7000-8000-000000000000'))).toBeNull()
  })
})
