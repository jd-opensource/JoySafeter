/**
 * Execution Manager
 *
 * Manages execution contexts for multiple Graphs, including:
 * - LRU cache management
 * - AbortController management
 * - ThreadId management
 */

import type { ExecutionContext, GraphExecutionState, InterruptInfo } from './types'
import { EXECUTION_CONFIG } from './types'
import { generateId } from './utils'

/**
 * Create empty Graph execution state
 */
export function createEmptyGraphState(): GraphExecutionState {
  return {
    steps: [],
    isExecuting: false,
    showPanel: false,
    activeNodeId: null,
    pendingInterrupts: new Map<string, InterruptInfo>(),
    currentState: null,
    executionTrace: [],
    routeDecisions: [],
  }
}

/**
 * Create execution context
 */
export function createExecutionContext(graphId: string): ExecutionContext {
  return {
    graphId,
    abortController: null,
    threadId: null,
    state: createEmptyGraphState(),
  }
}

/**
 * Execution Manager Class
 *
 * Uses singleton pattern to manage execution contexts for all graphs
 */
export class ExecutionManager {
  private static instance: ExecutionManager | null = null

  /** Access order record (for LRU) */
  private accessOrder: string[] = []

  private constructor() {}

  static getInstance(): ExecutionManager {
    if (!ExecutionManager.instance) {
      ExecutionManager.instance = new ExecutionManager()
    }
    return ExecutionManager.instance
  }

  /**
   * Record graph access (update LRU order)
   */
  recordAccess(graphId: string): void {
    const existingIndex = this.accessOrder.indexOf(graphId)
    if (existingIndex !== -1) {
      this.accessOrder.splice(existingIndex, 1)
    }
    this.accessOrder.push(graphId)
  }

  /**
   * Get list of graph IDs to evict
   *
   * @param contexts All current contexts
   * @returns List of graphIds to evict
   */
  getGraphsToEvict(contexts: Map<string, ExecutionContext>): string[] {
    const toEvict: string[] = []

    while (this.accessOrder.length > EXECUTION_CONFIG.MAX_CACHED_GRAPHS) {
      const oldestGraphId = this.accessOrder[0]
      const context = contexts.get(oldestGraphId)

      // Do not evict graphs that are running or have interrupts
      if (context && !context.state.isExecuting && context.state.pendingInterrupts.size === 0) {
        this.accessOrder.shift()
        toEvict.push(oldestGraphId)
      } else {
        // Move to end to avoid repeated checking
        this.accessOrder.shift()
        if (context) {
          this.accessOrder.push(oldestGraphId)
        }
        break // Avoid infinite loop
      }
    }

    return toEvict
  }

  /**
   * Remove from access record
   */
  removeFromAccess(graphId: string): void {
    const index = this.accessOrder.indexOf(graphId)
    if (index !== -1) {
      this.accessOrder.splice(index, 1)
    }
  }

  /**
   * Get access order (for debugging)
   */
  getAccessOrder(): readonly string[] {
    return this.accessOrder
  }

  /**
   * Reset (for testing)
   */
  reset(): void {
    this.accessOrder = []
  }
}

// Export singleton getter method
export const getExecutionManager = () => ExecutionManager.getInstance()
