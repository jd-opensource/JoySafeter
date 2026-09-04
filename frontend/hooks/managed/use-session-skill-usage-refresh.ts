import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'

import { managedSessionSkillUsageQueryKey } from '@/lib/managed/session-client'
import type { SessionId } from '@/types/entity-id'

interface UseSessionSkillUsageRefreshOptions {
  isRunning: boolean
  scopeKey: string
  sessionId: SessionId
}

export function useSessionSkillUsageRefresh({
  isRunning,
  scopeKey,
  sessionId,
}: UseSessionSkillUsageRefreshOptions) {
  const queryClient = useQueryClient()
  const previousStateRef = useRef({ isRunning, scopeKey, sessionId })

  useEffect(() => {
    const previousState = previousStateRef.current
    previousStateRef.current = { isRunning, scopeKey, sessionId }

    if (previousState.scopeKey !== scopeKey || previousState.sessionId !== sessionId) return
    if (!previousState.isRunning || isRunning) return

    void queryClient.invalidateQueries({
      queryKey: managedSessionSkillUsageQueryKey(scopeKey, sessionId),
    })
  }, [isRunning, queryClient, scopeKey, sessionId])
}
