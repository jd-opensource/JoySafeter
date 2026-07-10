import { act, cleanup, render } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('next-runtime-env', () => ({
  env: vi.fn(() => undefined),
}))

import { useProjectStore } from '@/stores/managed/project-store'

import { useSessionStream } from './sse'

const dom = new JSDOM('<!doctype html><html><body></body></html>')
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement

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

function sseResponseText(text: string) {
  return new Response(text, {
    status: 200,
    headers: { 'content-type': 'text/event-stream' },
  })
}

function openSseResponse() {
  return new Response(
    new ReadableStream({
      start() {
        // Keep the stream open until the hook aborts its fetch controller.
      },
    }),
    {
      status: 200,
      headers: { 'content-type': 'text/event-stream' },
    },
  )
}

function wait(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

describe('useSessionStream', () => {
  let originalFetch: typeof fetch | undefined

  beforeEach(() => {
    originalFetch = globalThis.fetch
  })

  afterEach(() => {
    cleanup()
    vi.useRealTimers()
    if (originalFetch) {
      globalThis.fetch = originalFetch
    } else {
      delete (globalThis as { fetch?: typeof fetch }).fetch
    }
    vi.restoreAllMocks()
    useProjectStore.setState({ currentOrgId: null, currentProjectId: null })
  })

  it('resets events and after_seq when switching sessions', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.includes('/sessions/session-a/')) {
        return Promise.resolve(sseResponse({ id: 'evt-a', type: 'user.message', seq: 9 }))
      }
      if (url.includes('/sessions/session-b/')) {
        return Promise.resolve(sseResponse({ id: 'evt-b', type: 'user.message', seq: 1 }))
      }
      return Promise.resolve(new Response('', { status: 404 }))
    })
    globalThis.fetch = fetchMock as unknown as typeof fetch

    const { getByTestId, rerender } = render(<HookHarness sessionId="session-a" />)

    await act(async () => {
      await wait(80)
    })
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(String(fetchMock.mock.calls[0][0])).toContain(
      '/sessions/session-a/events/stream?after_seq=0',
    )
    expect(getByTestId('events').textContent).toContain('evt-a')

    rerender(<HookHarness sessionId="session-b" />)

    await act(async () => {
      await wait(80)
    })
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(String(fetchMock.mock.calls[1][0])).toContain(
      '/sessions/session-b/events/stream?after_seq=0',
    )
    expect(getByTestId('events').textContent).toContain('evt-b')
    expect(getByTestId('events').textContent).not.toContain('evt-a')
  })

  it('reconnects the stream when managed project context changes', async () => {
    useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-a' })
    const signals: AbortSignal[] = []
    const headers: Record<string, string>[] = []
    const fetchMock = vi.fn((_url: string, init?: RequestInit) => {
      signals.push(init?.signal as AbortSignal)
      headers.push((init?.headers || {}) as Record<string, string>)
      return Promise.resolve(openSseResponse())
    })
    globalThis.fetch = fetchMock as unknown as typeof fetch

    render(<HookHarness sessionId="session-a" />)

    await act(async () => {
      await wait(20)
    })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(headers[0]['X-Org-Id']).toBe('org-a')
    expect(headers[0]['X-Project-Id']).toBe('project-a')

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-b', currentProjectId: 'project-b' })
      await wait(20)
    })

    expect(signals[0].aborted).toBe(true)
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(headers[1]['X-Org-Id']).toBe('org-b')
    expect(headers[1]['X-Project-Id']).toBe('project-b')
  })

  it('keeps a final SSE data frame when the stream closes without a trailing newline', async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve(
        sseResponseText(
          `data: ${JSON.stringify({ id: 'evt-final', type: 'user.message', seq: 1 })}`,
        ),
      ),
    )
    globalThis.fetch = fetchMock as unknown as typeof fetch

    const { getByTestId } = render(<HookHarness sessionId="session-a" />)

    await act(async () => {
      await wait(80)
    })

    expect(getByTestId('events').textContent).toContain('evt-final')
  })
})
