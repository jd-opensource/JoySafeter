import { describe, expect, it } from 'vitest'

import { parseSessionEventResponse } from './event-response-parsers'

const EVENT_UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f070'

describe('event response parsers', () => {
  it('brands canonical persisted events and permits identity-free ephemeral events', () => {
    expect(parseSessionEventResponse({ id: `evt_${EVENT_UUID}`, type: 'agent.message' }).id).toBe(
      `evt_${EVENT_UUID}`,
    )
    expect(parseSessionEventResponse({ type: 'agent.message' }).id).toBeUndefined()
  })

  it('rejects bare and cross-entity ids', () => {
    expect(() => parseSessionEventResponse({ id: EVENT_UUID, type: 'agent.message' })).toThrow()
    expect(() =>
      parseSessionEventResponse({ id: `task_${EVENT_UUID}`, type: 'agent.message' }),
    ).toThrow()
  })
})
