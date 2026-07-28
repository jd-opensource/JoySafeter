import { describe, expect, it } from 'vitest'

import { stripIdPrefix } from './id'

describe('managed id helpers', () => {
  it('strips trigger and task prefixes before calling UUID routes', () => {
    expect(stripIdPrefix('trig_123')).toBe('123')
    expect(stripIdPrefix('task_123')).toBe('123')
    expect(stripIdPrefix('trig_task_123')).toBe('123')
  })
})
