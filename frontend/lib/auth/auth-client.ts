/**
 * Auth client export (enhanced security version)
 * Uses JWT + HttpOnly Cookie authentication
 */
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'

import { ApiError, isUnauthorizedApiError } from '@/lib/api-client'

import {
  authApi,
  signIn,
  signUp,
  signOut,
  onSessionChange,
  type AuthUser,
  type AuthSession,
} from './api-client'
import { clearAuthenticatedClientState } from './auth-lifecycle'
import { startSilentSessionRefresh } from './session-refresh'

// ==================== Type Exports ====================
export type { AuthUser, AuthSession }
export { ApiError }

// ==================== Session Hook ====================
export type SessionHookResult = {
  data: { user: AuthUser | null } | null
  isPending: boolean
  error: Error | null
  refetch: () => Promise<void>
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
    retry: (failureCount, error) => !isUnauthorizedApiError(error) && failureCount < 2,
    retryDelay: 1000,
    refetchOnReconnect: true,
    refetchOnWindowFocus: true,
  })

  useEffect(() => {
    const unsubscribe = onSessionChange((type) => {
      if (type === 'logout') {
        clearAuthenticatedClientState(queryClient)
        queryClient.setQueryData(['session'], null)
      } else if (type === 'signin') {
        clearAuthenticatedClientState(queryClient)
        refetch()
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

// ==================== Client Object ====================
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
