/**
 * Command Service - Handles resuming interrupted graph execution
 *
 * Uses executionAdapter.injectMessage to deliver resume commands to running
 * executions, consistent with the rest of the execution flow.
 */

import { createApiError, ApiError } from '@/lib/api-client'

import { useExecutionStore } from '../stores/execution/executionStore'

import { executionAdapter } from './executionAdapter'

export interface Command {
  update?: Record<string, unknown>
  goto?: string
}

/**
 * Resume interrupted graph execution with a Command.
 *
 * Fetches the current execution ID from the active run (stored in executionStore),
 * serialises the Command as JSON, and injects it via the REST API.
 *
 * The `_onEvent` parameter is kept for call-site compatibility but is no longer
 * used — the execution WebSocket (subscribed in executionStore) already receives
 * all events from the resumed execution.
 */
export async function resumeWithCommand(
  _threadId: string,
  command: Command,
  _onEvent?: unknown,
): Promise<void> {
  const store = useExecutionStore.getState()
  const graphId = store.currentGraphId

  if (!graphId) {
    throw createApiError(400, 'Bad Request', {
      code: 'EXECUTION_RESUME_GRAPH_MISSING',
      message: 'No active graph for resume',
      data: null,
    })
  }

  const context = store.getContext(graphId)
  const runId = context.runId

  if (!runId) {
    throw createApiError(400, 'Bad Request', {
      code: 'EXECUTION_RESUME_RUN_MISSING',
      message: 'No active run to resume',
      data: { graph_id: graphId },
    })
  }

  try {
    const executionId = await executionAdapter.getExecutionId(runId)
    const message = JSON.stringify(command)
    await executionAdapter.injectMessage(executionId, message)
  } catch (e: unknown) {
    const error = e as { name?: string; message?: string }
    if (error?.name === 'AbortError') {
      throw e
    }
    store.setExecuting(false)
    if (e instanceof ApiError) {
      throw e
    }
    throw createApiError(0, 'Resume Failed', {
      code: 'EXECUTION_RESUME_FAILED',
      message: error?.message || 'Resume failed',
      data: { run_id: runId, graph_id: graphId },
    })
  }
}
