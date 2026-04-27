import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, refreshAccessTokenOrRelogin } from '../api-client'

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
})
