import { describe, expect, it } from 'vitest'

import { describeCron, isValidCron, nextRuns } from './cron'

describe('managed cron utilities', () => {
  it('matches the backend 5-field cron contract', () => {
    expect(isValidCron('*/5 * * * *')).toBe(true)
    expect(isValidCron('0 9 * * 1-5')).toBe(true)

    expect(isValidCron('* * * *')).toBe(false)
    expect(isValidCron('* * * * * *')).toBe(false)
    expect(isValidCron('@daily')).toBe(false)
  })

  it('returns safe fallbacks for expressions the UI cannot submit', () => {
    expect(describeCron('@daily')).toBe('@daily')
    expect(nextRuns('@daily', 'UTC')).toEqual([])
    expect(nextRuns('0 9 * * *', 'Nowhere/Nope')).toEqual([])
  })
})
