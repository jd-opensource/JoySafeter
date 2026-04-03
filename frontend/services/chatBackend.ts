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
  type:
    | 'content'
    | 'tool_start'
    | 'tool_end'
    | 'node_start'
    | 'node_end'
    | 'status'
    | 'error'
    | 'done'
    | 'thread_id'
    | 'model_input'
    | 'model_output'
    | 'interrupt'
    | 'command'
    | 'route_decision'
    | 'loop_iteration'
    | 'parallel_task'
    | 'state_update'
    | 'code_agent_thought'
    | 'code_agent_code'
    | 'code_agent_observation'
    | 'code_agent_final_answer'
    | 'code_agent_planning'
    | 'code_agent_error'
    | 'file_event'
  node_name: string
  run_id: string
  timestamp: number
  thread_id: string
  data: any
  // Trace / Observation 层级信息 (Phase D)
  trace_id?: string
  observation_id?: string
  parent_observation_id?: string
}

/**
 * Content event data structure
 */
export interface ContentEventData {
  delta: string // Incremental text
}

/**
 * Tool Start event data structure
 */
export interface ToolStartEventData {
  tool_name: string
  tool_input: any
}

/**
 * Tool End event data structure
 */
export interface ToolEndEventData {
  tool_name: string
  tool_output: any
  duration?: number
  status?: 'success' | 'error'
  files_changed?: Array<{ path: string; action: string }> | null
}

/**
 * Node Start event data structure
 */
export interface NodeStartEventData {
  node_name: string
  node_label?: string
  node_id?: string
}

/**
 * Node End event data structure
 */
export interface NodeEndEventData {
  node_name: string
  node_label?: string
  node_id?: string
  duration?: number
  status?: 'success' | 'error'
}

/**
 * Error event data structure
 */
export interface ErrorEventData {
  message: string
  error_code?: string // Structured error code for i18n (e.g., MODEL_NOT_FOUND, MODEL_NO_CREDENTIALS)
  code?: string // Legacy: e.g., "stopped" indicates user stopped
  params?: Record<string, string> // Parameters for i18n interpolation (e.g., {model: "gpt-4o", provider: "openai"})
}

/**
 * Model Input event data structure
 */
export interface ModelInputEventData {
  messages: any[] // Input message list
  model_name: string
  model_provider: string
}

/**
 * Model Output event data structure
 */
export interface ModelOutputEventData {
  output: any // AIMessage object
  model_name: string
  model_provider: string
  usage_metadata?: any // Usage metadata (token usage, etc.)
  prompt_tokens?: number
  completion_tokens?: number
  total_tokens?: number
}

/**
 * Interrupt event data structure
 */
export interface InterruptEventData {
  node_name: string
  node_label?: string
  state: any // Current state snapshot
  thread_id: string
}

/**
 * CodeAgent Thought event data structure
 */
export interface CodeAgentThoughtEventData {
  node_name: string
  step: number
  content: string
}

/**
 * CodeAgent Code event data structure
 */
export interface CodeAgentCodeEventData {
  node_name: string
  step: number
  code: string
}

/**
 * CodeAgent Observation event data structure
 */
export interface CodeAgentObservationEventData {
  node_name: string
  step: number
  observation: string
  has_error?: boolean
}

/**
 * CodeAgent Final Answer event data structure
 */
export interface CodeAgentFinalAnswerEventData {
  node_name: string
  step: number
  answer: any
}

/**
 * CodeAgent Planning event data structure
 */
export interface CodeAgentPlanningEventData {
  node_name: string
  step: number
  plan: string
  is_update?: boolean
}

/**
 * CodeAgent Error event data structure
 */
export interface CodeAgentErrorEventData {
  node_name: string
  step: number
  error: string
}

/**
 * Unified streaming event type (using standardized envelope structure)
 */
export type ChatStreamEvent = StreamEventEnvelope
