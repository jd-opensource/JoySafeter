import { act, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('next-runtime-env', () => ({
  env: vi.fn(() => undefined),
}))

import { useProjectStore } from '@/stores/managed/project-store'

import { useSessionStream } from './sse'

function HookHarness({ sessionId }: { sessionId: string }) {
  const { events } = useSessionStream(sessionId, true)
  return <div data-testid="events">{events.map((event) => event.id).join(',')}</div>
}

function sseResponse(event: object) {
  return new Response(`data: ${JSON.stringify(event)}\n\n`, {
    status: 200,
    headers: { 'content-type': 'text/event-stream' },
  })
}

describe('useSessionStream', () => {
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
    useProjectStore.setState({ currentOrgId: null, currentProjectId: null })
  })

  it('resets events and after_seq when switching sessions', async () => {
    // Fake timers keep the 500ms reconnect from firing so fetch call counts
    // stay deterministic. We advance ~60ms per phase to drive the connect()
    // promise chain and the 50ms batch flush, then assert synchronously —
    // testing-library's waitFor cannot be used here because it polls on real
    // timers that vi.useFakeTimers() freezes.
    vi.useFakeTimers()
    const fetchMock = vi.fn((url: string) => {
      if (url.includes('/sessions/session-a/')) {
        return Promise.resolve(sseResponse({ id: 'evt-a', type: 'user.message', seq: 9 }))
      }
      if (url.includes('/sessions/session-b/')) {
        return Promise.resolve(sseResponse({ id: 'evt-b', type: 'user.message', seq: 1 }))
      }
      return Promise.resolve(new Response('', { status: 404 }))
    })
    vi.stubGlobal('fetch', fetchMock)

    const { rerender } = render(<HookHarness sessionId="session-a" />)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60)
    })
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(String(fetchMock.mock.calls[0][0])).toContain(
      '/sessions/session-a/events/stream?after_seq=0',
    )
    expect(screen.getByTestId('events')).toHaveTextContent('evt-a')

    rerender(<HookHarness sessionId="session-b" />)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60)
    })
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(String(fetchMock.mock.calls[1][0])).toContain(
      '/sessions/session-b/events/stream?after_seq=0',
    )
    expect(screen.getByTestId('events')).toHaveTextContent('evt-b')
    expect(screen.getByTestId('events')).not.toHaveTextContent('evt-a')
  })
})
