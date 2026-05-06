import { useState, useEffect, useRef, useCallback } from 'react'

interface SessionData {
  runId: string
  executionId: string | null
}

function readSession(graphId: string): SessionData | null {
  const raw =
    localStorage.getItem(`draft_copilot_run_${graphId}`) ??
    localStorage.getItem(`copilot_run_${graphId}`)
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw)
    if (typeof parsed === 'object' && parsed.runId) return parsed as SessionData
  } catch {
    if (typeof raw === 'string' && raw.length > 0) {
      return { runId: raw, executionId: null }
    }
  }
  return null
}

export function useCopilotSession(graphId?: string) {
  const [session, setSessionState] = useState<SessionData | null>(null)
  const hasProcessedUrlInputRef = useRef(false)

  useEffect(() => {
    if (!graphId) return
    const stored = readSession(graphId)
    if (stored) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSessionState(stored)
    }
  }, [graphId])

  const setSession = useCallback(
    (runId: string, executionId: string | null = null) => {
      setSessionState({ runId, executionId })
      if (graphId) {
        localStorage.setItem(`draft_copilot_run_${graphId}`, JSON.stringify({ runId, executionId }))
        localStorage.removeItem(`copilot_run_${graphId}`)
      }
    },
    [graphId],
  )

  const clearSession = useCallback(() => {
    setSessionState(null)
    if (graphId) {
      localStorage.removeItem(`draft_copilot_run_${graphId}`)
      localStorage.removeItem(`copilot_run_${graphId}`)
    }
  }, [graphId])

  return {
    currentRunId: session?.runId ?? null,
    currentExecutionId: session?.executionId ?? null,
    hasProcessedUrlInputRef,
    setSession,
    clearSession,
  }
}
