/**
 * useCopilotSession - Hook for managing Copilot session state
 */

import { useState, useEffect, useRef } from 'react'

import { copilotService } from '@/services/copilotService'

export function useCopilotSession(graphId?: string) {
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null)
  const hasProcessedUrlInputRef = useRef(false)

  // Session recovery on component mount or graphId change
  useEffect(() => {
    if (!graphId) return

    const recoverSession = async () => {
      try {
        // Check localStorage for active session
        const storedSessionId = localStorage.getItem(`copilot_session_${graphId}`)
        if (!storedSessionId) return

        // Check session status
        const sessionData = await copilotService.getSession(storedSessionId)

        if (sessionData && sessionData.status === 'generating') {
          // Restore session
          setCurrentSessionId(storedSessionId)
          return sessionData.content // Return content for restoration
        } else {
          // Session completed or not found, clean up
          localStorage.removeItem(`copilot_session_${graphId}`)
        }
      } catch (error) {
        console.warn('[useCopilotSession] Failed to recover session:', error)
        // Clean up on error
        if (graphId) {
          localStorage.removeItem(`copilot_session_${graphId}`)
        }
      }
      return null
    }

    recoverSession()
  }, [graphId])

  const setSession = (sessionId: string) => {
    setCurrentSessionId(sessionId)
    if (graphId) {
      localStorage.setItem(`copilot_session_${graphId}`, sessionId)
    }
  }

  const clearSession = () => {
    setCurrentSessionId(null)
    if (graphId) {
      localStorage.removeItem(`copilot_session_${graphId}`)
    }
  }

  return {
    currentSessionId,
    hasProcessedUrlInputRef,
    setSession,
    clearSession,
  }
}
