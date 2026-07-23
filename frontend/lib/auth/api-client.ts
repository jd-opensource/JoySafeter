/**
 * Auth API Client
 *
 * Handles authentication-related API requests using the unified API client
 */
import CryptoJS from 'crypto-js'

import {
  ApiError,
  createApiError,
  isUnauthorizedApiError,
  managedGet,
  managedPost,
  refreshAccessTokenOrRelogin,
} from '@/lib/api-client'
import { createLogger } from '@/lib/logs/console/logger'

import { setCsrfToken, clearCsrfToken } from './csrf'
import { notifySessionChange, onSessionChange, type SessionChangeType } from './session-events'

const logger = createLogger('AuthAPI')

// ==================== Type Definitions ====================
export interface AuthUser {
  id: string
  email: string
  name: string
  image?: string | null
  emailVerified: boolean
  isSuperUser: boolean
  createdAt?: string
  updatedAt?: string
}

export interface AuthSession {
  id: string
  token: string
  expiresAt: string
  userId: string
  activeOrganizationId?: string | null
}

export interface LoginResponse {
  user: AuthUser
  access_token: string
  refresh_token?: string
  csrf_token?: string
  token_type: string
  expires_in: number
}

export interface SignUpResponse {
  user: AuthUser
  access_token: string
  refresh_token?: string
  csrf_token?: string
  token_type: string
  expires_in: number
}

export interface SessionResponse {
  user: AuthUser | null
}

// Use unified ApiError, but keep backward-compatible AuthError alias
export { ApiError as AuthError }

// ==================== Session Management ====================
export { onSessionChange, type SessionChangeType }

// ==================== Utility Functions ====================
function hashPassword(password: string): string {
  return CryptoJS.SHA256(password).toString()
}

// ==================== Auth API ====================
export const authApi = {
  async signInEmail(params: {
    email: string
    password: string
    callbackURL?: string
  }): Promise<LoginResponse> {
    const hashedPassword = hashPassword(params.password)
    const response = await managedPost<LoginResponse>(
      'auth/sign-in/email',
      {
        email: params.email,
        password: hashedPassword,
      },
      { withAuth: false, skipManagedContext: true },
    )

    if (response.csrf_token) {
      setCsrfToken(response.csrf_token)
    }

    notifySessionChange('signin')
    return response
  },

  async signUpEmail(params: {
    email: string
    password: string
    name: string
  }): Promise<SignUpResponse> {
    const hashedPassword = hashPassword(params.password)
    const response = await managedPost<SignUpResponse>(
      'auth/sign-up/email',
      {
        email: params.email,
        password: hashedPassword,
        name: params.name,
      },
      { withAuth: false, skipManagedContext: true },
    )

    if (response.csrf_token) {
      setCsrfToken(response.csrf_token)
    }

    notifySessionChange('signin')
    return response
  },

  async signOut(): Promise<void> {
    try {
      await managedPost('auth/logout', undefined, { skipManagedContext: true })
    } catch (error) {
      logger.warn('Logout request failed, clearing tokens anyway', { error })
    } finally {
      clearCsrfToken()
      notifySessionChange('logout')
    }
  },

  async getSession(): Promise<SessionResponse | null> {
    const fetchSession = async (): Promise<SessionResponse | null> => {
      const response = await managedGet<{
        user: {
          id: string
          email: string
          name: string
          image?: string
          email_verified: boolean
          is_super_user: boolean
        } | null
      }>('auth/session', { skipManagedContext: true })

      if (!response?.user) return null

      return {
        user: {
          id: response.user.id,
          email: response.user.email,
          name: response.user.name,
          image: response.user.image,
          emailVerified: response.user.email_verified,
          isSuperUser: response.user.is_super_user,
        },
      }
    }

    try {
      return await fetchSession()
    } catch (error) {
      if (isUnauthorizedApiError(error)) {
        // The access-token cookie expired (common after switching tabs, when
        // refetchOnWindowFocus re-checks the session). Try a one-shot refresh
        // using the long-lived HttpOnly refresh-token cookie before concluding
        // the user is logged out — otherwise a still-valid session would be
        // torn down and the AuthGuard would bounce to /signin.
        try {
          await refreshAccessTokenOrRelogin()
          return await fetchSession()
        } catch (refreshError) {
          if (isUnauthorizedApiError(refreshError)) {
            // Refresh token is also invalid/expired — genuinely logged out.
            return null
          }
          throw refreshError
        }
      }
      logger.warn('Failed to get session', { error })
      throw error
    }
  },

  async refreshToken(): Promise<void> {
    await refreshAccessTokenOrRelogin()
  },

  async forgetPassword(params: { email: string; redirectTo?: string }): Promise<void> {
    await managedPost(
      'auth/forgot-password',
      { email: params.email, redirect_to: params.redirectTo },
      { skipManagedContext: true },
    )
  },

  async resetPassword(params: { token: string; newPassword: string }): Promise<void> {
    const hashedPassword = hashPassword(params.newPassword)
    await managedPost(
      'auth/reset-password',
      {
        token: params.token,
        new_password: hashedPassword,
      },
      { skipManagedContext: true },
    )
  },

  async changePassword(params: { oldPassword: string; newPassword: string }): Promise<void> {
    await managedPost('auth/me/change-password', {
      old_password: params.oldPassword,
      new_password: params.newPassword,
    })
  },

  async verifyEmail(token: string): Promise<void> {
    await managedPost('auth/verify-email', { token }, { skipManagedContext: true })
  },

  async resendVerificationEmail(): Promise<void> {
    await managedPost('auth/resend-verification')
  },

  async sendVerificationOtp(params: {
    email: string
    type: 'sign-in' | 'email-verification' | 'forget-password'
  }): Promise<void> {
    await managedPost(
      'auth/email-otp/send',
      {
        email: params.email,
        type: params.type,
      },
      { skipManagedContext: true },
    )
  },

  async signInEmailOtp(params: { email: string; otp: string }): Promise<LoginResponse> {
    const response = await managedPost<LoginResponse>(
      'auth/sign-in/email-otp',
      {
        email: params.email,
        otp: params.otp,
      },
      { withAuth: false, skipManagedContext: true },
    )

    if (response.csrf_token) {
      setCsrfToken(response.csrf_token)
    }

    notifySessionChange('signin')
    return response
  },
}

// ==================== Convenience Exports ====================
export const signIn = {
  email: async (
    params: { email: string; password: string; callbackURL?: string },
    options?: { onError?: (ctx: { error: ApiError }) => void },
  ) => {
    try {
      const result = await authApi.signInEmail(params)
      return { data: result, error: null }
    } catch (error) {
      const apiError =
        error instanceof ApiError
          ? error
          : createApiError(0, 'Unknown Error', {
              code: 'UNKNOWN_ERROR',
              message: String(error),
              data: null,
            })
      options?.onError?.({ error: apiError })
      return { data: null, error: apiError }
    }
  },
  emailOtp: async (
    params: { email: string; otp: string },
    options?: { onError?: (ctx: { error: ApiError }) => void },
  ) => {
    try {
      const result = await authApi.signInEmailOtp(params)
      return { data: result, error: null }
    } catch (error) {
      const apiError =
        error instanceof ApiError
          ? error
          : createApiError(0, 'Unknown Error', {
              code: 'UNKNOWN_ERROR',
              message: String(error),
              data: null,
            })
      options?.onError?.({ error: apiError })
      return { data: null, error: apiError }
    }
  },
}

export const signUp = {
  email: async (
    params: { email: string; password: string; name: string },
    options?: { onError?: (ctx: { error: ApiError }) => void },
  ) => {
    try {
      const result = await authApi.signUpEmail(params)
      return { data: result, error: null }
    } catch (error) {
      const apiError =
        error instanceof ApiError
          ? error
          : createApiError(0, 'Unknown Error', {
              code: 'UNKNOWN_ERROR',
              message: String(error),
              data: null,
            })
      options?.onError?.({ error: apiError })
      return { data: null, error: apiError }
    }
  },
}

export const signOut = async () => {
  await authApi.signOut()
}
