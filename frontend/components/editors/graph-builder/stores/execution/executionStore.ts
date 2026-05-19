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

import { getExecutionWsClient } from '@/lib/ws/executions/executionWsClient'
import type {
  ExecutionEventFrame,
  ExecutionCompletedFrame,
  ExecutionSnapshotFrame,
} from '@/lib/ws/executions/types'
import type { AppErrorPayload } from '@/types/agent-run'
import type { ExecutionStep, ExecutionTreeNode } from '@/types'

import { buildExecutionTree } from '../../lib/execution-tree-building'
import type { GraphState, TraceStep } from './types'
import { generateId } from './utils'

import {
  createEmptyGraphState,
  createExecutionContext,
  getExecutionManager,
} from './ExecutionManager'
import type {
  ExecutionStore,
  ExecutionContext,
  GraphExecutionState,
  InterruptInfo,
  StartExecutionOptions,
  StartDraftExecutionInput,
} from './types'
import { executionAdapter } from '../../services/executionAdapter'
import { agentService as globalAgentService } from '@/services/agentService'
import { threadService } from '@/services/threadService'
import { useGraphStore } from '../graphStore'

const pendingContentUpdates = new Map<string, string>()
let contentUpdateScheduled = false

/**
 * Per-graph in-flight guard for `startExecution`. A rapid double-click on
 * Run used to mint two Threads (and two orphan runs) before the first
 * dispatch's isExecuting flag propagated. The module-level Set short-circuits
 * re-entry until the first startExecution call finishes its provisioning.
 */
const startInFlight = new Set<string>()

function getOrCreateContext(
  contexts: Map<string, ExecutionContext>,
  graphId: string | null,
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
    treeRoots: state.treeRoots,
    treeNodeMap: state.treeNodeMap,
  }
}

/**
 * Rebuild tree structure from steps and merge into state updates.
 */
function rebuildTree(steps: ExecutionStep[]): {
  treeRoots: ExecutionTreeNode[]
  treeNodeMap: Map<string, ExecutionTreeNode>
} {
  const { roots, nodeMap } = buildExecutionTree(steps)
  return { treeRoots: roots, treeNodeMap: nodeMap }
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
    treeRoots: [],
    treeNodeMap: new Map(),

    // ============ Graph Switching ============

    setCurrentGraphId: (graphId: string | null) => {
      const { contexts, clearGraphState } = get()

      if (graphId) {
        manager.recordAccess(graphId)
        const toEvict = manager.getGraphsToEvict(contexts)
        toEvict.forEach((id) => clearGraphState(id))
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
      if (state.steps.some((s) => s.id === step.id)) return
      const newSteps = [...state.steps, step]
      updateCurrentState({ steps: newSteps, ...rebuildTree(newSteps) })
    },

    updateStep: (stepId: string, updates: Partial<ExecutionStep>) => {
      const state = getCurrentState()
      const idx = state.steps.findIndex((s) => s.id === stepId)
      if (idx === -1) return

      const step = state.steps[idx]
      const hasChanges = Object.keys(updates).some(
        (k) => step[k as keyof ExecutionStep] !== updates[k as keyof ExecutionStep],
      )
      if (!hasChanges) return

      const newSteps = [...state.steps]
      // Deep merge data field instead of overwriting
      const mergedData = updates.data ? { ...(step.data || {}), ...updates.data } : step.data
      newSteps[idx] = { ...step, ...updates, data: mergedData }
      updateCurrentState({ steps: newSteps, ...rebuildTree(newSteps) })
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
            const idx = newSteps.findIndex((s) => s.id === id)
            if (idx !== -1) {
              newSteps[idx] = {
                ...newSteps[idx],
                content: (newSteps[idx].content || '') + content,
              }
              hasChanges = true
            }
          })

          if (hasChanges) {
            updateCurrentState({ steps: newSteps, ...rebuildTree(newSteps) })
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
        (s) => s.nodeId === interrupt.nodeId && s.status === 'running',
      )

      if (nodeStep) {
        const updatedSteps = state.steps.map((s) =>
          s.id === nodeStep.id ? { ...s, status: 'waiting' as const } : s,
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
        treeRoots: [],
        treeNodeMap: new Map(),
      })
    },

    clearGraphState: (graphId: string) => {
      const { contexts, currentGraphId } = get()

      const context = contexts.get(graphId)
      if (context?.subscribedExecutionId) {
        try {
          getExecutionWsClient().unsubscribe(context.subscribedExecutionId)
        } catch {
          /* ignore */
        }
      }
      if (context?.abortController) {
        context.abortController.abort()
      }
      if (context?.timeoutId !== null && context?.timeoutId !== undefined) {
        clearTimeout(context.timeoutId)
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

    setRunId: (graphId: string, runId: string | null) => {
      const { contexts } = get()
      const context = getOrCreateContext(contexts, graphId)
      const newContexts = new Map(contexts)
      newContexts.set(graphId, { ...context, runId })
      set({ contexts: newContexts })
    },

    setSubscribedExecutionId: (graphId: string, executionId: string | null) => {
      const { contexts } = get()
      const context = getOrCreateContext(contexts, graphId)
      const newContexts = new Map(contexts)
      newContexts.set(graphId, { ...context, subscribedExecutionId: executionId })
      set({ contexts: newContexts })
    },

    setTimeoutId: (graphId: string, timeoutId: ReturnType<typeof setTimeout> | null) => {
      const { contexts } = get()
      const context = getOrCreateContext(contexts, graphId)
      const newContexts = new Map(contexts)
      newContexts.set(graphId, { ...context, timeoutId })
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

    addRouteDecision: (nodeId, decision) => {
      const state = getCurrentState()
      updateCurrentState({
        routeDecisions: [...state.routeDecisions, { nodeId, decision, timestamp: Date.now() }],
      })
    },

    // ============ Execution Methods ============

    startExecution: async (
      input: string,
      draftInput?: StartDraftExecutionInput,
      options: StartExecutionOptions = {},
    ) => {
      const store = get()
      if (!input.trim()) return
      const openPanel = options.openPanel ?? true

      const builderState = useGraphStore.getState()
      const agentId = draftInput?.agentId ?? builderState.agentId
      const workspaceId = draftInput?.workspaceId ?? builderState.workspaceId

      if (!agentId || !workspaceId) {
        throw new Error(
          'agentId and workspaceId are required to start execution. Legacy workspace route is no longer supported.',
        )
      }

      const graphId = store.currentGraphId
      if (!graphId) {
        console.error('No graph_id available for execution')
        store.togglePanel(true)
        store.addStep({
          id: generateId('error'),
          nodeId: 'system',
          nodeLabel: 'Error',
          stepType: 'system_log',
          title: 'Execution Error',
          status: 'error',
          startTime: Date.now(),
          content: 'No graph available for execution. Please save your graph first.',
        })
        return
      }

      // Reject concurrent starts on the same graph. Without this, two rapid
      // clicks both pass the isExecuting check (set further down) and each
      // provisions a fresh Thread + Run.
      if (startInFlight.has(graphId)) {
        console.warn(`[execution] startExecution re-entered for ${graphId}; ignoring`)
        return
      }
      startInFlight.add(graphId)
      try {
        // If already executing, cancel the existing backend run before starting a new one
        const currentGraphState = store.getContext(graphId).state
        if (currentGraphState.isExecuting) {
          await get().stopExecution()
        }

        // Cancel previous subscription
        const existingContext = store.getContext(graphId)
        if (existingContext.subscribedExecutionId) {
          try {
            getExecutionWsClient().unsubscribe(existingContext.subscribedExecutionId)
          } catch {
            /* ignore */
          }
        }
        if (existingContext.abortController) {
          existingContext.abortController.abort()
        }

        const abortController = new AbortController()
        store.setAbortController(graphId, abortController)
        store.setRunId(graphId, null)
        store.setSubscribedExecutionId(graphId, null)

        store.updateGraphState(graphId, {
          steps: [],
          isExecuting: true,
          activeNodeId: null,
          pendingInterrupts: new Map(),
        })
        if (openPanel) {
          store.togglePanel(true)
        }

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

        // toolUseId → stepId
        const toolStepMap = new Map<string, string>() // toolUseId → stepId
        let currentThoughtStepId: string | null = null

        /**
         * Handle a single execution event and map it to store operations.
         */
        const handleExecutionEvent = (frame: ExecutionEventFrame) => {
          const { event_type, payload } = frame

          switch (event_type) {
            case 'assistant_text': {
              const text =
                (payload.delta as string) ??
                (payload.content as string) ??
                (payload.text as string) ??
                ''
              if (currentThoughtStepId) {
                store.appendContent(currentThoughtStepId, text)
              } else {
                const stepId = generateId('thought')
                currentThoughtStepId = stepId
                store.addStep({
                  id: stepId,
                  nodeId: 'assistant',
                  nodeLabel: 'Assistant',
                  stepType: 'agent_thought',
                  title: 'Assistant Response',
                  status: 'running',
                  startTime: Date.now(),
                  content: text,
                })
              }
              break
            }

            case 'thinking': {
              const text = (payload.text as string) ?? ''
              const stepId = generateId('thinking')
              currentThoughtStepId = stepId
              store.addStep({
                id: stepId,
                nodeId: 'assistant',
                nodeLabel: 'Assistant',
                stepType: 'agent_thought',
                title: 'Thinking',
                status: 'running',
                startTime: Date.now(),
                content: text,
              })
              break
            }

            case 'tool_use_start': {
              if (currentThoughtStepId) {
                store.updateStep(currentThoughtStepId, { status: 'success', endTime: Date.now() })
                currentThoughtStepId = null
              }
              const toolUseId = (payload.tool_use_id as string) ?? ''
              const toolName = (payload.tool_name as string) ?? 'tool'
              const toolInput = (payload.input as Record<string, unknown>) ?? {}
              const stepId = generateId('tool')
              toolStepMap.set(toolUseId, stepId)
              store.addStep({
                id: stepId,
                nodeId: 'tool',
                nodeLabel: toolName,
                stepType: 'tool_execution',
                title: toolName,
                status: 'running',
                startTime: Date.now(),
                data: { request: toolInput },
              })
              break
            }

            case 'tool_use_end': {
              const toolUseId = (payload.tool_use_id as string) ?? ''
              const isError = (payload.is_error as boolean) ?? false
              const output = payload.output ?? payload.result ?? ''
              const stepId = toolStepMap.get(toolUseId)
              if (stepId) {
                store.updateStep(stepId, {
                  status: isError ? 'error' : 'success',
                  endTime: Date.now(),
                  data: { response: output as string | Record<string, unknown> },
                })
                toolStepMap.delete(toolUseId)
              }
              break
            }

            case 'error': {
              const code = (payload.code as string) ?? ''
              const message =
                (payload.message as string) ?? String(payload.error ?? 'Unknown error')
              if (code === 'stopped') {
                // User-initiated stop — mark workflow as stopped, don't add error step
                store.updateStep(workflowId, { status: 'error', endTime: Date.now() })
              } else {
                store.addStep({
                  id: generateId('error'),
                  nodeId: 'system',
                  nodeLabel: 'Error',
                  stepType: 'system_log',
                  title: 'Error',
                  status: 'error',
                  startTime: Date.now(),
                  content: message,
                })
              }
              break
            }

            case 'artifact_created': {
              const artifactName = (payload.name as string) ?? 'Artifact'
              store.addStep({
                id: generateId('artifact'),
                nodeId: 'artifact',
                nodeLabel: artifactName,
                stepType: 'artifact',
                title: artifactName,
                status: 'success',
                startTime: Date.now(),
                data: payload,
              })
              break
            }

            case 'approval_requested': {
              const nodeId = (payload.node_id as string) ?? 'unknown'
              const nodeLabel = (payload.node_label as string) ?? nodeId
              const threadId = (payload.thread_id as string) ?? ''
              store.addInterrupt({
                nodeId,
                nodeLabel,
                state: payload as Record<string, unknown>,
                threadId,
              })
              break
            }

            case 'approval_resolved': {
              const nodeId = (payload.node_id as string) ?? 'unknown'
              store.removeInterrupt(nodeId)
              break
            }

            // Lifecycle events — handled by onCompleted / noop here
            case 'execution_started':
            case 'execution_status_change':
            case 'execution_completed':
            case 'user_message':
              break

            // Copilot events — handled by separate copilot pipeline
            case 'copilot_status':
            case 'copilot_content':
            case 'copilot_thought_step':
            case 'copilot_tool_call':
            case 'copilot_tool_result':
            case 'copilot_result':
              break

            default:
              // Unknown event types — ignore
              break
          }
        }

        const EXECUTION_TIMEOUT_MS = 10 * 60 * 1000 // 10 minutes
        try {
          const run = draftInput
            ? await executionAdapter.startDraftRun({
                agentId,
                versionId: draftInput.versionId,
                prompt: input,
                workspaceId,
                threadId: draftInput.threadId,
              })
            : await (async () => {
                const agent = await globalAgentService.get(agentId, workspaceId)
                const releaseId = agent.active_release_id
                if (!releaseId) {
                  throw new Error('Agent has no active release. Please publish the agent first.')
                }

                // Every run belongs to a Thread. Build-page "Run" button is a
                // one-off interaction, so we mint a fresh Thread per click — it
                // becomes the session root for container + CLI + Trace.
                const thread = await threadService.create({
                  agent_id: agentId,
                  title: `Run – ${new Date().toLocaleString()}`,
                  workspace_id: workspaceId,
                })

                return executionAdapter.startRun({
                  releaseId,
                  prompt: input,
                  workspaceId,
                  threadId: thread.id,
                })
              })()
          store.setRunId(graphId, run.id)

          const executionId = run.current_execution_id

          const timeoutId = setTimeout(() => {
            const context = getOrCreateContext(get().contexts, graphId)
            if (context.runId) {
              executionAdapter.cancelRun(context.runId).catch(() => {})
            }
            if (context.subscribedExecutionId) {
              try {
                getExecutionWsClient().unsubscribe(context.subscribedExecutionId)
              } catch {
                /* ignore */
              }
            }
            store.addStep({
              id: generateId('timeout'),
              nodeId: 'system',
              nodeLabel: 'System',
              stepType: 'system_log',
              title: 'Execution Timeout',
              status: 'error',
              startTime: Date.now(),
              content: 'Execution timed out after 10 minutes',
            })
            store.updateGraphState(graphId, { isExecuting: false })
          }, EXECUTION_TIMEOUT_MS)
          store.setTimeoutId(graphId, timeoutId)

          await new Promise<void>((resolve, reject) => {
            const onAbort = () => {
              try {
                getExecutionWsClient().unsubscribe(executionId)
              } catch {
                /* ignore */
              }
              resolve()
            }
            abortController.signal.addEventListener('abort', onAbort, { once: true })

            getExecutionWsClient()
              .subscribe(executionId, 0, {
                onEvent: (frame: ExecutionEventFrame) => {
                  try {
                    handleExecutionEvent(frame)
                  } catch (err) {
                    console.warn('[executionStore] Failed to handle execution event:', err)
                  }
                },

                onSnapshot: (frame: ExecutionSnapshotFrame) => {
                  for (const evt of frame.events) {
                    try {
                      handleExecutionEvent({
                        type: 'event',
                        execution_id: frame.execution_id,
                        seq: evt.seq,
                        event_type: evt.event_type,
                        payload: evt.payload,
                        created_at: evt.created_at,
                      })
                    } catch (err) {
                      console.warn('[executionStore] Failed to replay snapshot event:', err)
                    }
                  }
                },

                onCompleted: (frame: ExecutionCompletedFrame) => {
                  abortController.signal.removeEventListener('abort', onAbort)
                  if (currentThoughtStepId) {
                    store.updateStep(currentThoughtStepId, {
                      status: 'success',
                      endTime: Date.now(),
                    })
                    currentThoughtStepId = null
                  }
                  const now = Date.now()
                  const graphContext = store.getContext(graphId)
                  const workflowStep = graphContext.state.steps.find((s) => s.id === workflowId)
                  const status =
                    frame.status === 'succeeded' || frame.status === 'completed'
                      ? 'success'
                      : ('error' as const)
                  store.updateStep(workflowId, {
                    status,
                    endTime: now,
                    duration: now - (workflowStep?.startTime || now),
                  })
                  if (frame.error) {
                    store.addStep({
                      id: generateId('error'),
                      nodeId: 'system',
                      nodeLabel: 'Error',
                      stepType: 'system_log',
                      title: frame.error.code,
                      status: 'error',
                      startTime: now,
                      content: frame.error.message,
                      data: { ...frame.error },
                    })
                  }
                  resolve()
                },

                onError: (error: AppErrorPayload) => {
                  abortController.signal.removeEventListener('abort', onAbort)
                  reject(new Error(`Execution WebSocket error: ${error.message}`))
                },
              })
              .catch((err) => {
                abortController.signal.removeEventListener('abort', onAbort)
                reject(err)
              })

            store.setSubscribedExecutionId(graphId, executionId)
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
          // Clear the execution timeout on any completion path
          const finalContext = store.getContext(graphId)
          if (finalContext.timeoutId !== null) {
            clearTimeout(finalContext.timeoutId)
          }
          // Unsubscribe if still subscribed
          if (finalContext.subscribedExecutionId) {
            try {
              getExecutionWsClient().unsubscribe(finalContext.subscribedExecutionId)
            } catch {
              /* ignore */
            }
          }
          store.updateGraphState(graphId, { isExecuting: false })
          store.setAbortController(graphId, null)
          store.setRunId(graphId, null)
          store.setSubscribedExecutionId(graphId, null)
          store.setTimeoutId(graphId, null)
        }
      } finally {
        startInFlight.delete(graphId)
      }
    },

    startDraftExecution: async (params: StartDraftExecutionInput) => {
      await get().startExecution(params.input, params, { openPanel: false })
    },

    stopExecution: async () => {
      const {
        currentGraphId,
        getContext,
        setAbortController,
        setRunId,
        setSubscribedExecutionId,
        updateGraphState,
      } = get()
      if (!currentGraphId) return

      const context = getContext(currentGraphId)

      // Cancel via executionAdapter
      if (context.runId) {
        try {
          await executionAdapter.cancelRun(context.runId)
        } catch (error) {
          console.error('Failed to cancel run on backend:', error)
          // Surface the failure so the user knows the backend run may still be active
          get().addStep({
            id: generateId('cancel-error'),
            nodeId: 'system',
            nodeLabel: 'System',
            stepType: 'system_log',
            title: 'Cancel Failed',
            status: 'error',
            startTime: Date.now(),
            content: 'Failed to cancel execution on server. It may still be running.',
          })
        }
        setRunId(currentGraphId, null)
      }

      // Unsubscribe from execution WS
      if (context.subscribedExecutionId) {
        try {
          getExecutionWsClient().unsubscribe(context.subscribedExecutionId)
        } catch {
          /* ignore */
        }
        setSubscribedExecutionId(currentGraphId, null)
      }

      if (context.abortController) {
        context.abortController.abort()
        setAbortController(currentGraphId, null)
      }

      updateGraphState(currentGraphId, { isExecuting: false, activeNodeId: null })
    },
  }
})
