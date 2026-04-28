import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, apiFetch, refreshAccessTokenOrRelogin } from '../api-client'

describe('refreshAccessTokenOrRelogin', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('raises a canonical refresh-token-invalid error on 401', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response('', {
          status: 401,
          statusText: 'Unauthorized',
        }),
      ),
    )

    await expect(refreshAccessTokenOrRelogin()).rejects.toMatchObject<ApiError>({
      code: 'REFRESH_TOKEN_INVALID',
      message: 'Refresh token expired, please login again',
      status: 401,
    })
  })

  it('raises a canonical request-timeout error on abort', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockRejectedValue(Object.assign(new Error('Aborted'), { name: 'AbortError' })),
    )

    await expect(refreshAccessTokenOrRelogin()).rejects.toMatchObject<ApiError>({
      code: 'REQUEST_TIMEOUT',
      message: 'Token refresh timed out',
      status: 408,
    })
  })

  it('parses canonical error payloads without an error envelope', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            code: 'USER_NOT_FOUND',
            message: '用户不存在',
            data: null,
          }),
          {
            status: 404,
            statusText: 'Not Found',
            headers: { 'Content-Type': 'application/json' },
          },
        ),
      ),
    )

    await expect(apiFetch('users/1', { withAuth: false })).rejects.toMatchObject<ApiError>({
      code: 'USER_NOT_FOUND',
      message: '用户不存在',
      status: 404,
    })
  })
})
