import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'

import type { Session } from '@/types/managed'

import {
  findCachedSessionForDetail,
  getMessageInputPlaceholderKey,
  primeSessionDetailCache,
  refreshSessionEventsAfterMutation,
  shouldSendMessageFromKeyDown,
} from './page'

function sessionFixture(overrides: Partial<Session> = {}): Session {
  return {
    id: 'sess_019f4619-e72a-7eb3-b0cc-d0791661c9cc',
    title: 'EverOS',
    status: 'running',
    created_at: '2026-07-09T08:58:00.000Z',
    updated_at: '2026-07-15T05:21:00.000Z',
    agent: {
      id: 'agent-1',
      name: 'AI Agent 开源项目猎手-u33i',
      engine_kind: 'claude',
    },
    ...overrides,
  }
}

describe('session message input keyboard handling', () => {
  it('does not send while an IME composition is active', () => {
    expect(
      shouldSendMessageFromKeyDown({
        key: 'Enter',
        shiftKey: false,
        nativeEvent: { isComposing: true },
      }),
    ).toBe(false)
  })

  it('does not send for IME composition keyCode 229', () => {
    expect(
      shouldSendMessageFromKeyDown({
        key: 'Enter',
        shiftKey: false,
        nativeEvent: { isComposing: false, keyCode: 229 },
      }),
    ).toBe(false)
  })

  it('sends only on plain Enter after composition has ended', () => {
    expect(
      shouldSendMessageFromKeyDown({
        key: 'Enter',
        shiftKey: false,
        nativeEvent: { isComposing: false },
      }),
    ).toBe(true)

    expect(
      shouldSendMessageFromKeyDown({
        key: 'Enter',
        shiftKey: true,
        nativeEvent: { isComposing: false },
      }),
    ).toBe(false)
  })
})

describe('session events refresh handling', () => {
  it('keeps current events rendered while requesting a post-send refresh', () => {
    const eventsLoadedRef = { current: true }
    const loadEvents = vi.fn()

    refreshSessionEventsAfterMutation(eventsLoadedRef, loadEvents)

    expect(eventsLoadedRef.current).toBe(false)
    expect(loadEvents).toHaveBeenCalledTimes(1)
  })
})

describe('session message input visual state', () => {
  it('treats forced streaming as busy immediately after send', () => {
    expect(
      getMessageInputPlaceholderKey({
        isArchived: false,
        isRunning: false,
        streamForced: true,
      }),
    ).toBe('running')
  })

  it('keeps the archived placeholder highest priority', () => {
    expect(
      getMessageInputPlaceholderKey({
        isArchived: true,
        isRunning: true,
        streamForced: true,
      }),
    ).toBe('archived')
  })
})

describe('session detail transition cache', () => {
  it('primes the detail query cache before navigating from the session list', () => {
    const queryClient = new QueryClient()
    const session = sessionFixture()

    primeSessionDetailCache(queryClient, session)

    expect(queryClient.getQueryData(['session', session.id])).toEqual(session)
  })

  it('finds session initial data from a paginated sessions list cache', () => {
    const queryClient = new QueryClient()
    const session = sessionFixture()
    queryClient.setQueryData(['sessions', undefined, false, 10], {
      data: [session],
      has_more: false,
    })

    expect(findCachedSessionForDetail(queryClient, '019f4619-e72a-7eb3-b0cc-d0791661c9cc')).toEqual(session)
  })
})
