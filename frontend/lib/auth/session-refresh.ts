import type { QueryClient } from '@tanstack/react-query'

import { isUnauthorizedApiError } from '@/lib/api-client'

import { authApi } from './api-client'

const SESSION_REFRESH_INTERVAL_MS = 10 * 60 * 1000
const SESSION_REFRESH_THROTTLE_MS = 60 * 1000

let sessionRefreshRefCount = 0
let sessionRefreshTimer: number | null = null
let sessionRefreshQueryClient: QueryClient | null = null
const sessionRefreshClientRefs = new Map<QueryClient, number>()
let lastSessionRefreshAttemptAt = 0
let sessionRefreshGeneration = 0

function isRefreshLifecycleActive(queryClient: QueryClient, generation: number): boolean {
  return sessionRefreshGeneration === generation && sessionRefreshClientRefs.has(queryClient)
}

async function runSilentSessionRefresh(
  queryClient: QueryClient,
  generation: number,
): Promise<void> {
  const now = Date.now()
  if (now - lastSessionRefreshAttemptAt < SESSION_REFRESH_THROTTLE_MS) {
    return
  }
  lastSessionRefreshAttemptAt = now

  try {
    await authApi.refreshToken()
    if (!isRefreshLifecycleActive(queryClient, generation)) return
    await queryClient.invalidateQueries({ queryKey: ['session'], exact: true })
  } catch (error) {
    if (!isRefreshLifecycleActive(queryClient, generation)) return
    if (isUnauthorizedApiError(error)) {
      queryClient.setQueryData(['session'], null)
    }
  }
}

function runVisibleSilentSessionRefresh(): void {
  const queryClient = sessionRefreshQueryClient
  if (!queryClient) return
  if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return
  void runSilentSessionRefresh(queryClient, sessionRefreshGeneration)
}

export function startSilentSessionRefresh(queryClient: QueryClient): () => void {
  if (typeof window === 'undefined') return () => {}

  if (sessionRefreshRefCount === 0) {
    sessionRefreshGeneration += 1
  }
  sessionRefreshClientRefs.set(queryClient, (sessionRefreshClientRefs.get(queryClient) ?? 0) + 1)
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
    const currentClientRefCount = sessionRefreshClientRefs.get(queryClient) ?? 0
    if (currentClientRefCount <= 1) {
      sessionRefreshClientRefs.delete(queryClient)
    } else {
      sessionRefreshClientRefs.set(queryClient, currentClientRefCount - 1)
    }

    sessionRefreshRefCount = Math.max(0, sessionRefreshRefCount - 1)
    if (sessionRefreshQueryClient === queryClient) {
      sessionRefreshQueryClient = Array.from(sessionRefreshClientRefs.keys()).pop() ?? null
    }
    if (sessionRefreshRefCount > 0) return

    sessionRefreshGeneration += 1
    if (sessionRefreshTimer) {
      window.clearInterval(sessionRefreshTimer)
      sessionRefreshTimer = null
    }
    window.removeEventListener('focus', runVisibleSilentSessionRefresh)
    document.removeEventListener('visibilitychange', runVisibleSilentSessionRefresh)
    sessionRefreshQueryClient = null
  }
}
