/**
 * Command Service - Handles resuming interrupted graph execution
 *
 * Uses shared eventProcessor to handle SSE events, ensuring consistency with startExecution.
 */

import { apiStream } from '@/lib/api-client'
import type { ChatStreamEvent } from '@/services/chatBackend'

import { generateId } from '../stores/execution/utils'
import { useExecutionStore } from '../stores/executionStore'

import {
  processEvent,
  createEventProcessorContext,
  type EventProcessorStore,
} from './eventProcessor'

export interface Command {
  update?: Record<string, unknown>
  goto?: string
}

/**
 * Resume interrupted graph execution with a Command
 * This function processes the SSE stream and updates the execution store
 */
export async function resumeWithCommand(
  threadId: string,
  command: Command,
  onEvent?: (evt: ChatStreamEvent) => void
): Promise<void> {
  // Use unified apiStream method to handle SSE streaming requests
  const response = await apiStream('chat/resume', {
    thread_id: threadId,
    command: command,
  })

  // Get execution store
  const store = useExecutionStore.getState()
  const graphId = store.currentGraphId

  if (!graphId) {
    throw new Error('No active graph for resume')
  }

  // Handle SSE stream
  const reader = response.body?.getReader()
  if (!reader) {
    throw new Error('No response body')
  }

  // Create event processing context
  const ctx = createEventProcessorContext(
    graphId,
    generateId,
    () => store.steps
  )

  // Create store adapter conforming to EventProcessorStore interface
  const storeAdapter: EventProcessorStore = {
    addStep: store.addStep,
    updateStep: store.updateStep,
    appendContent: store.appendContent,
    addInterrupt: store.addInterrupt,
    setExecuting: store.setExecuting,
    updateState: store.updateState,
    addTraceStep: store.addTraceStep,
    addRouteDecision: store.addRouteDecision,
    setThreadId: store.setThreadId,
    updateGraphState: store.updateGraphState,
    getContext: store.getContext,
  }

  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  const sseSplitRegex = /(?:\r\n|\r|\n){2}/

  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const parts = buffer.split(sseSplitRegex)
      buffer = parts.pop() || ''

      for (const part of parts) {
        if (part.startsWith('data: ')) {
          try {
            const data = JSON.parse(part.slice(6)) as ChatStreamEvent

            // Call custom event handler if provided
            if (onEvent) {
              onEvent(data)
            }

            // Use shared event processor
            const result = processEvent(data, ctx, storeAdapter)

            // Update currentThoughtId in context
            ctx.currentThoughtId = result.currentThoughtId

            // Check if processing should stop
            if (result.shouldStop) {
              return
            }
          } catch (e) {
            // Ignore parse errors for non-JSON lines
            if (e instanceof Error && e.message.includes('Resume failed')) {
              throw e
            }
          }
        }
      }
    }
  } catch (e: unknown) {
    const error = e as { name?: string; message?: string }
    if (error?.name === 'AbortError') {
      throw e
    }
    store.setExecuting(false)
    throw new Error(`Resume failed: ${error?.message || String(e)}`)
  }
}
