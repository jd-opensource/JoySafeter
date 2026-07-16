import { describe, expect, it } from 'vitest'

import { stripIdPrefix } from './id'

describe('managed id helpers', () => {
  it('strips schedule and task prefixes before calling UUID routes', () => {
    expect(stripIdPrefix('sched_123')).toBe('123')
    expect(stripIdPrefix('task_123')).toBe('123')
    expect(stripIdPrefix('sched_task_123')).toBe('123')
  })
})
