'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

import { getExecutionWsClient } from '@/lib/ws/executions/executionWsClient'
import type {
  ExecutionCompletedFrame,
  ExecutionEventFrame,
  ExecutionSnapshotFrame,
} from '@/lib/ws/executions/types'
import type { ExecutionEvent } from '@/types/agent-run'

interface UseExecutionStreamOptions {
  executionId: string
  enabled?: boolean
}

interface UseExecutionStreamResult {
  events: ExecutionEvent[]
  status: string | null
  isConnected: boolean
  /** True if WS failed and we should fall back to polling */
  wsFailed: boolean
}

/**
 * WebSocket hook for real-time execution events.
 * Connects to /ws/executions, subscribes to a single execution,
 * receives snapshot + live events. Falls back to polling if WS fails.
 */
export function useExecutionStream({
  executionId,
  enabled = true,
}: UseExecutionStreamOptions): UseExecutionStreamResult {
  const [events, setEvents] = useState<ExecutionEvent[]>([])
  const [status, setStatus] = useState<string | null>(null)
  const [isConnected, setIsConnected] = useState(false)
  const [wsFailed, setWsFailed] = useState(false)
  const seqRef = useRef(0)
  const failCountRef = useRef(0)
  const mountedRef = useRef(true)

  const handleSnapshot = useCallback((frame: ExecutionSnapshotFrame) => {
    if (!mountedRef.current) return
    seqRef.current = frame.last_seq
    setStatus(frame.status)
    setEvents(frame.events ?? [])
    failCountRef.current = 0
  }, [])

  const handleEvent = useCallback((frame: ExecutionEventFrame) => {
    if (!mountedRef.current) return
    const newEvent: ExecutionEvent = {
      id: `${frame.execution_id}-${frame.seq}`,
      execution_id: frame.execution_id,
      seq: frame.seq,
      event_type: frame.event_type,
      payload: frame.payload,
      created_at: frame.created_at,
    }
    setEvents((prev) => {
      if (prev.some((e) => e.seq === newEvent.seq)) return prev
      return [...prev, newEvent]
    })
    failCountRef.current = 0
  }, [])

  const handleCompleted = useCallback((frame: ExecutionCompletedFrame) => {
    if (!mountedRef.current) return
    setStatus(frame.status)
  }, [])

  const handleError = useCallback((message: string) => {
    if (!mountedRef.current) return
    console.warn('[ExecStream] WS error:', message)
    failCountRef.current += 1
    if (failCountRef.current >= 3) {
      setWsFailed(true)
    }
  }, [])

  useEffect(() => {
    if (!enabled || !executionId) return

    mountedRef.current = true

    const client = getExecutionWsClient()
    const unsub = client.subscribeConnectionState((state) => {
      if (mountedRef.current) setIsConnected(state.isConnected)
    })

    client
      .subscribe(executionId, seqRef.current, {
        onSnapshot: handleSnapshot,
        onEvent: handleEvent,
        onCompleted: handleCompleted,
        onError: handleError,
      })
      .catch(() => {
        if (mountedRef.current) setWsFailed(true)
      })

    return () => {
      mountedRef.current = false
      unsub()
      client.unsubscribe(executionId)
    }
  }, [executionId, enabled, handleSnapshot, handleEvent, handleCompleted, handleError])

  return { events, status, isConnected, wsFailed }
}
