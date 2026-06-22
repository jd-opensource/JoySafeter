/**
 * Auth client export (enhanced security version)
 * Uses JWT + HttpOnly Cookie authentication
 */
import { useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'

import { ApiError } from '@/lib/api-client'

import {
  authApi,
  signIn,
  signUp,
  signOut,
  onSessionChange,
  type AuthUser,
  type AuthSession,
} from './api-client'

// ==================== Type Exports ====================
export type { AuthUser, AuthSession }
export { ApiError as AuthError }

// ==================== Session Hook ====================
export type SessionHookResult = {
  data: { user: AuthUser | null } | null
  isPending: boolean
  error: Error | null
  refetch: () => Promise<void>
}

const SESSION_REFRESH_INTERVAL_MS = 10 * 60 * 1000
const SESSION_REFRESH_THROTTLE_MS = 60 * 1000

let sessionRefreshRefCount = 0
let sessionRefreshTimer: number | null = null
let sessionRefreshQueryClient: QueryClient | null = null
let lastSessionRefreshAttemptAt = 0

async function runSilentSessionRefresh(queryClient: QueryClient): Promise<void> {
  const now = Date.now()
  if (now - lastSessionRefreshAttemptAt < SESSION_REFRESH_THROTTLE_MS) {
    return
  }
  lastSessionRefreshAttemptAt = now

  try {
    await authApi.refreshToken()
    await queryClient.invalidateQueries({ queryKey: ['session'] })
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      queryClient.setQueryData(['session'], null)
    }
  }
}

function runVisibleSilentSessionRefresh(): void {
  if (!sessionRefreshQueryClient) return
  if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return
  void runSilentSessionRefresh(sessionRefreshQueryClient)
}

function startSilentSessionRefresh(queryClient: QueryClient): () => void {
  if (typeof window === 'undefined') return () => {}

  sessionRefreshQueryClient = queryClient
  sessionRefreshRefCount += 1

  if (!sessionRefreshTimer) {
    sessionRefreshTimer = window.setInterval(
      runVisibleSilentSessionRefresh,
      SESSION_REFRESH_INTERVAL_MS,
    )
    window.addEventListener('focus', runVisibleSilentSessionRefresh)
    document.addEventListener('visibilitychange', runVisibleSilentSessionRefresh)
  }

  return () => {
    sessionRefreshRefCount = Math.max(0, sessionRefreshRefCount - 1)
    if (sessionRefreshRefCount > 0) return

    if (sessionRefreshTimer) {
      window.clearInterval(sessionRefreshTimer)
      sessionRefreshTimer = null
    }
    window.removeEventListener('focus', runVisibleSilentSessionRefresh)
    document.removeEventListener('visibilitychange', runVisibleSilentSessionRefresh)
    sessionRefreshQueryClient = null
  }
}

/**
 * Hook to get current session (optimized with React Query)
 */
export function useSession(): SessionHookResult {
  const queryClient = useQueryClient()

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ['session'],
    queryFn: async () => {
      const response = await authApi.getSession()
      return response?.user ? { user: response.user } : null
    },
    staleTime: 5 * 60 * 1000,
    retry: (failureCount, error) =>
      !(error instanceof ApiError && error.status === 401) && failureCount < 2,
    retryDelay: 1000,
    refetchOnReconnect: true,
    refetchOnWindowFocus: true,
  })

  useEffect(() => {
    const unsubscribe = onSessionChange((type) => {
      if (type === 'logout') {
        queryClient.setQueryData(['session'], null)
      } else {
        refetch()
      }
    })
    return unsubscribe
  }, [queryClient, refetch])

  useEffect(() => {
    if (!data?.user) return
    return startSilentSessionRefresh(queryClient)
  }, [data?.user, queryClient])

  return {
    data: data ?? null,
    isPending,
    error: error as Error | null,
    refetch: async () => {
      await refetch()
    },
  }
}

// ==================== Client Object (compatible with Better Auth) ====================
export const client = {
  signIn: {
    email: signIn.email,
    emailOtp: signIn.emailOtp,
  },
  signUp: {
    email: signUp.email,
  },
  signOut,
  getSession: authApi.getSession,
  refreshToken: authApi.refreshToken,
  forgetPassword: authApi.forgetPassword,
  resetPassword: authApi.resetPassword,
  changePassword: authApi.changePassword,
  verifyEmail: authApi.verifyEmail,
  resendVerificationEmail: authApi.resendVerificationEmail,
  emailOtp: {
    sendVerificationOtp: authApi.sendVerificationOtp,
  },
}

// ==================== Exports ====================
export { signIn, signUp, signOut, authApi, onSessionChange }

/**
 * useActiveOrganization placeholder
 */
export function useActiveOrganization() {
  return { data: null, isPending: false, error: null }
}
