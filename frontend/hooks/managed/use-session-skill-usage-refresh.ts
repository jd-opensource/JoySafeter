import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'

interface UseSessionSkillUsageRefreshOptions {
  isRunning: boolean
  sessionScope: string
}

export function useSessionSkillUsageRefresh({
  isRunning,
  sessionScope,
}: UseSessionSkillUsageRefreshOptions) {
  const queryClient = useQueryClient()
  const previousStateRef = useRef({ isRunning, sessionScope })

  useEffect(() => {
    const previousState = previousStateRef.current
    previousStateRef.current = { isRunning, sessionScope }

    if (previousState.sessionScope !== sessionScope) return
    if (!previousState.isRunning || isRunning) return

    void queryClient.invalidateQueries({
      queryKey: ['session-skill-usage', sessionScope],
    })
  }, [isRunning, queryClient, sessionScope])
}
