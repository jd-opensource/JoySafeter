'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

import { getExecutionWsClient } from '@/lib/ws/executions/executionWsClient'
import type {
  ExecutionEventFrame,
  ExecutionSnapshotFrame,
  ExecutionStatusFrame,
} from '@/lib/ws/executions/types'
import type { ExecutionEvent } from '@/types/executions'

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

  const handleSnapshot = useCallback((frame: ExecutionSnapshotFrame) => {
    seqRef.current = frame.last_seq
    setStatus(frame.status)
    setEvents(frame.events ?? [])
    failCountRef.current = 0
  }, [])

  const handleEvent = useCallback((frame: ExecutionEventFrame) => {
    const newEvent: ExecutionEvent = {
      id: `${frame.execution_id}-${frame.seq}`,
      execution_id: frame.execution_id,
      seq: frame.seq,
      event_type: frame.event_type,
      payload: frame.payload,
      created_at: frame.created_at,
    }
    setEvents((prev) => [...prev, newEvent])
    failCountRef.current = 0
  }, [])

  const handleStatus = useCallback((frame: ExecutionStatusFrame) => {
    setStatus(frame.status)
  }, [])

  const handleError = useCallback((message: string) => {
    console.warn('[ExecStream] WS error:', message)
    failCountRef.current += 1
    if (failCountRef.current >= 3) {
      setWsFailed(true)
    }
  }, [])

  useEffect(() => {
    if (!enabled || !executionId) return

    const client = getExecutionWsClient()
    const unsub = client.subscribeConnectionState((state) => {
      setIsConnected(state.isConnected)
    })

    client
      .subscribe(executionId, seqRef.current, {
        onSnapshot: handleSnapshot,
        onEvent: handleEvent,
        onStatus: handleStatus,
        onError: handleError,
      })
      .catch(() => {
        setWsFailed(true)
      })

    return () => {
      unsub()
      client.unsubscribe(executionId)
    }
  }, [executionId, enabled, handleSnapshot, handleEvent, handleStatus, handleError])

  return { events, status, isConnected, wsFailed }
}
