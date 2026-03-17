/**
 * Event Adapter - Maps backend ChatStreamEvent to ExecutionStep format
 *
 * This adapter provides a clean separation between backend event format
 * and frontend execution step representation.
 *
 * Uses the standardized SSE envelope structure from backend.
 */

import type {
  ChatStreamEvent,
  ContentEventData,
  ToolStartEventData,
  ToolEndEventData,
  NodeStartEventData,
  NodeEndEventData,
  ErrorEventData,
  ModelInputEventData,
  ModelOutputEventData,
  InterruptEventData,
  CommandEventData,
  RouteDecisionEventData,
  LoopIterationEventData,
  ParallelTaskEventData,
  StateUpdateEventData,
  CodeAgentThoughtEventData,
  CodeAgentCodeEventData,
  CodeAgentObservationEventData,
  CodeAgentFinalAnswerEventData,
  CodeAgentPlanningEventData,
  CodeAgentErrorEventData,
} from '@/services/chatBackend'
import type { ExecutionStep } from '@/types'

import type { InterruptState } from '../stores/execution/types'

export interface EventAdapterContext {
  currentThoughtId: string | null
  toolStepMap: Map<string, string> // key: "tool_name:run_id" or "tool_name" (for backward compatibility)
  nodeStepMap: Map<string, string> // key: "node_name:run_id" or "node_name" (for backward compatibility)
  modelStepMap: Map<string, string> // key: "run_id" - for pairing model_input and model_output
  genId: (prefix: string) => string
  getSteps: () => ExecutionStep[]
}

export type AdapterResult =
  | { type: 'noop' }
  | { type: 'stopped' }
  | { type: 'done' }
  | { type: 'add_step'; step: ExecutionStep }
  | { type: 'append_content'; stepId: string; content: string }
  | { type: 'update_step'; stepId: string; updates: Partial<ExecutionStep>; clearThought?: boolean }
  | { type: 'interrupt'; nodeId: string; nodeLabel: string; state: InterruptState; threadId: string }
  | { type: 'command'; command: CommandEventData; nodeId: string }
  | { type: 'route_decision'; decision: RouteDecisionEventData }
  | { type: 'loop_iteration'; iteration: LoopIterationEventData }
  | { type: 'parallel_task'; task: ParallelTaskEventData }
  | { type: 'state_update'; update: StateUpdateEventData }

type TraceFields = Pick<ExecutionStep, 'traceId' | 'observationId' | 'parentObservationId'>

/**
 * Helper: extract trace/observation fields from event envelope
 */
function extractTraceFields(evt: ChatStreamEvent): TraceFields {
  return {
    traceId: evt.trace_id || undefined,
    observationId: evt.observation_id || undefined,
    parentObservationId: evt.parent_observation_id || undefined,
  }
}

// ============================================================================
// Event Handlers
// ============================================================================

function handleErrorEvent(evt: ChatStreamEvent, ctx: EventAdapterContext, traceFields: TraceFields): AdapterResult {
  const { node_name, timestamp, data } = evt
  const errorData = data as ErrorEventData
  const errorMsg = errorData?.message || 'Unknown error'
  const errorCode = errorData?.code

  if (errorCode === 'stopped' || errorMsg === 'Stream stopped' || errorMsg.includes('stopped')) {
    return { type: 'stopped' }
  }

  return {
    type: 'add_step',
    step: {
      id: ctx.genId('error'),
      nodeId: node_name || 'system',
      nodeLabel: 'Error',
      stepType: 'system_log',
      title: 'Error',
      status: 'error',
      startTime: timestamp || Date.now(),
      content: errorMsg,
      ...traceFields,
    },
  }
}

function handleContentEvent(evt: ChatStreamEvent, ctx: EventAdapterContext, traceFields: TraceFields): AdapterResult {
  const { node_name, timestamp, data } = evt
  const contentData = data as ContentEventData
  const delta = contentData?.delta || ''
  if (!delta) return { type: 'noop' }

  if (!ctx.currentThoughtId) {
    return {
      type: 'add_step',
      step: {
        id: ctx.genId('thought'),
        nodeId: node_name || 'agent',
        nodeLabel: node_name || 'Agent',
        stepType: 'agent_thought',
        title: `Reasoning (${node_name || 'Agent'})`,
        status: 'running',
        startTime: timestamp || Date.now(),
        content: delta,
        ...traceFields,
      },
    }
  }

  return {
    type: 'append_content',
    stepId: ctx.currentThoughtId,
    content: delta,
  }
}

function handleToolEvents(evt: ChatStreamEvent, ctx: EventAdapterContext, traceFields: TraceFields): AdapterResult {
  const { type, node_name, run_id, timestamp, data } = evt

  if (type === 'tool_start') {
    const toolData = data as ToolStartEventData
    const toolName = toolData?.tool_name || 'tool'
    const toolInput = toolData?.tool_input

    const toolId = ctx.genId('tool')
    const toolKey = run_id ? `${toolName}:${run_id}` : toolName
    ctx.toolStepMap.set(toolKey, toolId)

    return {
      type: 'add_step',
      step: {
        id: toolId,
        nodeId: node_name || 'tool',
        nodeLabel: toolName,
        stepType: 'tool_execution',
        title: toolName,
        status: 'running',
        startTime: timestamp || Date.now(),
        data: { request: toolInput },
        ...traceFields,
      },
    }
  }

  if (type === 'tool_end') {
    const toolData = data as ToolEndEventData
    const toolName = toolData?.tool_name || 'tool'
    const toolOutput = toolData?.tool_output

    const toolKey = run_id ? `${toolName}:${run_id}` : toolName
    let toolId = ctx.toolStepMap.get(toolKey)

    if (!toolId) {
      toolId = ctx.toolStepMap.get(toolName)
      if (toolId) {
        ctx.toolStepMap.delete(toolName)
        ctx.toolStepMap.set(toolKey, toolId)
      }
    }

    if (!toolId) return { type: 'noop' }

    const existingStep = ctx.getSteps().find((s) => s.id === toolId)
    ctx.toolStepMap.delete(toolKey)

    return {
      type: 'update_step',
      stepId: toolId,
      updates: {
        status: (toolData?.status === 'error' ? 'error' : 'success') as 'success' | 'error',
        endTime: timestamp || Date.now(),
        duration: toolData?.duration,
        data: {
          request: existingStep?.data?.request,
          response: toolOutput,
        },
      },
    }
  }

  return { type: 'noop' }
}

function handleNodeEvents(evt: ChatStreamEvent, ctx: EventAdapterContext, traceFields: TraceFields): AdapterResult {
  const { type, node_name, run_id, timestamp, data } = evt

  if (type === 'node_start') {
    const nodeData = data as NodeStartEventData
    const nodeId = node_name || nodeData?.node_name || 'unknown'
    const stepId = ctx.genId('node')

    const nodeKey = run_id ? `${nodeId}:${run_id}` : nodeId
    ctx.nodeStepMap.set(nodeKey, stepId)

    return {
      type: 'add_step',
      step: {
        id: stepId,
        nodeId: nodeId,
        nodeLabel: nodeData?.node_label || node_name || 'Unknown Node',
        stepType: 'node_lifecycle',
        title: nodeData?.node_label || node_name || 'Node',
        status: 'running',
        startTime: timestamp || Date.now(),
        ...traceFields,
      },
    }
  }

  if (type === 'node_end') {
    const nodeData = data as NodeEndEventData
    const nodeId = node_name || nodeData?.node_name || 'unknown'

    const nodeKey = run_id ? `${nodeId}:${run_id}` : nodeId
    let stepId = ctx.nodeStepMap.get(nodeKey)

    if (!stepId) {
      stepId = ctx.nodeStepMap.get(nodeId)
      if (stepId) {
        ctx.nodeStepMap.delete(nodeId)
        ctx.nodeStepMap.set(nodeKey, stepId)
      }
    }

    if (stepId) {
      ctx.nodeStepMap.delete(nodeKey)
      return {
        type: 'update_step',
        stepId: stepId,
        updates: {
          status: (nodeData?.status === 'error' ? 'error' : 'success') as 'success' | 'error',
          endTime: timestamp || Date.now(),
          duration: nodeData?.duration,
          data: {
            // @ts-ignore
            payload: nodeData?.payload
          }
        },
      }
    }

    const nodeStep = ctx.getSteps().find(
      (s) => s.stepType === 'node_lifecycle' &&
        (s.nodeId === nodeId || s.nodeId === nodeData?.node_name) &&
        s.status === 'running'
    )

    if (nodeStep) {
      return {
        type: 'update_step',
        stepId: nodeStep.id,
        updates: {
          status: (nodeData?.status === 'error' ? 'error' : 'success') as 'success' | 'error',
          endTime: timestamp || Date.now(),
          duration: nodeData?.duration,
          data: {
            ...nodeStep.data,
            // @ts-ignore
            payload: nodeData?.payload
          }
        },
      }
    }

    return {
      type: 'add_step',
      step: {
        id: ctx.genId('node'),
        nodeId: node_name || nodeData?.node_name || 'unknown',
        nodeLabel: nodeData?.node_label || node_name || 'Unknown Node',
        stepType: 'node_lifecycle',
        title: nodeData?.node_label || node_name || 'Node',
        status: (nodeData?.status === 'error' ? 'error' : 'success') as 'success' | 'error',
        startTime: timestamp || Date.now(),
        endTime: timestamp || Date.now(),
        duration: nodeData?.duration,
        data: {
          // @ts-ignore
          payload: nodeData?.payload
        },
        ...traceFields,
      },
    }
  }

  return { type: 'noop' }
}

function handleModelEvents(evt: ChatStreamEvent, ctx: EventAdapterContext, traceFields: TraceFields): AdapterResult {
  const { type, node_name, run_id, timestamp, data } = evt

  if (type === 'model_input') {
    const modelData = data as ModelInputEventData
    const modelName = modelData?.model_name || 'unknown'
    const modelProvider = modelData?.model_provider || 'unknown'
    const messages = modelData?.messages || []

    const stepId = ctx.genId('model_io')

    if (run_id) {
      ctx.modelStepMap.set(run_id, stepId)
    }

    return {
      type: 'add_step',
      step: {
        id: stepId,
        nodeId: node_name || 'model',
        nodeLabel: `${modelProvider}/${modelName}`,
        stepType: 'model_io',
        title: `Model I/O (${modelProvider}/${modelName})`,
        status: 'running',
        startTime: timestamp || Date.now(),
        data: {
          messages: messages,
          model_name: modelName,
          model_provider: modelProvider,
          run_id: run_id,
        },
        ...traceFields,
      },
    }
  }

  if (type === 'model_output') {
    const modelData = data as ModelOutputEventData
    const modelName = modelData?.model_name || 'unknown'
    const modelProvider = modelData?.model_provider || 'unknown'
    const output = modelData?.output
    const usageMetadata = modelData?.usage_metadata

    if (run_id && ctx.modelStepMap.has(run_id)) {
      const existingStepId = ctx.modelStepMap.get(run_id)!
      ctx.modelStepMap.delete(run_id)

      return {
        type: 'update_step',
        stepId: existingStepId,
        updates: {
          status: 'success',
          endTime: timestamp || Date.now(),
          data: {
            output: output,
            usage_metadata: usageMetadata,
          },
          promptTokens: modelData?.prompt_tokens,
          completionTokens: modelData?.completion_tokens,
          totalTokens: modelData?.total_tokens,
          ...traceFields,
        },
      }
    }

    return {
      type: 'add_step',
      step: {
        id: ctx.genId('model_output'),
        nodeId: node_name || 'model',
        nodeLabel: `${modelProvider}/${modelName}`,
        stepType: 'model_io',
        title: `Model Output (${modelProvider}/${modelName})`,
        status: 'success',
        startTime: timestamp || Date.now(),
        data: {
          output: output,
          model_name: modelName,
          model_provider: modelProvider,
          usage_metadata: usageMetadata,
          run_id: run_id,
        },
        promptTokens: modelData?.prompt_tokens,
        completionTokens: modelData?.completion_tokens,
        totalTokens: modelData?.total_tokens,
        ...traceFields,
      },
    }
  }

  return { type: 'noop' }
}

function handleCodeAgentEvents(evt: ChatStreamEvent, ctx: EventAdapterContext, traceFields: TraceFields): AdapterResult {
  const { type, node_name, timestamp, data } = evt

  if (type === 'code_agent_thought') {
    const thoughtData = data as CodeAgentThoughtEventData
    return {
      type: 'add_step',
      step: {
        id: ctx.genId('ca_thought'),
        nodeId: thoughtData.node_name || node_name || 'code_agent',
        nodeLabel: 'CodeAgent',
        stepType: 'code_agent_thought',
        title: `Thinking (Step ${thoughtData.step})`,
        status: 'success',
        startTime: timestamp || Date.now(),
        content: thoughtData.content,
        data: { step: thoughtData.step },
        ...traceFields,
      },
    }
  }

  if (type === 'code_agent_code') {
    const codeData = data as CodeAgentCodeEventData
    return {
      type: 'add_step',
      step: {
        id: ctx.genId('ca_code'),
        nodeId: codeData.node_name || node_name || 'code_agent',
        nodeLabel: 'CodeAgent',
        stepType: 'code_agent_code',
        title: `Code (Step ${codeData.step})`,
        status: 'success',
        startTime: timestamp || Date.now(),
        content: codeData.code,
        data: { step: codeData.step },
        ...traceFields,
      },
    }
  }

  if (type === 'code_agent_observation') {
    const obsData = data as CodeAgentObservationEventData
    return {
      type: 'add_step',
      step: {
        id: ctx.genId('ca_obs'),
        nodeId: obsData.node_name || node_name || 'code_agent',
        nodeLabel: 'CodeAgent',
        stepType: 'code_agent_observation',
        title: `Observation (Step ${obsData.step})`,
        status: obsData.has_error ? 'error' : 'success',
        startTime: timestamp || Date.now(),
        content: obsData.observation,
        data: { step: obsData.step, has_error: obsData.has_error },
        ...traceFields,
      },
    }
  }

  if (type === 'code_agent_final_answer') {
    const answerData = data as CodeAgentFinalAnswerEventData
    const answerStr = typeof answerData.answer === 'string'
      ? answerData.answer
      : JSON.stringify(answerData.answer, null, 2)
    return {
      type: 'add_step',
      step: {
        id: ctx.genId('ca_answer'),
        nodeId: answerData.node_name || node_name || 'code_agent',
        nodeLabel: 'CodeAgent',
        stepType: 'code_agent_final_answer',
        title: 'Final Answer',
        status: 'success',
        startTime: timestamp || Date.now(),
        content: answerStr,
        data: { step: answerData.step, answer: answerData.answer },
        ...traceFields,
      },
    }
  }

  if (type === 'code_agent_planning') {
    const planData = data as CodeAgentPlanningEventData
    return {
      type: 'add_step',
      step: {
        id: ctx.genId('ca_plan'),
        nodeId: planData.node_name || node_name || 'code_agent',
        nodeLabel: 'CodeAgent',
        stepType: 'code_agent_planning',
        title: planData.is_update ? 'Plan Update' : 'Execution Plan',
        status: 'success',
        startTime: timestamp || Date.now(),
        content: planData.plan,
        data: { step: planData.step, is_update: planData.is_update },
        ...traceFields,
      },
    }
  }

  if (type === 'code_agent_error') {
    const errorData = data as CodeAgentErrorEventData
    return {
      type: 'add_step',
      step: {
        id: ctx.genId('ca_error'),
        nodeId: errorData.node_name || node_name || 'code_agent',
        nodeLabel: 'CodeAgent',
        stepType: 'code_agent_error',
        title: `Error (Step ${errorData.step})`,
        status: 'error',
        startTime: timestamp || Date.now(),
        content: errorData.error,
        data: { step: errorData.step },
        ...traceFields,
      },
    }
  }

  return { type: 'noop' }
}

function handleMiscEvents(evt: ChatStreamEvent, ctx: EventAdapterContext, traceFields: TraceFields): AdapterResult {
  const { type, node_name, data } = evt

  if (type === 'done') return { type: 'done' }
  if (type === 'status') return { type: 'noop' }
  if (type === 'thread_id') return { type: 'noop' }

  if (type === 'interrupt') {
    const interruptData = data as InterruptEventData
    return {
      type: 'interrupt',
      nodeId: interruptData.node_name || node_name || 'unknown',
      nodeLabel: interruptData.node_label || interruptData.node_name || 'Unknown Node',
      state: interruptData.state || {},
      threadId: interruptData.thread_id || evt.thread_id,
    }
  }

  if (type === 'command') {
    return {
      type: 'command',
      command: data as CommandEventData,
      nodeId: node_name || 'unknown',
    }
  }

  if (type === 'route_decision') {
    return {
      type: 'route_decision',
      decision: data as RouteDecisionEventData,
    }
  }

  if (type === 'loop_iteration') {
    return {
      type: 'loop_iteration',
      iteration: data as LoopIterationEventData,
    }
  }

  if (type === 'parallel_task') {
    return {
      type: 'parallel_task',
      task: data as ParallelTaskEventData,
    }
  }

  if (type === 'state_update') {
    return {
      type: 'state_update',
      update: data as StateUpdateEventData,
    }
  }

  return { type: 'noop' }
}

// ============================================================================
// Main Adapter Function
// ============================================================================

export function mapChatEventToExecutionStep(
  evt: ChatStreamEvent,
  ctx: EventAdapterContext
): AdapterResult {
  const traceFields = extractTraceFields(evt)

  switch (evt.type) {
    case 'error':
      return handleErrorEvent(evt, ctx, traceFields)
    case 'content':
      return handleContentEvent(evt, ctx, traceFields)
    case 'tool_start':
    case 'tool_end':
      return handleToolEvents(evt, ctx, traceFields)
    case 'node_start':
    case 'node_end':
      return handleNodeEvents(evt, ctx, traceFields)
    case 'model_input':
    case 'model_output':
      return handleModelEvents(evt, ctx, traceFields)
    case 'code_agent_thought':
    case 'code_agent_code':
    case 'code_agent_observation':
    case 'code_agent_final_answer':
    case 'code_agent_planning':
    case 'code_agent_error':
      return handleCodeAgentEvents(evt, ctx, traceFields)
    default:
      return handleMiscEvents(evt, ctx, traceFields)
  }
}

// ============================================================================
// Helper Builders
// ============================================================================

/**
 * Creates a workflow lifecycle step
 */
export function createWorkflowStep(
  id: string,
  input: string,
  status: 'running' | 'success' | 'error' = 'running'
): ExecutionStep {
  return {
    id,
    nodeId: 'system',
    nodeLabel: 'Workflow',
    stepType: 'node_lifecycle',
    title: 'Workflow Execution',
    status,
    startTime: Date.now(),
    data: { input },
  }
}

/**
 * Creates an error step
 */
export function createErrorStep(
  id: string,
  message: string
): ExecutionStep {
  return {
    id,
    nodeId: 'system',
    nodeLabel: 'Error',
    stepType: 'system_log',
    title: 'Execution Error',
    status: 'error',
    startTime: Date.now(),
    content: message,
  }
}
