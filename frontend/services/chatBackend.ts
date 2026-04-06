/**
 * Command event data structure
 */
export interface CommandEventData {
  update?: Record<string, unknown>
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
  result?: unknown
  error_msg?: string
}

/**
 * State update event data structure
 */
export interface StateUpdateEventData {
  updated_fields: string[]
  state_snapshot: Record<string, unknown>
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
  tool_input: Record<string, unknown>
}

/**
 * Tool End event data structure
 */
export interface ToolEndEventData {
  tool_name: string
  tool_output: string | Record<string, unknown>
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
 * Status event data structure
 */
export interface StatusEventData {
  status: string
  [key: string]: unknown
}

/**
 * Thread ID event data structure
 */
export interface ThreadIdEventData {
  thread_id: string
  [key: string]: unknown
}

/**
 * File event data structure
 */
export interface FileEventData {
  path: string
  action: string
  [key: string]: unknown
}

/**
 * Model Input event data structure
 */
export interface ModelInputEventData {
  messages: Array<Record<string, unknown>> // LangChain message objects
  model_name: string
  model_provider: string
}

/**
 * Model Output event data structure
 */
export interface ModelOutputEventData {
  output: Record<string, unknown> // AIMessage object
  model_name: string
  model_provider: string
  usage_metadata?: { input_tokens?: number; output_tokens?: number; total_tokens?: number }
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
  state: Record<string, unknown> // Current state snapshot
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
  answer: string | Record<string, unknown>
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

// --- Shared envelope fields (excluding type and data) ---
interface ChatWsFrameBase {
  node_name: string
  run_id: string
  timestamp: number
  thread_id: string
  // trace / observation hierarchy info (Phase D)
  trace_id?: string
  observation_id?: string
  parent_observation_id?: string
}

/**
 * Discriminated union WebSocket event frame.
 * TypeScript narrows `data` automatically when you switch on `type`.
 */
export type ChatWsFrame =
  | (ChatWsFrameBase & { type: 'content'; data: ContentEventData })
  | (ChatWsFrameBase & { type: 'tool_start'; data: ToolStartEventData })
  | (ChatWsFrameBase & { type: 'tool_end'; data: ToolEndEventData })
  | (ChatWsFrameBase & { type: 'node_start'; data: NodeStartEventData })
  | (ChatWsFrameBase & { type: 'node_end'; data: NodeEndEventData })
  | (ChatWsFrameBase & { type: 'status'; data: StatusEventData })
  | (ChatWsFrameBase & { type: 'error'; data: ErrorEventData })
  | (ChatWsFrameBase & { type: 'done'; data: Record<string, unknown> })
  | (ChatWsFrameBase & { type: 'thread_id'; data: ThreadIdEventData })
  | (ChatWsFrameBase & { type: 'model_input'; data: ModelInputEventData })
  | (ChatWsFrameBase & { type: 'model_output'; data: ModelOutputEventData })
  | (ChatWsFrameBase & { type: 'interrupt'; data: InterruptEventData })
  | (ChatWsFrameBase & { type: 'command'; data: CommandEventData })
  | (ChatWsFrameBase & { type: 'route_decision'; data: RouteDecisionEventData })
  | (ChatWsFrameBase & { type: 'loop_iteration'; data: LoopIterationEventData })
  | (ChatWsFrameBase & { type: 'parallel_task'; data: ParallelTaskEventData })
  | (ChatWsFrameBase & { type: 'state_update'; data: StateUpdateEventData })
  | (ChatWsFrameBase & { type: 'code_agent_thought'; data: CodeAgentThoughtEventData })
  | (ChatWsFrameBase & { type: 'code_agent_code'; data: CodeAgentCodeEventData })
  | (ChatWsFrameBase & { type: 'code_agent_observation'; data: CodeAgentObservationEventData })
  | (ChatWsFrameBase & { type: 'code_agent_final_answer'; data: CodeAgentFinalAnswerEventData })
  | (ChatWsFrameBase & { type: 'code_agent_planning'; data: CodeAgentPlanningEventData })
  | (ChatWsFrameBase & { type: 'code_agent_error'; data: CodeAgentErrorEventData })
  | (ChatWsFrameBase & { type: 'file_event'; data: FileEventData })

/**
 * Unified streaming event type (using standardized envelope structure)
 */
export type ChatStreamEvent = ChatWsFrame
