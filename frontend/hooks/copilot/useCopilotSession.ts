/**
 * useCopilotSession - Hook for managing Copilot run state
 *
 * Tracks the current run_id (formerly session_id) via Run Center.
 */

import { useState, useEffect, useRef, useCallback } from 'react'

export function useCopilotSession(graphId?: string) {
  const [currentRunId, setCurrentRunId] = useState<string | null>(null)
  const hasProcessedUrlInputRef = useRef(false)

  // Read initial run_id from localStorage on mount
  useEffect(() => {
    if (!graphId) return
    const storedRunId = localStorage.getItem(`copilot_run_${graphId}`)
    if (storedRunId) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setCurrentRunId(storedRunId)
    }
  }, [graphId])

  const setSession = useCallback(
    (runId: string) => {
      setCurrentRunId(runId)
      if (graphId) {
        localStorage.setItem(`copilot_run_${graphId}`, runId)
      }
    },
    [graphId],
  )

  const clearSession = useCallback(() => {
    setCurrentRunId(null)
    if (graphId) {
      localStorage.removeItem(`copilot_run_${graphId}`)
    }
  }, [graphId])

  return {
    currentRunId,
    hasProcessedUrlInputRef,
    setSession,
    clearSession,
  }
}
