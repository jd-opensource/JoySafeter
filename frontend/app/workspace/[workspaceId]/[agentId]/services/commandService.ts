/**
 * Command Service - Handles resuming interrupted graph execution
 *
 * Uses shared eventProcessor to handle SSE events, ensuring consistency with startExecution.
 */

import type { ChatStreamEvent } from '@/services/chatBackend'

import { generateId } from '../stores/execution/utils'
import { useExecutionStore } from '../stores/executionStore'

import {
  processEvent,
  createEventProcessorContext,
  type EventProcessorStore,
} from './eventProcessor'
import { workspaceChatWsService } from './workspaceChatWsService'

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
  onEvent?: (evt: ChatStreamEvent) => void,
): Promise<void> {
  // Get execution store
  const store = useExecutionStore.getState()
  const graphId = store.currentGraphId

  if (!graphId) {
    throw new Error('No active graph for resume')
  }

  // Create event processing context
  const ctx = createEventProcessorContext(graphId, generateId, () => store.steps)

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

  try {
    const result = await workspaceChatWsService.sendResume({
      threadId,
      command,
      onEvent: (data) => {
        if (onEvent) onEvent(data)
        const processed = processEvent(data, ctx, storeAdapter)
        ctx.currentThoughtId = processed.currentThoughtId
      },
    })
    if (result.threadId) {
      store.setThreadId(graphId, result.threadId)
    }
    store.setRequestId(graphId, result.requestId)
  } catch (e: unknown) {
    const error = e as { name?: string; message?: string }
    if (error?.name === 'AbortError') {
      throw e
    }
    store.setExecuting(false)
    throw new Error(`Resume failed: ${error?.message || String(e)}`)
  }
}
