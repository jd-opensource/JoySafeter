/**
 * Event Processor - Unified SSE Event Handler
 *
 * Shared event processing logic for startExecution and resumeWithCommand.
 * Ensures all event types are correctly handled in both execution paths.
 */

import type { ChatStreamEvent } from '@/services/chatBackend'
import type { ExecutionStep } from '@/types'

import type { GraphState, TraceStep } from '../components/visualization'
import type { InterruptState } from '../stores/execution/types'
import { generateId } from '../stores/execution/utils'

import { mapChatEventToExecutionStep, type AdapterResult } from './eventAdapter'

// Re-export generateId for backwards compatibility
export { generateId }

/**
 * Event processing context
 */
export interface EventProcessorContext {
  /** Current thought step ID */
  currentThoughtId: string | null
  /** Tool name to step ID mapping */
  toolStepMap: Map<string, string>
  /** Node name to step ID mapping */
  nodeStepMap: Map<string, string>
  /** Model run_id to step ID mapping, used for pairing model_input and model_output */
  modelStepMap: Map<string, string>
  /** Current graphId */
  graphId: string
  /** Function to generate unique IDs */
  genId: (prefix: string) => string
  /** Function to get current steps */
  getSteps: () => ExecutionStep[]
}

/**
 * Store interface - Defines store methods to be called
 */
export interface EventProcessorStore {
  addStep: (step: ExecutionStep) => void
  updateStep: (stepId: string, updates: Partial<ExecutionStep>) => void
  appendContent: (stepId: string, text: string) => void
  addInterrupt: (interrupt: {
    nodeId: string
    nodeLabel: string
    state: InterruptState
    threadId: string
  }) => void
  setExecuting: (isExecuting: boolean) => void
  updateState: (state: Partial<GraphState>) => void
  addTraceStep: (step: TraceStep) => void
  addRouteDecision: (
    nodeId: string,
    nodeType: 'condition' | 'router' | 'loop',
    decision: {
      result: boolean | string
      reason: string
      goto: string
    }
  ) => void
  setThreadId: (graphId: string, threadId: string | null) => void
  updateGraphState: (graphId: string, updates: { isExecuting?: boolean }) => void
  getContext: (graphId: string) => { state: { currentState: GraphState | null } }
}

/**
 * Event processing result
 */
export interface ProcessEventResult {
  /** Whether processing should stop */
  shouldStop: boolean
  /** Stop reason */
  stopReason?: 'stopped' | 'done' | 'interrupt'
  /** Updated currentThoughtId */
  currentThoughtId: string | null
}

/**
 * Process a single SSE event
 *
 * @param evt - SSE event
 * @param ctx - Processing context
 * @param store - Store instance
 * @returns Processing result
 */
export function processEvent(
  evt: ChatStreamEvent,
  ctx: EventProcessorContext,
  store: EventProcessorStore
): ProcessEventResult {
  let { currentThoughtId } = ctx
  const { toolStepMap, nodeStepMap, modelStepMap, genId, getSteps, graphId } = ctx

  // Use eventAdapter to transform event
  const result = mapChatEventToExecutionStep(evt, {
    currentThoughtId,
    toolStepMap,
    nodeStepMap,
    modelStepMap,
    genId,
    getSteps,
  })

  // Handle different result types
  switch (result.type) {
    case 'stopped':
      store.setExecuting(false)
      return { shouldStop: true, stopReason: 'stopped', currentThoughtId }

    case 'add_step':
      if (result.step) {
        store.addStep(result.step)
        if (result.step.stepType === 'agent_thought') {
          currentThoughtId = result.step.id
        }
      }
      break

    case 'append_content':
      if (result.stepId && result.content) {
        store.appendContent(result.stepId, result.content)
      }
      break

    case 'update_step':
      if (result.stepId && result.updates) {
        store.updateStep(result.stepId, result.updates)
        if (result.clearThought) {
          currentThoughtId = null
        }
      }
      break

    case 'done':
      if (currentThoughtId) {
        store.updateStep(currentThoughtId, { status: 'success', endTime: Date.now() })
        currentThoughtId = null
      }
      store.setExecuting(false)
      return { shouldStop: true, stopReason: 'done', currentThoughtId: null }

    case 'interrupt':
      store.addInterrupt({
        nodeId: result.nodeId,
        nodeLabel: result.nodeLabel,
        state: result.state,
        threadId: result.threadId,
      })
      if (result.threadId) {
        store.setThreadId(graphId, result.threadId)
      }
      store.updateGraphState(graphId, { isExecuting: false })
      return { shouldStop: true, stopReason: 'interrupt', currentThoughtId }

    case 'command':
      handleCommandEvent(result, evt, graphId, store)
      break

    case 'route_decision':
      handleRouteDecisionEvent(result, store)
      break

    case 'loop_iteration':
      handleLoopIterationEvent(result, store)
      break

    case 'parallel_task':
      handleParallelTaskEvent(result, graphId, store)
      break

    case 'state_update':
      handleStateUpdateEvent(result, store)
      break

    case 'noop':
      // No processing needed
      break
  }

  return { shouldStop: false, currentThoughtId }
}

/**
 * Handle command event
 */
function handleCommandEvent(
  result: AdapterResult & { type: 'command' },
  evt: ChatStreamEvent,
  graphId: string,
  store: EventProcessorStore
): void {
  if (result.command.update) {
    store.updateState(result.command.update)
  }
  const ctx = store.getContext(graphId)
  store.addTraceStep({
    nodeId: result.nodeId,
    nodeType: 'agent',
    timestamp: evt.timestamp || Date.now(),
    command: {
      update: result.command.update || {},
      goto: result.command.goto,
      reason: result.command.reason,
    },
    stateSnapshot: ctx.state.currentState || {},
  })
}

/**
 * Handle route_decision event
 */
function handleRouteDecisionEvent(
  result: AdapterResult & { type: 'route_decision' },
  store: EventProcessorStore
): void {
  store.addRouteDecision(result.decision.node_id, result.decision.node_type, {
    result: result.decision.result,
    reason: result.decision.reason,
    goto: result.decision.goto,
  })
  store.updateState({
    current_node: result.decision.node_id,
    route_decision:
      typeof result.decision.result === 'boolean'
        ? result.decision.result
          ? 'true'
          : 'false'
        : String(result.decision.result),
    route_reason: result.decision.reason,
  })
}

/**
 * Handle loop_iteration event
 */
function handleLoopIterationEvent(
  result: AdapterResult & { type: 'loop_iteration' },
  store: EventProcessorStore
): void {
  store.updateState({
    loop_count: result.iteration.iteration,
    loop_condition_met: result.iteration.condition_met,
    max_loop_iterations: result.iteration.max_iterations,
  })
}

/**
 * Handle parallel_task event
 */
function handleParallelTaskEvent(
  result: AdapterResult & { type: 'parallel_task' },
  graphId: string,
  store: EventProcessorStore
): void {
  const ctx = store.getContext(graphId)
  const taskStates = (ctx.state.currentState as Record<string, unknown>)?.task_states as Record<
    string,
    unknown
  > || {}
  taskStates[result.task.task_id] = {
    status:
      result.task.status === 'started'
        ? 'running'
        : result.task.status === 'completed'
          ? 'completed'
          : 'error',
    result: result.task.result,
    error_msg: result.task.error_msg,
  }
  store.updateState({ task_states: taskStates, parallel_mode: true } as Partial<GraphState>)
}

/**
 * Handle state_update event
 */
function handleStateUpdateEvent(
  result: AdapterResult & { type: 'state_update' },
  store: EventProcessorStore
): void {
  store.updateState((result.update.state_snapshot || {}) as Partial<GraphState>)
}

/**
 * Create event processing context
 */
export function createEventProcessorContext(
  graphId: string,
  genId: (prefix: string) => string,
  getSteps: () => ExecutionStep[]
): EventProcessorContext {
  return {
    currentThoughtId: null,
    toolStepMap: new Map<string, string>(),
    nodeStepMap: new Map<string, string>(),
    modelStepMap: new Map<string, string>(),
    graphId,
    genId,
    getSteps,
  }
}
