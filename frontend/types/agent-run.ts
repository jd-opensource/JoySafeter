export const TRIGGER_SOURCES = [
  'task',
  'chat',
  'api',
  'scheduler',
  'draft_test',
  'draft_copilot',
  'debug',
  'copilot',
] as const

export type TriggerSource = (typeof TRIGGER_SOURCES)[number]

export interface AgentRun {
  id: string
  release_id: string
  workspace_id: string
  thread_id: string | null
  task_id: string | null
  trigger_source: TriggerSource
  goal: string | null
  input_payload: Record<string, unknown> | null
  status: AgentRunStatus
  current_execution_id: string | null
  result_summary: string | null
  started_at: string | null
  ended_at: string | null
  created_by: string | null
  created_at: string
}

export const RUN_STATUSES = [
  'pending',
  'running',
  'succeeded',
  'failed',
  'cancelled',
] as const

export type AgentRunStatus = (typeof RUN_STATUSES)[number]

export const ACTIVE_RUN_STATUSES: readonly AgentRunStatus[] = [
  'pending',
  'running',
] as const

export const TERMINAL_RUN_STATUSES: readonly AgentRunStatus[] = [
  'succeeded',
  'failed',
  'cancelled',
] as const

export const RUN_STATUS_STYLES: Record<AgentRunStatus, string> = {
  pending: 'border-[var(--border)] bg-[var(--surface-2)] text-[var(--text-secondary)]',
  running:
    'border-[var(--skill-brand-200)] bg-[var(--skill-brand-50)] text-[var(--skill-brand-700)]',
  succeeded:
    'border-[var(--status-success-bg)] bg-[var(--status-success-bg)] text-[var(--status-success)]',
  failed: 'border-[var(--status-error)] bg-[var(--surface-2)] text-[var(--status-error)]',
  cancelled: 'border-[var(--border)] bg-[var(--surface-2)] text-[var(--text-muted)]',
}

export const RUN_STATUS_I18N: Record<AgentRunStatus, string> = {
  pending: 'execution.statusPending',
  running: 'execution.statusRunning',
  succeeded: 'execution.statusSucceeded',
  failed: 'execution.statusFailed',
  cancelled: 'execution.statusCancelled',
}

export interface CreateAgentRunRequest {
  release_id: string
  thread_id?: string
  task_id?: string
  trigger_source: TriggerSource
  goal?: string
  input_payload?: Record<string, unknown>
}

export const EXECUTION_STATUSES = [
  'pending',
  'dispatched',
  'running',
  'approval_wait',
  'succeeded',
  'failed',
  'cancelled',
] as const

export type ExecutionStatus = (typeof EXECUTION_STATUSES)[number]

export const ACTIVE_EXECUTION_STATUSES: readonly ExecutionStatus[] = [
  'pending',
  'dispatched',
  'running',
  'approval_wait',
] as const

export const TERMINAL_EXECUTION_STATUSES: readonly ExecutionStatus[] = [
  'succeeded',
  'failed',
  'cancelled',
] as const

export const EXECUTION_STATUS_STYLES: Record<ExecutionStatus, string> = {
  pending: 'border-[var(--border)] bg-[var(--surface-2)] text-[var(--text-secondary)]',
  dispatched: 'border-[var(--brand-200)] bg-[var(--brand-50)] text-[var(--brand-700)]',
  running:
    'border-[var(--skill-brand-200)] bg-[var(--skill-brand-50)] text-[var(--skill-brand-700)]',
  approval_wait:
    'border-[var(--status-warning-bg)] bg-[var(--status-warning-bg)] text-[var(--status-warning)]',
  succeeded:
    'border-[var(--status-success-bg)] bg-[var(--status-success-bg)] text-[var(--status-success)]',
  failed: 'border-[var(--status-error)] bg-[var(--surface-2)] text-[var(--status-error)]',
  cancelled: 'border-[var(--border)] bg-[var(--surface-2)] text-[var(--text-muted)]',
}

export const EXECUTION_STATUS_I18N: Record<ExecutionStatus, string> = {
  pending: 'execution.statusPending',
  dispatched: 'execution.statusDispatched',
  running: 'execution.statusRunning',
  approval_wait: 'execution.statusApprovalWait',
  succeeded: 'execution.statusSucceeded',
  failed: 'execution.statusFailed',
  cancelled: 'execution.statusCancelled',
}

export type ExecutionEventType =
  | 'assistant_text'
  | 'thinking'
  | 'tool_use_start'
  | 'tool_use_end'
  | 'error'
  | 'artifact_created'
  | 'approval_requested'
  | 'approval_resolved'
  | 'user_message'
  | 'execution_started'
  | 'execution_completed'
  | 'execution_status_change'
  | 'copilot_status'
  | 'copilot_content'
  | 'copilot_thought_step'
  | 'copilot_tool_call'
  | 'copilot_tool_result'
  | 'copilot_result'

export interface Execution {
  id: string
  run_id: string
  parent_execution_id: string | null
  attempt_index: number
  executor_kind: string
  runtime_session_ref: string | null
  status: ExecutionStatus
  error: AppErrorPayload | null
  metrics: Record<string, unknown> | null
  started_at: string | null
  ended_at: string | null
  created_at: string
}

export type ErrorSource =
  | 'api'
  | 'engine'
  | 'runtime'
  | 'node'
  | 'tool'
  | 'websocket'
  | 'auth'
  | 'validation'
  | 'permission'
  | 'internal'

export type UserAction = 'retry' | 'configure_model' | 'relogin' | 'fix_input' | 'contact_support'

export interface AppErrorPayload {
  code: string
  message: string
  data: Record<string, unknown> | null
  source?: ErrorSource
  retryable?: boolean
  user_action?: UserAction
  detail?: string
}

export interface ExecutionEvent {
  id: string
  execution_id: string
  seq: number
  event_type: ExecutionEventType
  payload: Record<string, unknown>
  created_at: string
}

export interface ExecutionEventsPage {
  execution_id: string
  events: ExecutionEvent[]
  next_after_seq: number
}

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
