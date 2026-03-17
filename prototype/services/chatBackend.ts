
/**
 * Command event data structure
 */
export interface CommandEventData {
  update?: Record<string, any>
  goto?: string
  reason?: string
}

/**
 * Route decision event data structure
 */
export interface RouteDecisionEventData {
  node_id: string
  node_type: 'condition' | 'router' | 'loop'
  result: boolean | string
  reason: string
  goto: string
  evaluated_rules?: Array<{
    rule: string
    condition: string
    matched: boolean
  }>
  expression?: string // Expression for Condition node
}

/**
 * Loop iteration event data structure
 */
export interface LoopIterationEventData {
  loop_node_id: string
  iteration: number
  max_iterations: number
  condition_met: boolean
  reason: string
  condition_type?: 'while' | 'forEach' | 'doWhile'
  condition?: string
}

/**
 * Parallel task event data structure
 */
export interface ParallelTaskEventData {
  task_id: string
  status: 'started' | 'completed' | 'error'
  result?: any
  error_msg?: string
}

/**
 * State update event data structure
 */
export interface StateUpdateEventData {
  updated_fields: string[]
  state_snapshot: Partial<any> // GraphState
}

/**
 * Standardized SSE event envelope structure
 * Consistent with backend format in backend/app/api/v1/chat.py
 */
export interface StreamEventEnvelope {
  type: 'content' | 'tool_start' | 'tool_end' | 'node_start' | 'node_end' | 'status' | 'error' | 'done' | 'thread_id' | 'model_input' | 'model_output' | 'interrupt' | 'command' | 'route_decision' | 'loop_iteration' | 'parallel_task' | 'state_update' | 'code_agent_thought' | 'code_agent_code' | 'code_agent_observation' | 'code_agent_final_answer' | 'code_agent_planning' | 'code_agent_error';
  node_name: string;
  run_id: string;
  timestamp: number;
  thread_id: string;
  data: any;
  // Trace / Observation 层级信息 (Phase D)
  trace_id?: string;
  observation_id?: string;
  parent_observation_id?: string;
}

/**
 * Content event data structure
 */
export interface ContentEventData {
  delta: string; // Incremental text
}

/**
 * Tool Start event data structure
 */
export interface ToolStartEventData {
  tool_name: string;
  tool_input: any;
}

/**
 * Tool End event data structure
 */
export interface ToolEndEventData {
  tool_name: string;
  tool_output: any;
  duration?: number;
  status?: 'success' | 'error';
}

/**
 * Node Start event data structure
 */
export interface NodeStartEventData {
  node_name: string;
  node_label?: string;
  node_id?: string;
}

/**
 * Node End event data structure
 */
export interface NodeEndEventData {
  node_name: string;
  node_label?: string;
  node_id?: string;
  duration?: number;
  status?: 'success' | 'error';
}

/**
 * Error event data structure
 */
export interface ErrorEventData {
  message: string;
  code?: string; // Error code, e.g., "stopped" indicates user stopped
}

/**
 * Status event data structure
 */
export interface StatusEventData {
  message: string;
}

/**
 * Model Input event data structure
 */
export interface ModelInputEventData {
  messages: any[]; // Input message list
  model_name: string;
  model_provider: string;
}

/**
 * Model Output event data structure
 */
export interface ModelOutputEventData {
  output: any; // AIMessage object
  model_name: string;
  model_provider: string;
  usage_metadata?: any; // Usage metadata (token usage, etc.)
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
}

/**
 * Interrupt event data structure
 */
export interface InterruptEventData {
  node_name: string;
  node_label?: string;
  state: any; // Current state snapshot
  thread_id: string;
}

/**
 * CodeAgent Thought event data structure
 */
export interface CodeAgentThoughtEventData {
  node_name: string;
  step: number;
  content: string;
}

/**
 * CodeAgent Code event data structure
 */
export interface CodeAgentCodeEventData {
  node_name: string;
  step: number;
  code: string;
}

/**
 * CodeAgent Observation event data structure
 */
export interface CodeAgentObservationEventData {
  node_name: string;
  step: number;
  observation: string;
  has_error?: boolean;
}

/**
 * CodeAgent Final Answer event data structure
 */
export interface CodeAgentFinalAnswerEventData {
  node_name: string;
  step: number;
  answer: any;
}

/**
 * CodeAgent Planning event data structure
 */
export interface CodeAgentPlanningEventData {
  node_name: string;
  step: number;
  plan: string;
  is_update?: boolean;
}

/**
 * CodeAgent Error event data structure
 */
export interface CodeAgentErrorEventData {
  node_name: string;
  step: number;
  error: string;
}

/**
 * Unified streaming event type (using standardized envelope structure)
 */
export type ChatStreamEvent = StreamEventEnvelope;

export interface StreamChatParams {
  message: string;
  threadId?: string | null;
  graphId?: string | null;
  metadata?: Record<string, any>;
  signal?: AbortSignal;
  onEvent: (evt: ChatStreamEvent) => void;
}

import { apiStream } from '@/lib/api-client'

const sseSplitRegex = /\n\n/

function parseSseChunk(chunk: string): ChatStreamEvent[] {
  // SSE can contain multiple "data:" lines; backend uses single data: <json>
  const events: ChatStreamEvent[] = []
  const lines = chunk.split('\n')
  for (const line of lines) {
    const trimmed = line.trim()
    if (!trimmed.startsWith('data:')) continue
    const payloadStr = trimmed.slice('data:'.length).trim()
    if (!payloadStr) continue
    try {
      const parsed = JSON.parse(payloadStr)
      // Validate if it's in standardized format
      if (parsed && typeof parsed === 'object' && parsed.type && parsed.data !== undefined) {
        events.push(parsed as ChatStreamEvent)
      }
    } catch (e) {
      // Ignore malformed chunks
      console.warn('Failed to parse SSE chunk:', e)
    }
  }
  return events
}

/**
 * Stream chat via POST /v1/chat/stream (SSE).
 *
 * Uses unified API client to handle SSE streaming requests, including CSRF token and authentication handling.
 */
export async function streamChat(params: StreamChatParams): Promise<{ threadId?: string }> {
  const { message, threadId, graphId, metadata, signal, onEvent } = params

  // Check if aborted before making request
  if (signal?.aborted) {
    return { threadId: threadId || undefined }
  }

  try {
    // Use unified apiStream method, automatically handles CSRF token and authentication
    const resp = await apiStream(
      'chat/stream',
      {
        message,
        thread_id: threadId || null,
        graph_id: graphId || null,
        metadata: metadata || {},
      },
      {
        signal,
        withAuth: true,
      }
    )

    if (!resp.body) {
      throw new Error('Response body is null')
    }

    const reader = resp.body.getReader()
    const decoder = new TextDecoder('utf-8')

    let buffer = ''
    let latestThreadId: string | undefined = threadId || undefined

    try {
      while (true) {
        const { value, done } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const parts = buffer.split(sseSplitRegex)
        buffer = parts.pop() || ''

        for (const part of parts) {
          const evts = parseSseChunk(part)
          for (const evt of evts) {
            const tid = (evt as any)?.thread_id
            if (typeof tid === 'string' && tid) latestThreadId = tid
            onEvent(evt)
          }
        }
      }
    } finally {
      reader.releaseLock()
    }

    return { threadId: latestThreadId }
  } catch (e: any) {
    if (e?.name === 'AbortError') {
      // Request was aborted, return current threadId
      return { threadId: threadId || undefined }
    }
    throw e
  }
}
