'use client'

/**
 * Execution Store
 *
 * Zustand Store for managing Graph execution state
 *
 * Responsibilities:
 * - Multi-Graph state isolation
 * - LRU cache management
 * - Execution flow control
 */

import { create } from 'zustand'

import { streamChat, type ChatStreamEvent } from '@/services/chatBackend'
import type { ExecutionStep } from '@/types'

import type { GraphState, TraceStep } from '../../components/visualization'
import { agentService } from '../../services/agentService'
import {
  processEvent,
  createEventProcessorContext,
  generateId as genId,
  type EventProcessorStore,
} from '../../services/eventProcessor'

import {
  createEmptyGraphState,
  createExecutionContext,
  getExecutionManager,
} from './ExecutionManager'
import type {
  ExecutionStore,
  ExecutionContext,
  GraphExecutionState,
  InterruptInfo
} from './types'
import { generateId } from './utils'

// ============ Batch Update Buffer ============
// Used to merge high-frequency appendContent calls, reducing state update frequency

const pendingContentUpdates = new Map<string, string>()
let contentUpdateScheduled = false

// ============ Helper Functions ============

function getOrCreateContext(
  contexts: Map<string, ExecutionContext>,
  graphId: string | null
): ExecutionContext {
  if (!graphId) return createExecutionContext('')
  let context = contexts.get(graphId)
  if (!context) {
    context = createExecutionContext(graphId)
  }
  return context
}

function syncComputedProperties(state: GraphExecutionState) {
  return {
    steps: state.steps,
    isExecuting: state.isExecuting,
    showPanel: state.showPanel,
    activeNodeId: state.activeNodeId,
    pendingInterrupts: state.pendingInterrupts,
    currentState: state.currentState,
    executionTrace: state.executionTrace,
    routeDecisions: state.routeDecisions,
  }
}

// ============ Store ============

export const useExecutionStore = create<ExecutionStore>((set, get) => {
  const manager = getExecutionManager()

  const getCurrentState = (): GraphExecutionState => {
    const { contexts, currentGraphId } = get()
    return getOrCreateContext(contexts, currentGraphId).state
  }

  const updateCurrentState = (updates: Partial<GraphExecutionState>) => {
    const { contexts, currentGraphId } = get()
    if (!currentGraphId) return

    const context = getOrCreateContext(contexts, currentGraphId)
    const newState = { ...context.state, ...updates }
    const newContext = { ...context, state: newState }

    const newContexts = new Map(contexts)
    newContexts.set(currentGraphId, newContext)

    set({
      contexts: newContexts,
      ...syncComputedProperties(newState),
    })
  }

  return {
    // ============ State ============
    contexts: new Map<string, ExecutionContext>(),
    currentGraphId: null,
    steps: [],
    isExecuting: false,
    showPanel: false,
    activeNodeId: null,
    pendingInterrupts: new Map<string, InterruptInfo>(),
    currentState: null,
    executionTrace: [],
    routeDecisions: [],

    // ============ Graph Switching ============

    setCurrentGraphId: (graphId: string | null) => {
      const { contexts, clearGraphState } = get()

      if (graphId) {
        manager.recordAccess(graphId)
        const toEvict = manager.getGraphsToEvict(contexts)
        toEvict.forEach(id => clearGraphState(id))
      }

      const context = getOrCreateContext(contexts, graphId)

      if (graphId && !contexts.has(graphId)) {
        const newContexts = new Map(contexts)
        newContexts.set(graphId, context)
        set({
          contexts: newContexts,
          currentGraphId: graphId,
          ...syncComputedProperties(context.state),
        })
      } else {
        set({
          currentGraphId: graphId,
          ...syncComputedProperties(context.state),
        })
      }
    },

    // ============ State Updates ============

    updateGraphState: (graphId: string, updates: Partial<GraphExecutionState>) => {
      const { contexts, currentGraphId } = get()
      const context = getOrCreateContext(contexts, graphId)
      const newState = { ...context.state, ...updates }
      const newContext = { ...context, state: newState }

      const newContexts = new Map(contexts)
      newContexts.set(graphId, newContext)

      if (graphId === currentGraphId) {
        set({ contexts: newContexts, ...syncComputedProperties(newState) })
      } else {
        set({ contexts: newContexts })
      }
    },

    // ============ Step Management ============

    addStep: (step: ExecutionStep) => {
      const state = getCurrentState()
      if (state.steps.some(s => s.id === step.id)) return
      updateCurrentState({ steps: [...state.steps, step] })
    },

    updateStep: (stepId: string, updates: Partial<ExecutionStep>) => {
      const state = getCurrentState()
      const idx = state.steps.findIndex(s => s.id === stepId)
      if (idx === -1) return

      const step = state.steps[idx]
      const hasChanges = Object.keys(updates).some(
        k => step[k as keyof ExecutionStep] !== updates[k as keyof ExecutionStep]
      )
      if (!hasChanges) return

      const newSteps = [...state.steps]
      // Deep merge data field instead of overwriting
      const mergedData = updates.data
        ? { ...(step.data || {}), ...updates.data }
        : step.data
      newSteps[idx] = { ...step, ...updates, data: mergedData }
      updateCurrentState({ steps: newSteps })
    },

    appendContent: (stepId: string, text: string) => {
      if (!text) return

      // Accumulate to buffer instead of immediate update
      const existing = pendingContentUpdates.get(stepId) || ''
      pendingContentUpdates.set(stepId, existing + text)

      // Schedule batch update (execute once per microtask cycle)
      if (!contentUpdateScheduled) {
        contentUpdateScheduled = true
        queueMicrotask(() => {
          contentUpdateScheduled = false
          const updates = new Map(pendingContentUpdates)
          pendingContentUpdates.clear()

          const state = getCurrentState()
          const newSteps = [...state.steps]
          let hasChanges = false

          updates.forEach((content, id) => {
            const idx = newSteps.findIndex(s => s.id === id)
            if (idx !== -1) {
              newSteps[idx] = {
                ...newSteps[idx],
                content: (newSteps[idx].content || '') + content
              }
              hasChanges = true
            }
          })

          if (hasChanges) {
            updateCurrentState({ steps: newSteps })
          }
        })
      }
    },

    // ============ Panel ============

    togglePanel: (show?: boolean) => {
      const state = getCurrentState()
      updateCurrentState({ showPanel: show ?? !state.showPanel })
    },

    // ============ Interrupt Management ============

    addInterrupt: (interrupt: InterruptInfo) => {
      const state = getCurrentState()
      const newInterrupts = new Map(state.pendingInterrupts)
      newInterrupts.set(interrupt.nodeId, interrupt)

      const nodeStep = state.steps.find(
        s => s.nodeId === interrupt.nodeId && s.status === 'running'
      )

      if (nodeStep) {
        const updatedSteps = state.steps.map(s =>
          s.id === nodeStep.id ? { ...s, status: 'waiting' as const } : s
        )
        updateCurrentState({ pendingInterrupts: newInterrupts, steps: updatedSteps })
      } else {
        updateCurrentState({ pendingInterrupts: newInterrupts })
      }
    },

    removeInterrupt: (nodeId: string) => {
      const state = getCurrentState()
      const newInterrupts = new Map(state.pendingInterrupts)
      newInterrupts.delete(nodeId)
      updateCurrentState({ pendingInterrupts: newInterrupts })
    },

    clearInterrupts: () => {
      updateCurrentState({ pendingInterrupts: new Map() })
    },

    getInterrupt: (nodeId: string) => getCurrentState().pendingInterrupts.get(nodeId),

    // ============ Execution Control ============

    clear: () => {
      updateCurrentState({
        steps: [],
        currentState: null,
        executionTrace: [],
        routeDecisions: [],
      })
    },

    clearGraphState: (graphId: string) => {
      const { contexts, currentGraphId } = get()

      const context = contexts.get(graphId)
      if (context?.abortController) {
        context.abortController.abort()
      }

      manager.removeFromAccess(graphId)

      const newContexts = new Map(contexts)
      newContexts.delete(graphId)

      if (graphId === currentGraphId) {
        set({ contexts: newContexts, ...syncComputedProperties(createEmptyGraphState()) })
      } else {
        set({ contexts: newContexts })
      }
    },

    getRunningGraphIds: () => {
      const { contexts } = get()
      const running: string[] = []
      contexts.forEach((ctx, id) => {
        if (ctx.state.isExecuting) running.push(id)
      })
      return running
    },

    setExecuting: (isExecuting: boolean) => {
      const state = getCurrentState()
      updateCurrentState({
        isExecuting,
        activeNodeId: isExecuting ? state.activeNodeId : null,
      })
    },

    // ============ Execution Context ============

    getContext: (graphId: string) => {
      const { contexts } = get()
      return getOrCreateContext(contexts, graphId)
    },

    setAbortController: (graphId: string, controller: AbortController | null) => {
      const { contexts } = get()
      const context = getOrCreateContext(contexts, graphId)
      const newContexts = new Map(contexts)
      newContexts.set(graphId, { ...context, abortController: controller })
      set({ contexts: newContexts })
    },

    setThreadId: (graphId: string, threadId: string | null) => {
      const { contexts } = get()
      const context = getOrCreateContext(contexts, graphId)
      const newContexts = new Map(contexts)
      newContexts.set(graphId, { ...context, threadId })
      set({ contexts: newContexts })
    },

    // ============ Command Mode ============

    updateState: (stateUpdate: Partial<GraphState>) => {
      const state = getCurrentState()
      updateCurrentState({
        currentState: state.currentState
          ? { ...state.currentState, ...stateUpdate }
          : (stateUpdate as GraphState),
      })
    },

    addTraceStep: (step: TraceStep) => {
      const state = getCurrentState()
      updateCurrentState({ executionTrace: [...state.executionTrace, step] })
    },

    addRouteDecision: (nodeId, nodeType, decision) => {
      const state = getCurrentState()
      updateCurrentState({
        routeDecisions: [
          ...state.routeDecisions,
          { nodeId, nodeType, decision, timestamp: Date.now() },
        ],
      })
    },

    // ============ Execution Methods ============

    startExecution: async (input: string) => {
      const store = get()
      if (!input.trim()) return

      const graphId = store.currentGraphId || agentService.getCachedGraphId()
      if (!graphId) {
        console.error('No graph_id available for execution')
        return
      }

      // Cancel previous execution
      const existingContext = store.getContext(graphId)
      if (existingContext.abortController) {
        existingContext.abortController.abort()
      }

      const abortController = new AbortController()
      store.setAbortController(graphId, abortController)
      store.setThreadId(graphId, null)

      store.clearInterrupts()
      store.updateGraphState(graphId, {
        steps: [],
        isExecuting: true,
        activeNodeId: null,
        pendingInterrupts: new Map(),
      })
      store.togglePanel(true)

      const workflowId = generateId('workflow')
      store.addStep({
        id: workflowId,
        nodeId: 'system',
        nodeLabel: 'Workflow',
        stepType: 'node_lifecycle',
        title: 'Workflow Execution',
        status: 'running',
        startTime: Date.now(),
        data: { input },
      })

      // Create event processing context
      const ctx = createEventProcessorContext(
        graphId,
        genId,
        () => get().steps
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

      try {
        const result = await streamChat({
          message: input,
          threadId: null,
          graphId,
          metadata: {},
          signal: abortController.signal,
          onEvent: (evt: ChatStreamEvent) => {
            const s = get()

            // Use shared event processor
            const eventResult = processEvent(evt, ctx, storeAdapter)

            // Update currentThoughtId in context
            ctx.currentThoughtId = eventResult.currentThoughtId

            // Special handling for stopped event to update workflow step
            if (eventResult.shouldStop && eventResult.stopReason === 'stopped') {
              s.updateStep(workflowId, { status: 'error', endTime: Date.now() })
            }
          },
        })

        if (result.threadId) store.setThreadId(graphId, result.threadId)

        const graphContext = store.getContext(graphId)
        const workflowStep = graphContext.state.steps.find(s => s.id === workflowId)
        store.updateStep(workflowId, {
          status: 'success',
          endTime: Date.now(),
          duration: Date.now() - (workflowStep?.startTime || Date.now()),
        })
      } catch (e: unknown) {
        const error = e as { name?: string; message?: string }
        store.updateStep(workflowId, { status: 'error', endTime: Date.now() })
        if (error?.name !== 'AbortError') {
          store.addStep({
            id: generateId('error'),
            nodeId: 'system',
            nodeLabel: 'Error',
            stepType: 'system_log',
            title: 'Execution Error',
            status: 'error',
            startTime: Date.now(),
            content: String(error?.message || e),
          })
        }
      } finally {
        store.updateGraphState(graphId, { isExecuting: false })
        store.setAbortController(graphId, null)
      }
    },

    stopExecution: async () => {
      const { currentGraphId, getContext, setAbortController, setThreadId, updateGraphState } = get()
      if (!currentGraphId) return

      const context = getContext(currentGraphId)

      if (context.abortController) {
        context.abortController.abort()
        setAbortController(currentGraphId, null)
      }

      if (context.threadId) {
        try {
          const { apiPost } = await import('@/lib/api-client')
          await apiPost('chat/stop', { thread_id: context.threadId })
        } catch (error) {
          console.error('Failed to stop execution:', error)
        }
        setThreadId(currentGraphId, null)
      }

      updateGraphState(currentGraphId, { isExecuting: false, activeNodeId: null })
    },
  }
})
