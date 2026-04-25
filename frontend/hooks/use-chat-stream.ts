'use client'

import { useEffect, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { useExecutionStream } from './use-execution-stream'
import { threadEventKeys } from './use-thread-events'
import { TERMINAL_EXECUTION_STATUSES } from '@/types/agent-run'
import type { ThreadEvent } from '@/types/thread'

export function useChatStream(
  executionId: string | null,
  threadId: string,
  workspaceId: string,
) {
  const queryClient = useQueryClient()
  const { events, status } = useExecutionStream({
    executionId: executionId || '',
    enabled: Boolean(executionId),
  })

  const lastSeenSeqRef = useRef(-1)

  useEffect(() => {
    if (!executionId || !events.length) return

    const newEvents = events.filter(
      (e) => e.sequence_no > lastSeenSeqRef.current,
    )
    if (!newEvents.length) return

    lastSeenSeqRef.current = Math.max(
      ...newEvents.map((e) => e.sequence_no),
    )

    queryClient.setQueryData(
      threadEventKeys.events(threadId, workspaceId),
      (old: { events: ThreadEvent[]; total: number } | undefined) => {
        const existing = old?.events ?? []
        const mapped: ThreadEvent[] = newEvents.map((e) => ({
          id: e.id || `stream-${e.sequence_no}`,
          run_id: '',
          execution_id: executionId,
          sequence_no: e.sequence_no,
          event_type: e.event_type,
          payload: e.payload,
          execution_status: status || 'running',
          created_at: e.created_at || new Date().toISOString(),
        }))
        return {
          events: [...existing, ...mapped],
          total: (old?.total ?? 0) + mapped.length,
        }
      },
    )
  }, [events, executionId, threadId, workspaceId, status, queryClient])

  const prevStatusRef = useRef<string | null>(null)
  useEffect(() => {
    const prev = prevStatusRef.current
    prevStatusRef.current = status
    if (
      prev &&
      !TERMINAL_EXECUTION_STATUSES.includes(prev as never) &&
      status &&
      TERMINAL_EXECUTION_STATUSES.includes(status as never)
    ) {
      lastSeenSeqRef.current = -1
      setTimeout(() => {
        queryClient.invalidateQueries({
          queryKey: threadEventKeys.events(threadId, workspaceId),
        })
      }, 500)
    }
  }, [status, threadId, workspaceId, queryClient])

  const isExecuting = Boolean(
    executionId &&
      status &&
      !TERMINAL_EXECUTION_STATUSES.includes(status as never),
  )

  return { isExecuting, status }
}
