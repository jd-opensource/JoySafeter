import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'

import type { AuthUser } from '@/lib/auth/api-client'

/**
 * Safe user information type (does not contain sensitive data)
 * Only stores basic information for display
 */
interface SafeUserInfo {
  id: string
  email: string
  name: string
  image?: string | null
}

/**
 * Auth state interface
 *
 * Security notes:
 * - Token is no longer stored in localStorage (prevent XSS theft)
 * - Token is managed by backend via HttpOnly Cookie
 * - Only keep token reference in memory (for status checking)
 * - Only persist non-sensitive user display information
 */
interface AuthState {
  user: AuthUser | null
  // Token is only saved in memory, not persisted to localStorage
  // Actual authentication is done via HttpOnly Cookie
  token: string | null
  isLoading: boolean
  error: string | null
  isAuthenticated: boolean
  setAuth: (user: AuthUser | null, token: string | null) => void
  setUser: (user: AuthUser | null) => void
  setToken: (token: string | null) => void
  setLoading: (isLoading: boolean) => void
  setError: (error: string | null) => void
  clearAuth: () => void
}

/**
 * Extract safe display information from complete user object
 */
function extractSafeUserInfo(user: AuthUser | null): SafeUserInfo | null {
  if (!user) return null
  return {
    id: user.id,
    email: user.email,
    name: user.name,
    image: user.image,
  }
}

/**
 * Auth Store
 * Manages user authentication state
 *
 * Security improvements:
 * 1. Token is no longer persisted to localStorage (prevent XSS attack theft)
 * 2. Authentication state is managed via HttpOnly Cookie (set by server)
 * 3. Only persist non-sensitive user display information
 * 4. Use sessionStorage instead of localStorage (auto-clear on tab close)
 */
export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      token: null,  // Memory-only state, not persisted
      isLoading: false,
      error: null,
      get isAuthenticated() {
        const state = get()
        // Authentication status based on user existence (actual authentication done via HttpOnly Cookie)
        return !!state.user
      },
      setAuth: (user, token) => set({ user, token }),
      setUser: (user) => set({ user }),
      setToken: (token) => set({ token }),
      setLoading: (isLoading) => set({ isLoading }),
      setError: (error) => set({ error }),
      clearAuth: () => set({ user: null, token: null, error: null }),
    }),
    {
      name: 'auth-state',
      // Use localStorage to store user display information (reduce loading on page refresh)
      // Note: Token is not stored here, authentication is managed by HttpOnly Cookie
      storage: createJSONStorage(() => {
        if (typeof window === 'undefined') {
          // SSR environment returns empty storage
          return {
            getItem: () => null,
            setItem: () => {},
            removeItem: () => {},
          }
        }
        return localStorage
      }),
      // Only persist non-sensitive user display information
      // Note: Token is no longer persisted!
      partialize: (state) => ({
        // Only store safe user display information
        user: extractSafeUserInfo(state.user) as AuthUser | null,
        // token is not persisted - managed by HttpOnly Cookie
      }),
      // Version control for migrating old data
      version: 2,
      migrate: (persistedState: any, version: number) => {
        if (version < 2) {
          // Migrate from old version: clear possibly stored token
          return {
            ...persistedState,
            token: null,  // Clear old token
          }
        }
        return persistedState as AuthState
      },
    }
  )
)

/**
 * Clear all authentication-related storage data
 * Used for thorough cleanup on logout
 */
export function clearAllAuthStorage(): void {
  if (typeof window === 'undefined') return

  // Clear auth data in sessionStorage
  sessionStorage.removeItem('auth-state')

  // Clear possibly remaining localStorage data (migrated from old version)
  localStorage.removeItem('auth-state')

  // Clear token refresh related locks
  localStorage.removeItem('is_other_tab_refreshing')
  localStorage.removeItem('last_refresh_time')
}
