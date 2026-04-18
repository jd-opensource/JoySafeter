export interface Execution {
  id: string
  workspace_id: string
  user_id: string
  source: ExecutionSource
  status: ExecutionStatus
  title?: string | null
  mission_id?: string | null
  agent_profile_id?: string | null
  parent_execution_id?: string | null
  runtime_type: string
  container_id?: string | null
  started_at?: string | null
  finished_at?: string | null
  last_seq: number
  session_id?: string | null
  result_summary?: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export type ExecutionStatus = 'queued' | 'dispatched' | 'running' | 'interrupt_wait' | 'approval_wait' | 'completed' | 'failed' | 'cancelled'
export type ExecutionSource = 'mission' | 'chat' | 'graph' | 'coordinator' | 'api'

export const ACTIVE_EXECUTION_STATUSES: readonly ExecutionStatus[] = ['queued', 'dispatched', 'running', 'approval_wait'] as const
export const TERMINAL_EXECUTION_STATUSES: readonly ExecutionStatus[] = ['completed', 'failed', 'cancelled'] as const

export interface ExecutionEvent {
  id: string
  execution_id: string
  seq: number
  event_type: ExecutionEventType
  payload: Record<string, unknown>
  created_at: string
}

export type ExecutionEventType =
  | 'text' | 'assistant_text'
  | 'thinking'
  | 'tool_use' | 'tool_use_start'
  | 'tool_result' | 'tool_use_end'
  | 'error'
  | 'artifact' | 'artifact_created'
  | 'approval_request' | 'approval_requested' | 'approval_resolved'
  | 'user_message'
  | 'status'
  | 'execution_started' | 'execution_completed'

export interface ExecutionSnapshot {
  execution_id: string
  last_seq: number
  status: string
  projection: {
    last_text?: string
    tool_count?: number
    current_tool?: string | null
    artifacts?: Record<string, unknown>[]
    approval_pending?: Record<string, unknown> | null
    error?: string | null
  }
}
