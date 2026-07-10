import { JSDOM } from 'jsdom'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('next-runtime-env', () => ({
  env: vi.fn(() => undefined),
}))

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement
globalThis.localStorage = dom.window.localStorage

let onSessionChange: typeof import('./session-events').onSessionChange
let notifySessionChange: typeof import('./session-events').notifySessionChange
let publishRefreshCompleted: typeof import('./session-events').publishRefreshCompleted

describe('auth session events', () => {
  beforeAll(async () => {
    const sessionEventsModule = await import('./session-events')
    onSessionChange = sessionEventsModule.onSessionChange
    notifySessionChange = sessionEventsModule.notifySessionChange
    publishRefreshCompleted = sessionEventsModule.publishRefreshCompleted
  })

  beforeEach(() => {
    localStorage.clear()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
    localStorage.clear()
  })

  it('publishes refresh completion to same-tab listeners and storage waiters', () => {
    const events: string[] = []
    const unsubscribe = onSessionChange((type) => events.push(type))

    publishRefreshCompleted('auth_refresh_completed_at_test')
    unsubscribe()

    expect(Number(localStorage.getItem('auth_refresh_completed_at_test'))).toBeGreaterThan(0)
    expect(events).toEqual(['refresh'])
  })

  it('does not let an older storage cleanup remove a newer session event', () => {
    vi.useFakeTimers()
    let now = 1_767_225_600_000
    vi.spyOn(Date, 'now').mockImplementation(() => now)

    notifySessionChange('signin')

    vi.advanceTimersByTime(50)
    now += 50
    notifySessionChange('logout')

    vi.advanceTimersByTime(50)

    const storedEvent = JSON.parse(localStorage.getItem('auth_session_change') || '{}') as {
      type?: string
    }
    expect(storedEvent.type).toBe('logout')

    vi.advanceTimersByTime(50)

    expect(localStorage.getItem('auth_session_change')).toBeNull()
  })
})
