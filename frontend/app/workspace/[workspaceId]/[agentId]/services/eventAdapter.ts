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

// Main Adapter Function

export function mapChatEventToExecutionStep(
  evt: ChatStreamEvent,
  ctx: EventAdapterContext
): AdapterResult {
  const { currentThoughtId, toolStepMap, nodeStepMap, modelStepMap, genId, getSteps } = ctx
  const { type, node_name, run_id, timestamp, data } = evt

  // ========== Error Event ==========
  if (type === 'error') {
    const errorData = data as ErrorEventData
    const errorMsg = errorData?.message || 'Unknown error'
    const errorCode = errorData?.code

    // Check if this is a stop event (determined by code or message)
    if (errorCode === 'stopped' || errorMsg === 'Stream stopped' || errorMsg.includes('stopped')) {
      return { type: 'stopped' }
    }

    return {
      type: 'add_step',
      step: {
        id: genId('error'),
        nodeId: node_name || 'system',
        nodeLabel: 'Error',
        stepType: 'system_log',
        title: 'Error',
        status: 'error',
        startTime: timestamp || Date.now(),
        content: errorMsg,
      },
    }
  }

  // ========== Content Event (Agent Thought) ==========
  if (type === 'content') {
    const contentData = data as ContentEventData
    const delta = contentData?.delta || ''
    if (!delta) return { type: 'noop' }

    // If no current thought step, create one
    if (!currentThoughtId) {
      const thoughtId = genId('thought')
      return {
        type: 'add_step',
        step: {
          id: thoughtId,
          nodeId: node_name || 'agent',
          nodeLabel: node_name || 'Agent',
          stepType: 'agent_thought',
          title: `Reasoning (${node_name || 'Agent'})`,
          status: 'running',
          startTime: timestamp || Date.now(),
          content: delta,
        },
      }
    }

    // Append content to existing thought
    return {
      type: 'append_content',
      stepId: currentThoughtId,
      content: delta,
    }
  }

  // ========== Tool Start Event ==========
  if (type === 'tool_start') {
    const toolData = data as ToolStartEventData
    const toolName = toolData?.tool_name || 'tool'
    const toolInput = toolData?.tool_input

    const toolId = genId('tool')
    // Use tool_name:run_id as key to support concurrent execution
    const toolKey = run_id ? `${toolName}:${run_id}` : toolName
    toolStepMap.set(toolKey, toolId)

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
      },
    }
  }

  // ========== Tool End Event ==========
  if (type === 'tool_end') {
    const toolData = data as ToolEndEventData
    const toolName = toolData?.tool_name || 'tool'
    const toolOutput = toolData?.tool_output

    // Try to match using run_id, fallback to tool_name if not available
    const toolKey = run_id ? `${toolName}:${run_id}` : toolName
    let toolId = toolStepMap.get(toolKey)

    // If not found, try using only tool_name (backward compatible)
    if (!toolId) {
      toolId = toolStepMap.get(toolName)
      if (toolId) {
        // Update mapping to use new key
        toolStepMap.delete(toolName)
        toolStepMap.set(toolKey, toolId)
      }
    }

    if (!toolId) return { type: 'noop' }

    // Get existing step to preserve request data
    const existingStep = getSteps().find((s) => s.id === toolId)
    toolStepMap.delete(toolKey)

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

  // ========== Node Start Event ==========
  if (type === 'node_start') {
    const nodeData = data as NodeStartEventData
    const nodeId = node_name || nodeData?.node_name || 'unknown'
    const stepId = genId('node')

    // Use node_name:run_id as key to support concurrent execution
    const nodeKey = run_id ? `${nodeId}:${run_id}` : nodeId
    nodeStepMap.set(nodeKey, stepId)

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
      },
    }
  }

  // ========== Node End Event ==========
  if (type === 'node_end') {
    const nodeData = data as NodeEndEventData
    const nodeId = node_name || nodeData?.node_name || 'unknown'

    // Try to match using run_id
    const nodeKey = run_id ? `${nodeId}:${run_id}` : nodeId
    let stepId = nodeStepMap.get(nodeKey)

    // If not found, try using only node_name (backward compatible)
    if (!stepId) {
      stepId = nodeStepMap.get(nodeId)
      if (stepId) {
        // Update mapping to use new key
        nodeStepMap.delete(nodeId)
        nodeStepMap.set(nodeKey, stepId)
      }
    }

    // If found through mapping, update directly
    if (stepId) {
      nodeStepMap.delete(nodeKey)
      return {
        type: 'update_step',
        stepId: stepId,
        updates: {
          status: (nodeData?.status === 'error' ? 'error' : 'success') as 'success' | 'error',
          endTime: timestamp || Date.now(),
          duration: nodeData?.duration,
        },
      }
    }

    // If not found in mapping, try searching through step list (backward compatible)
    const nodeStep = getSteps().find(
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
        },
      }
    }

    // If corresponding start step not found, create a new step
    return {
      type: 'add_step',
      step: {
        id: genId('node'),
        nodeId: node_name || nodeData?.node_name || 'unknown',
        nodeLabel: nodeData?.node_label || node_name || 'Unknown Node',
        stepType: 'node_lifecycle',
        title: nodeData?.node_label || node_name || 'Node',
        status: (nodeData?.status === 'error' ? 'error' : 'success') as 'success' | 'error',
        startTime: timestamp || Date.now(),
        endTime: timestamp || Date.now(),
        duration: nodeData?.duration,
      },
    }
  }

  // ========== Done Event ==========
  if (type === 'done') {
    return { type: 'done' }
  }

  // ========== Status Event ==========
  if (type === 'status') {
    // Can handle status information here, return noop for now
    return { type: 'noop' }
  }

  // ========== Model Input Event ==========
  if (type === 'model_input') {
    const modelData = data as ModelInputEventData
    const modelName = modelData?.model_name || 'unknown'
    const modelProvider = modelData?.model_provider || 'unknown'
    const messages = modelData?.messages || []

    const stepId = genId('model_io')

    // Use run_id to record this step's ID for subsequent model_output merging
    if (run_id) {
      modelStepMap.set(run_id, stepId)
    }

    return {
      type: 'add_step',
      step: {
        id: stepId,
        nodeId: node_name || 'model',
        nodeLabel: `${modelProvider}/${modelName}`,
        stepType: 'model_io',
        title: `Model I/O (${modelProvider}/${modelName})`,
        status: 'running', // Waiting for output
        startTime: timestamp || Date.now(),
        data: {
          messages: messages,
          model_name: modelName,
          model_provider: modelProvider,
          run_id: run_id,
          // output field will be populated in model_output event
        },
      },
    }
  }

  // ========== Model Output Event ==========
  if (type === 'model_output') {
    const modelData = data as ModelOutputEventData
    const modelName = modelData?.model_name || 'unknown'
    const modelProvider = modelData?.model_provider || 'unknown'
    const output = modelData?.output
    const usageMetadata = modelData?.usage_metadata

    // Try to find corresponding model_input step and update
    if (run_id && modelStepMap.has(run_id)) {
      const existingStepId = modelStepMap.get(run_id)!
      modelStepMap.delete(run_id) // Clean up to prevent duplicate updates

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
        },
      }
    }

    // If corresponding input not found (rare case), create independent output step
    const stepId = genId('model_output')
    return {
      type: 'add_step',
      step: {
        id: stepId,
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
      },
    }
  }

  // ========== Interrupt Event ==========
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

  // ========== Thread ID Event ==========
  if (type === 'thread_id') {
    // Initial handshake event, no processing needed
    return { type: 'noop' }
  }

  // ========== Command Event ==========
  if (type === 'command') {
    const commandData = data as CommandEventData
    return {
      type: 'command',
      command: commandData,
      nodeId: node_name || 'unknown',
    }
  }

  // ========== Route Decision Event ==========
  if (type === 'route_decision') {
    const decisionData = data as RouteDecisionEventData
    return {
      type: 'route_decision',
      decision: decisionData,
    }
  }

  // ========== Loop Iteration Event ==========
  if (type === 'loop_iteration') {
    const iterationData = data as LoopIterationEventData
    return {
      type: 'loop_iteration',
      iteration: iterationData,
    }
  }

  // ========== Parallel Task Event ==========
  if (type === 'parallel_task') {
    const taskData = data as ParallelTaskEventData
    return {
      type: 'parallel_task',
      task: taskData,
    }
  }

  // ========== State Update Event ==========
  if (type === 'state_update') {
    const updateData = data as StateUpdateEventData
    return {
      type: 'state_update',
      update: updateData,
    }
  }

  // ========== CodeAgent Thought Event ==========
  if (type === 'code_agent_thought') {
    const thoughtData = data as CodeAgentThoughtEventData
    return {
      type: 'add_step',
      step: {
        id: genId('ca_thought'),
        nodeId: thoughtData.node_name || node_name || 'code_agent',
        nodeLabel: 'CodeAgent',
        stepType: 'code_agent_thought',
        title: `Thinking (Step ${thoughtData.step})`,
        status: 'success',
        startTime: timestamp || Date.now(),
        content: thoughtData.content,
        data: { step: thoughtData.step },
      },
    }
  }

  // ========== CodeAgent Code Event ==========
  if (type === 'code_agent_code') {
    const codeData = data as CodeAgentCodeEventData
    return {
      type: 'add_step',
      step: {
        id: genId('ca_code'),
        nodeId: codeData.node_name || node_name || 'code_agent',
        nodeLabel: 'CodeAgent',
        stepType: 'code_agent_code',
        title: `Code (Step ${codeData.step})`,
        status: 'success',
        startTime: timestamp || Date.now(),
        content: codeData.code,
        data: { step: codeData.step },
      },
    }
  }

  // ========== CodeAgent Observation Event ==========
  if (type === 'code_agent_observation') {
    const obsData = data as CodeAgentObservationEventData
    return {
      type: 'add_step',
      step: {
        id: genId('ca_obs'),
        nodeId: obsData.node_name || node_name || 'code_agent',
        nodeLabel: 'CodeAgent',
        stepType: 'code_agent_observation',
        title: `Observation (Step ${obsData.step})`,
        status: obsData.has_error ? 'error' : 'success',
        startTime: timestamp || Date.now(),
        content: obsData.observation,
        data: { step: obsData.step, has_error: obsData.has_error },
      },
    }
  }

  // ========== CodeAgent Final Answer Event ==========
  if (type === 'code_agent_final_answer') {
    const answerData = data as CodeAgentFinalAnswerEventData
    const answerStr = typeof answerData.answer === 'string'
      ? answerData.answer
      : JSON.stringify(answerData.answer, null, 2)
    return {
      type: 'add_step',
      step: {
        id: genId('ca_answer'),
        nodeId: answerData.node_name || node_name || 'code_agent',
        nodeLabel: 'CodeAgent',
        stepType: 'code_agent_final_answer',
        title: 'Final Answer',
        status: 'success',
        startTime: timestamp || Date.now(),
        content: answerStr,
        data: { step: answerData.step, answer: answerData.answer },
      },
    }
  }

  // ========== CodeAgent Planning Event ==========
  if (type === 'code_agent_planning') {
    const planData = data as CodeAgentPlanningEventData
    return {
      type: 'add_step',
      step: {
        id: genId('ca_plan'),
        nodeId: planData.node_name || node_name || 'code_agent',
        nodeLabel: 'CodeAgent',
        stepType: 'code_agent_planning',
        title: planData.is_update ? 'Plan Update' : 'Execution Plan',
        status: 'success',
        startTime: timestamp || Date.now(),
        content: planData.plan,
        data: { step: planData.step, is_update: planData.is_update },
      },
    }
  }

  // ========== CodeAgent Error Event ==========
  if (type === 'code_agent_error') {
    const errorData = data as CodeAgentErrorEventData
    return {
      type: 'add_step',
      step: {
        id: genId('ca_error'),
        nodeId: errorData.node_name || node_name || 'code_agent',
        nodeLabel: 'CodeAgent',
        stepType: 'code_agent_error',
        title: `Error (Step ${errorData.step})`,
        status: 'error',
        startTime: timestamp || Date.now(),
        content: errorData.error,
        data: { step: errorData.step },
      },
    }
  }

  return { type: 'noop' }
}


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
