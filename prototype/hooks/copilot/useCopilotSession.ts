/**
 * useCopilotSession - Hook for managing Copilot session state
 */

import { useState, useEffect, useRef, useCallback } from 'react'

import { copilotService } from '@/services/copilotService'

export function useCopilotSession(graphId?: string) {
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null)
  const hasProcessedUrlInputRef = useRef(false)

  // Read initial session from localStorage on mount
  useEffect(() => {
    if (!graphId) return
    const storedSessionId = localStorage.getItem(`copilot_session_${graphId}`)
    if (storedSessionId) {
      setCurrentSessionId(storedSessionId)
    }
  }, [graphId])

  const setSession = useCallback((sessionId: string) => {
    setCurrentSessionId(sessionId)
    if (graphId) {
      localStorage.setItem(`copilot_session_${graphId}`, sessionId)
    }
  }, [graphId])

  const clearSession = useCallback(() => {
    setCurrentSessionId(null)
    if (graphId) {
      localStorage.removeItem(`copilot_session_${graphId}`)
    }
  }, [graphId])

  return {
    currentSessionId,
    hasProcessedUrlInputRef,
    setSession,
    clearSession,
  }
}
