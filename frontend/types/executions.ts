export interface Execution {
  id: string
  workspace_id: string
  user_id: string
  source: ExecutionSource
  status: ExecutionStatus
  title?: string | null
  task_id?: string | null
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

export type ExecutionStatus =
  | 'pending'
  | 'dispatched'
  | 'running'
  | 'approval_wait'
  | 'succeeded'
  | 'failed'
  | 'cancelled'
export type ExecutionSource = 'mission' | 'chat' | 'graph' | 'coordinator' | 'api'

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
  pending: 'runs.statusPending',
  dispatched: 'runs.statusDispatched',
  running: 'runs.statusRunning',
  approval_wait: 'runs.statusApprovalWait',
  succeeded: 'runs.statusSucceeded',
  failed: 'runs.statusFailed',
  cancelled: 'runs.statusCancelled',
}

export interface ExecutionEvent {
  id: string
  execution_id: string
  seq: number
  event_type: ExecutionEventType
  payload: Record<string, unknown>
  created_at: string
}

export type ExecutionEventType =
  | 'text'
  | 'assistant_text'
  | 'thinking'
  | 'tool_use'
  | 'tool_use_start'
  | 'tool_result'
  | 'tool_use_end'
  | 'error'
  | 'artifact'
  | 'artifact_created'
  | 'approval_request'
  | 'approval_requested'
  | 'approval_resolved'
  | 'user_message'
  | 'status'
  | 'execution_started'
  | 'execution_completed'

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

export interface ExecutionEventsPage {
  execution_id: string
  events: ExecutionEvent[]
  next_after_seq: number
}
