/**
 * Auth API Client
 *
 * Handles authentication-related API requests using the unified API client
 */
import CryptoJS from 'crypto-js'

import { apiGet, apiPost, ApiError, refreshAccessTokenOrRelogin } from '@/lib/api-client'
import { createLogger } from '@/lib/logs/console/logger'

import { setCsrfToken, getCsrfToken, clearCsrfToken } from './csrf'

const logger = createLogger('AuthAPI')

// ==================== Re-export CSRF functions (maintain backward compatibility) ====================
export { setCsrfToken, getCsrfToken, clearCsrfToken }

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
const SESSION_CHANGE_KEY = 'auth_session_change'

function notifySessionChange(type: 'signin' | 'logout' | 'refresh'): void {
  if (typeof window === 'undefined') return
  try {
    const event = { type, timestamp: Date.now() }
    localStorage.setItem(SESSION_CHANGE_KEY, JSON.stringify(event))
    setTimeout(() => localStorage.removeItem(SESSION_CHANGE_KEY), 100)
  } catch (e) {
    console.warn('Failed to notify session change:', e)
  }
}

export function onSessionChange(callback: (type: 'signin' | 'logout' | 'refresh') => void): () => void {
  if (typeof window === 'undefined') return () => {}

  const handler = (e: StorageEvent) => {
    if (e.key === SESSION_CHANGE_KEY && e.newValue) {
      try {
        const event = JSON.parse(e.newValue)
        callback(event.type)
      } catch { /* ignore */ }
    }
  }

  window.addEventListener('storage', handler)
  return () => window.removeEventListener('storage', handler)
}

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
    const response = await apiPost<LoginResponse>('auth/sign-in/email', {
      email: params.email,
      password: hashedPassword,
    })

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
    const response = await apiPost<SignUpResponse>('auth/sign-up/email', {
      email: params.email,
      password: hashedPassword,
      name: params.name,
    })

    if (response.csrf_token) {
      setCsrfToken(response.csrf_token)
    }

    notifySessionChange('signin')
    return response
  },

  async signOut(): Promise<void> {
    try {
      await apiPost('auth/logout')
    } catch (error) {
      logger.warn('Logout request failed, clearing tokens anyway', { error })
    } finally {
      clearCsrfToken()
      notifySessionChange('logout')
    }
  },

  async getSession(): Promise<SessionResponse | null> {
    try {
      const response = await apiGet<{
        user: { id: string; email: string; name: string; image?: string; email_verified: boolean; is_super_user: boolean } | null
      }>('auth/session')

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
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        return null
      }
      logger.warn('Failed to get session', { error })
      return null
    }
  },

  async refreshToken(): Promise<void> {
    await refreshAccessTokenOrRelogin()
    notifySessionChange('refresh')
  },

  async forgetPassword(params: { email: string; redirectTo?: string }): Promise<void> {
    await apiPost('auth/forgot-password', { email: params.email, redirect_to: params.redirectTo })
  },

  async resetPassword(params: { token: string; newPassword: string }): Promise<void> {
    const hashedPassword = hashPassword(params.newPassword)
    await apiPost('auth/reset-password', {
      token: params.token,
      new_password: hashedPassword,
    })
  },

  async changePassword(params: { oldPassword: string; newPassword: string }): Promise<void> {
    await apiPost('auth/me/change-password', {
      old_password: params.oldPassword,
      new_password: params.newPassword,
    })
  },

  async verifyEmail(token: string): Promise<void> {
    await apiPost('auth/verify-email', { token })
  },

  async resendVerificationEmail(): Promise<void> {
    await apiPost('auth/resend-verification')
  },

  async sendVerificationOtp(params: {
    email: string
    type: 'sign-in' | 'email-verification' | 'forget-password'
  }): Promise<void> {
    await apiPost('auth/email-otp/send', {
      email: params.email,
      type: params.type,
    })
  },

  async signInEmailOtp(params: { email: string; otp: string }): Promise<LoginResponse> {
    const response = await apiPost<LoginResponse>('auth/sign-in/email-otp', {
      email: params.email,
      otp: params.otp,
    })

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
    options?: { onError?: (ctx: { error: ApiError }) => void }
  ) => {
    try {
      const result = await authApi.signInEmail(params)
      return { data: result, error: null }
    } catch (error) {
      const apiError = error instanceof ApiError ? error : new ApiError(0, 'Unknown Error', String(error))
      options?.onError?.({ error: apiError })
      return { data: null, error: apiError }
    }
  },
  emailOtp: async (
    params: { email: string; otp: string },
    options?: { onError?: (ctx: { error: ApiError }) => void }
  ) => {
    try {
      const result = await authApi.signInEmailOtp(params)
      return { data: result, error: null }
    } catch (error) {
      const apiError = error instanceof ApiError ? error : new ApiError(0, 'Unknown Error', String(error))
      options?.onError?.({ error: apiError })
      return { data: null, error: apiError }
    }
  },
}

export const signUp = {
  email: async (
    params: { email: string; password: string; name: string },
    options?: { onError?: (ctx: { error: ApiError }) => void }
  ) => {
    try {
      const result = await authApi.signUpEmail(params)
      return { data: result, error: null }
    } catch (error) {
      const apiError = error instanceof ApiError ? error : new ApiError(0, 'Unknown Error', String(error))
      options?.onError?.({ error: apiError })
      return { data: null, error: apiError }
    }
  },
}

export const signOut = async () => {
  await authApi.signOut()
}
