/**
 * Execution Store Types
 *
 * Defines all types and interfaces related to execution
 */

import type { ExecutionStep } from '@/types'

import type { GraphState, TraceStep } from '../../components/visualization'

// ============ Basic Types ============

export interface InterruptState extends Record<string, unknown> {
  /** Current interrupted node ID */
  current_node?: string
  /** Route decision information */
  route_decision?: string
  route_reason?: string
  /** Loop related state */
  loop_count?: number
  loop_condition_met?: boolean
  max_loop_iterations?: number
  /** Parallel task state */
  parallel_mode?: boolean
  task_states?: Record<string, {
    status: 'pending' | 'running' | 'completed' | 'error'
    result?: any
    error_msg?: string
  }>
  /** Complete graph state snapshot */
  graph_state?: Partial<GraphState>
}

export interface InterruptInfo {
  nodeId: string
  nodeLabel: string
  state: InterruptState
  threadId: string
}

export interface RouteDecision {
  nodeId: string
  nodeType: 'condition' | 'router' | 'loop'
  decision: {
    result: boolean | string
    reason: string
    goto: string
  }
  timestamp: number
}

// ============ Graph Execution State ============

export interface GraphExecutionState {
  steps: ExecutionStep[]
  isExecuting: boolean
  showPanel: boolean
  activeNodeId: string | null
  pendingInterrupts: Map<string, InterruptInfo>
  currentState: GraphState | null
  executionTrace: TraceStep[]
  routeDecisions: RouteDecision[]
}

// ============ Execution Context ============

export interface ExecutionContext {
  graphId: string
  abortController: AbortController | null
  threadId: string | null
  state: GraphExecutionState
}

// ============ Store Types ============

export interface ExecutionStoreState {
  // Core state
  contexts: Map<string, ExecutionContext>
  currentGraphId: string | null

  // Computed properties for current graph (backward compatible)
  steps: ExecutionStep[]
  isExecuting: boolean
  showPanel: boolean
  activeNodeId: string | null
  pendingInterrupts: Map<string, InterruptInfo>
  currentState: GraphState | null
  executionTrace: TraceStep[]
  routeDecisions: RouteDecision[]
}

export interface ExecutionStoreActions {
  // Graph switching
  setCurrentGraphId: (graphId: string | null) => void

  // State updates
  updateGraphState: (graphId: string, updates: Partial<GraphExecutionState>) => void

  // Step management
  addStep: (step: ExecutionStep) => void
  updateStep: (stepId: string, updates: Partial<ExecutionStep>) => void
  appendContent: (stepId: string, text: string) => void

  // Panel control
  togglePanel: (show?: boolean) => void

  // Interrupt management
  addInterrupt: (interrupt: InterruptInfo) => void
  removeInterrupt: (nodeId: string) => void
  clearInterrupts: () => void
  getInterrupt: (nodeId: string) => InterruptInfo | undefined

  // Execution control
  clear: () => void
  clearGraphState: (graphId: string) => void
  getRunningGraphIds: () => string[]
  setExecuting: (isExecuting: boolean) => void
  startExecution: (input: string) => Promise<void>
  stopExecution: () => Promise<void>

  // Execution context management
  getContext: (graphId: string) => ExecutionContext
  setAbortController: (graphId: string, controller: AbortController | null) => void
  setThreadId: (graphId: string, threadId: string | null) => void

  // Command Mode visualization
  updateState: (state: Partial<GraphState>) => void
  addTraceStep: (step: TraceStep) => void
  addRouteDecision: (nodeId: string, nodeType: 'condition' | 'router' | 'loop', decision: {
    result: boolean | string
    reason: string
    goto: string
  }) => void
}

export type ExecutionStore = ExecutionStoreState & ExecutionStoreActions

// ============ Configuration Constants ============

export const EXECUTION_CONFIG = {
  /** Maximum number of cached graphs */
  MAX_CACHED_GRAPHS: 10,
} as const

