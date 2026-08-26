import { beforeEach, describe, expect, it, vi } from 'vitest'

import { USER_ID } from '@/test-utils/entity-ids'

const { managedPostMock } = vi.hoisted(() => ({
  managedPostMock: vi.fn(),
}))

vi.mock('@/lib/api-client', () => {
  class ApiError extends Error {}

  return {
    ApiError,
    createApiError: vi.fn((status: number, name: string, body: { message: string }) =>
      Object.assign(new ApiError(body.message || name), { status }),
    ),
    isUnauthorizedApiError: vi.fn(() => false),
    managedGet: vi.fn(),
    managedPost: managedPostMock,
    refreshAccessTokenOrRelogin: vi.fn(),
  }
})

vi.mock('./csrf', () => ({
  clearCsrfToken: vi.fn(),
  setCsrfToken: vi.fn(),
}))

vi.mock('./session-events', () => ({
  notifySessionChange: vi.fn(),
  onSessionChange: vi.fn(),
}))

import { authApi } from './api-client'

describe('auth password transport contract', () => {
  beforeEach(() => {
    managedPostMock.mockReset()
    managedPostMock.mockImplementation((path: string) => {
      if (path === 'auth/sign-in/email' || path === 'auth/sign-up/email') {
        return Promise.resolve({
          user: {
            id: USER_ID,
            email: 'user@example.com',
            name: 'User',
            emailVerified: false,
            isSuperUser: false,
          },
          access_token: 'access-token',
          token_type: 'bearer',
          expires_in: 900,
        })
      }

      return Promise.resolve({})
    })
  })

  it('sends raw passwords for server-side adaptive hashing', async () => {
    await authApi.signInEmail({ email: 'user@example.com', password: 'Sign-In1!' })
    await authApi.signUpEmail({ email: 'user@example.com', name: 'User', password: 'Sign-Up1!' })
    await authApi.resetPassword({ token: 'reset-token', newPassword: 'Reset-Me1!' })
    await authApi.changePassword({ oldPassword: 'Old-One1!', newPassword: 'New-One1!' })

    expect(managedPostMock).toHaveBeenNthCalledWith(
      1,
      'auth/sign-in/email',
      { email: 'user@example.com', password: 'Sign-In1!' },
      { withAuth: false, skipManagedContext: true },
    )
    expect(managedPostMock).toHaveBeenNthCalledWith(
      2,
      'auth/sign-up/email',
      { email: 'user@example.com', name: 'User', password: 'Sign-Up1!' },
      { withAuth: false, skipManagedContext: true },
    )
    expect(managedPostMock).toHaveBeenNthCalledWith(
      3,
      'auth/reset-password',
      { token: 'reset-token', new_password: 'Reset-Me1!' },
      { skipManagedContext: true },
    )
    expect(managedPostMock).toHaveBeenNthCalledWith(4, 'auth/me/change-password', {
      old_password: 'Old-One1!',
      new_password: 'New-One1!',
    })
  })

  it.each([{}, 'proj_018f6f42-0a51-7cc4-98c8-4f6f0ca5f021'])(
    'rejects malformed login user IDs before returning auth state',
    async (id) => {
      managedPostMock.mockResolvedValueOnce({
        user: {
          id,
          email: 'user@example.com',
          name: 'User',
          emailVerified: false,
          isSuperUser: false,
        },
        access_token: 'access-token',
        token_type: 'bearer',
        expires_in: 900,
      })

      await expect(
        authApi.signInEmail({ email: 'user@example.com', password: 'Sign-In1!' }),
      ).rejects.toThrow(TypeError)
    },
  )
})
