/**
 * useCopilotExecutionBridge - Bridge execution events to copilot callbacks
 *
 * When copilot dispatches through the execution engine (POST /v1/copilot/run),
 * events arrive as ExecutionEventFrames via the execution WebSocket.
 * This hook maps those events to the existing copilot callback system
 * (onStatus, onContent, onThoughtStep, etc.) so the UI works unchanged.
 */

import { useEffect, useRef } from 'react'

import { useExecutionStream } from '@/hooks/use-execution-stream'
import { TERMINAL_EXECUTION_STATUSES } from '@/types/agent-run'
import type { AppErrorPayload, ExecutionEvent } from '@/types/agent-run'
import type { GraphAction } from '@/types/copilot'

interface CopilotCallbacks {
  onStatus: (stage: string, message: string) => void
  onContent: (content: string) => void
  onThoughtStep: (step: { index: number; content: string }) => void
  onToolCall: (tool: string, input: Record<string, unknown>) => void
  onToolResult: (action: {
    type: string
    payload: Record<string, unknown>
    reasoning?: string
  }) => void
  onResult: (response: { message: string; actions?: GraphAction[] }) => Promise<void>
  onError: (error: AppErrorPayload) => void
  onDone: () => Promise<void>
}

interface UseCopilotExecutionBridgeOptions {
  executionId: string | null
  callbacks: CopilotCallbacks
}

/**
 * Subscribes to execution events and dispatches to copilot callbacks.
 */
export function useCopilotExecutionBridge({
  executionId,
  callbacks,
}: UseCopilotExecutionBridgeOptions) {
  const callbacksRef = useRef(callbacks)
  useEffect(() => {
    callbacksRef.current = callbacks
  }, [callbacks])

  const { status, events, error } = useExecutionStream({
    executionId: executionId || '',
    enabled: Boolean(executionId),
  })

  const processedSeqRef = useRef(0)

  // Process new events as they arrive
  useEffect(() => {
    if (!events || events.length === 0) return

    const cb = callbacksRef.current
    const newEvents = events.filter((e: ExecutionEvent) => e.seq > processedSeqRef.current)

    for (const event of newEvents) {
      processedSeqRef.current = event.seq
      const payload = event.payload as Record<string, unknown>

      switch (event.event_type) {
        case 'copilot_status':
          cb.onStatus((payload.stage as string) ?? 'processing', (payload.message as string) ?? '')
          break

        case 'copilot_content':
          cb.onContent((payload.content as string) ?? '')
          break

        case 'copilot_thought_step':
          cb.onThoughtStep(payload.step as { index: number; content: string })
          break

        case 'copilot_tool_call':
          cb.onToolCall(payload.tool as string, (payload.input as Record<string, unknown>) ?? {})
          break

        case 'copilot_tool_result':
          cb.onToolResult(
            payload.action as {
              type: string
              payload: Record<string, unknown>
              reasoning?: string
            },
          )
          break

        case 'copilot_result':
          cb.onResult({
            message: (payload.message as string) ?? '',
            actions: payload.actions as GraphAction[] | undefined,
          })
          break

        case 'error':
          cb.onError({
            code: (payload.code as string) ?? 'UNKNOWN_ERROR',
            message: (payload.message as string) ?? 'Unknown error',
            data: (payload.data as Record<string, unknown> | null) ?? null,
          })
          break
      }
    }
  }, [events])

  useEffect(() => {
    if (!error) {
      return
    }

    const cb = callbacksRef.current
    cb.onError(error)
  }, [error])

  useEffect(() => {
    if (!executionId || !status || !TERMINAL_EXECUTION_STATUSES.includes(status as never)) {
      return
    }

    void callbacksRef.current.onDone()
  }, [executionId, status])

  // Reset processed seq when execution changes
  useEffect(() => {
    processedSeqRef.current = 0
  }, [executionId])

  const isActive = Boolean(
    executionId && status && !TERMINAL_EXECUTION_STATUSES.includes(status as never),
  )

  return { isActive, status }
}
