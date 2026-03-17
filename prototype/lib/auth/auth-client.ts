/**
 * Mock auth client for prototype — no backend required.
 * Any valid email + any non-empty password will sign in.
 * Session stored in localStorage.
 */
'use client'

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'

// ==================== Types ====================

export interface AuthUser {
  id: string
  email: string
  name: string
  image?: string
}

export interface AuthSession {
  user: AuthUser
}

export class AuthError extends Error {
  code: string
  constructor(message: string, code = 'AUTH_ERROR') {
    super(message)
    this.code = code
    this.name = 'AuthError'
  }
}

export { AuthError as ApiError }

// ==================== Storage ====================

const SESSION_KEY = 'prototype_auth_session'

function getStoredSession(): { user: AuthUser } | null {
  if (typeof window === 'undefined') return null
  try {
    const raw = localStorage.getItem(SESSION_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

function setStoredSession(user: AuthUser | null): void {
  if (typeof window === 'undefined') return
  if (user) {
    localStorage.setItem(SESSION_KEY, JSON.stringify({ user }))
  } else {
    localStorage.removeItem(SESSION_KEY)
  }
}

// ==================== Event bus ====================

type SessionEventType = 'login' | 'logout'
const listeners: Array<(type: SessionEventType) => void> = []

export function onSessionChange(cb: (type: SessionEventType) => void): () => void {
  listeners.push(cb)
  return () => {
    const i = listeners.indexOf(cb)
    if (i > -1) listeners.splice(i, 1)
  }
}

// ==================== useSession hook ====================

export type SessionHookResult = {
  data: { user: AuthUser | null } | null
  isPending: boolean
  error: Error | null
  refetch: () => Promise<void>
}

export function useSession(): SessionHookResult {
  const queryClient = useQueryClient()

  const { data, isPending, refetch } = useQuery({
    queryKey: ['session'],
    queryFn: () => getStoredSession(),
    staleTime: Infinity,
    retry: false,
  })

  useEffect(() => {
    return onSessionChange((type) => {
      if (type === 'logout') {
        queryClient.setQueryData(['session'], null)
      } else {
        refetch()
      }
    })
  }, [queryClient, refetch])

  return {
    data: data ?? null,
    isPending,
    error: null,
    refetch: async () => { await refetch() },
  }
}

// ==================== signIn ====================

function buildUser(email: string): AuthUser {
  const name = email
    .split('@')[0]
    .replace(/[._-]/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
  return { id: `user-${Date.now()}`, email, name }
}

const signIn = {
  emailOtp: async (_params: { email: string; otp: string }) => {
    await new Promise((r) => setTimeout(r, 400))
    return { data: { user: null }, error: null }
  },
  email: async (
    { email, password }: { email: string; password: string; callbackURL?: string },
    options?: { onError?: (ctx: { error: AuthError }) => void }
  ) => {
    await new Promise((r) => setTimeout(r, 500))

    if (!email || !password) {
      const err = new AuthError('Email and password are required', 'MISSING_CREDENTIALS')
      options?.onError?.({ error: err })
      return { data: null, error: err }
    }

    const emailOk = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())
    if (!emailOk) {
      const err = new AuthError('Invalid email format', 'INVALID_EMAIL')
      options?.onError?.({ error: err })
      return { data: null, error: err }
    }

    const user = buildUser(email.trim().toLowerCase())
    setStoredSession(user)
    listeners.forEach((cb) => cb('login'))
    return { data: { user }, error: null }
  },
}

const signUp = {
  email: async (
    { email, name }: { email: string; name?: string; password?: string },
    _options?: { onError?: (ctx: { error: AuthError }) => void }
  ) => {
    await new Promise((r) => setTimeout(r, 500))
    const user: AuthUser = {
      id: `user-${Date.now()}`,
      email: email.trim().toLowerCase(),
      name: name || buildUser(email).name,
    }
    setStoredSession(user)
    listeners.forEach((cb) => cb('login'))
    return { data: { user }, error: null }
  },
}

async function signOut(_options?: unknown): Promise<void> {
  setStoredSession(null)
  listeners.forEach((cb) => cb('logout'))
}

// ==================== client object ====================

export const client = {
  signIn,
  signUp,
  signOut,
  emailOtp: {
    sendVerificationOtp: async (_params: { email: string; type?: string }) => ({ data: null, error: null }),
  },
  getSession: () => Promise.resolve(getStoredSession()),
  refreshToken: () => Promise.resolve(null),
  forgetPassword: async (_params: unknown) => ({ data: null, error: null }),
  resetPassword: async (_params: unknown) => ({ data: null, error: null }),
  changePassword: async (_params: unknown) => ({ data: null, error: null }),
  verifyEmail: async (_params: unknown) => ({ data: null, error: null }),
  resendVerificationEmail: async (_params: unknown) => ({ data: null, error: null }),
}

export { signIn, signUp, signOut }
export function clearCsrfToken(): void {}
export function clearTokens(): void {}
export function useActiveOrganization() {
  return { data: null, isPending: false, error: null }
}
