import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('next-runtime-env', () => ({
  env: vi.fn(() => undefined),
}))

import { ApiError, apiFetch, apiPost } from './api-client'

describe('api-client error contract', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('preserves backend error payload and response trace id', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
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
      ),
    )

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
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response('upstream gateway exploded', {
          status: 502,
          statusText: 'Bad Gateway',
          headers: { 'content-type': 'text/plain', 'x-trace-id': 'trace-502' },
        }),
      ),
    )

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
    vi.stubGlobal('fetch', fetchMock)

    await apiPost('echo', '', { withAuth: false })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0][1]?.body).toBe(JSON.stringify(''))
  })
})
