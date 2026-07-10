import { JSDOM } from 'jsdom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('next-runtime-env', () => ({
  env: vi.fn(() => undefined),
}))

import { useProjectStore } from '@/stores/managed/project-store'

import { ApiError, apiFetch, apiPost, apiStream } from './api-client'
import { clearCsrfToken, setCsrfToken } from './auth/csrf'

const originalFetch = globalThis.fetch
const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement
globalThis.localStorage = dom.window.localStorage

describe('api-client error contract', () => {
  beforeEach(() => {
    localStorage.clear()
    clearCsrfToken()
    document.cookie = 'csrf_token=; Max-Age=0; path=/'
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
    vi.restoreAllMocks()
    clearCsrfToken()
    localStorage.clear()
    document.cookie = 'csrf_token=; Max-Age=0; path=/'
    useProjectStore.setState({ currentOrgId: null, currentProjectId: null })
  })

  it('preserves backend error payload and response trace id', async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValue(
        new Response(
          JSON.stringify({
            code: 'SERVICE_UNAVAILABLE',
            message: 'Failed to enqueue task',
            data: { queue: 'joysafeter:global_queue' },
            source: 'runtime',
            retryable: true,
            user_action: 'retry',
          }),
          {
            status: 503,
            statusText: 'Service Unavailable',
            headers: { 'content-type': 'application/json', 'x-trace-id': 'trace-123' },
          },
        ),
      ) as typeof fetch

    try {
      await apiFetch('tasks', { withAuth: false })
      throw new Error('expected apiFetch to reject')
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError)
      const apiError = error as ApiError
      expect(apiError.status).toBe(503)
      expect(apiError.code).toBe('SERVICE_UNAVAILABLE')
      expect(apiError.message).toBe('Failed to enqueue task')
      expect(apiError.source).toBe('runtime')
      expect(apiError.retryable).toBe(true)
      expect(apiError.userAction).toBe('retry')
      expect(apiError.traceId).toBe('trace-123')
      expect(apiError.data).toEqual({ queue: 'joysafeter:global_queue' })
    }
  })

  it('keeps non-json error bodies instead of collapsing to status text', async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValue(
        new Response('upstream gateway exploded', {
          status: 502,
          statusText: 'Bad Gateway',
          headers: { 'content-type': 'text/plain', 'x-trace-id': 'trace-502' },
        }),
      ) as typeof fetch

    try {
      await apiFetch('tasks', { withAuth: false })
      throw new Error('expected apiFetch to reject')
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError)
      const apiError = error as ApiError
      expect(apiError.code).toBe('HTTP_502')
      expect(apiError.message).toBe('upstream gateway exploded')
      expect(apiError.detail).toBe('upstream gateway exploded')
      expect(apiError.traceId).toBe('trace-502')
    }
  })

  it('does not drop falsey request bodies', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ success: true, data: { ok: true } }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    globalThis.fetch = fetchMock as typeof fetch

    await apiPost('echo', '', { withAuth: false })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0][1]?.body).toBe(JSON.stringify(''))
  })

  it('sends managed context headers on streaming requests', async () => {
    useProjectStore.setState({ currentOrgId: 'org-1', currentProjectId: 'project-1' })
    const fetchMock = vi.fn().mockResolvedValue(
      new Response('data: [DONE]\n\n', {
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
      }),
    )
    globalThis.fetch = fetchMock as typeof fetch

    await apiStream('quickstart/chat', { messages: [] })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0][1]?.headers).toMatchObject({
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      'X-Org-Id': 'org-1',
      'X-Project-Id': 'project-1',
    })
  })

  it('uses the refreshed csrf cookie after another tab completes token refresh', async () => {
    setCsrfToken('old-csrf')
    localStorage.setItem(
      'auth_refresh_lock',
      JSON.stringify({ owner: 'other-tab', expiresAt: Number.MAX_SAFE_INTEGER }),
    )
    localStorage.setItem('auth_refresh_completed_at', String(Number.MAX_SAFE_INTEGER))

    const seenHeaders: Record<string, string>[] = []
    const fetchMock = vi
      .fn()
      .mockImplementationOnce((_url: string, init?: RequestInit) => {
        seenHeaders.push({ ...((init?.headers || {}) as Record<string, string>) })
        document.cookie = 'csrf_token=new-csrf; path=/'
        return Promise.resolve(
          new Response(JSON.stringify({ code: 'UNAUTHORIZED', message: 'expired' }), {
            status: 401,
            statusText: 'Unauthorized',
          }),
        )
      })
      .mockImplementationOnce((_url: string, init?: RequestInit) => {
        seenHeaders.push({ ...((init?.headers || {}) as Record<string, string>) })
        return Promise.resolve(
          new Response(JSON.stringify({ success: true, data: { ok: true } }), {
            status: 200,
            headers: { 'content-type': 'application/json' },
          }),
        )
      })
    globalThis.fetch = fetchMock as typeof fetch

    await expect(apiFetch('tasks')).resolves.toEqual({ ok: true })

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(seenHeaders[0]).toMatchObject({
      'X-CSRF-Token': 'old-csrf',
    })
    expect(seenHeaders[1]).toMatchObject({
      'X-CSRF-Token': 'new-csrf',
    })
  })
})
