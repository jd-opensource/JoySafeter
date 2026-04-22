export interface AgentRun {
  id: string
  release_id: string
  workspace_id: string
  thread_id: string | null
  task_id: string | null
  trigger_source: 'task' | 'chat' | 'api' | 'scheduler'
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

export type AgentRunStatus =
  | 'queued'
  | 'running'
  | 'completed'
  | 'failed'
  | 'cancelled'

export const ACTIVE_RUN_STATUSES: readonly AgentRunStatus[] = [
  'queued',
  'running',
] as const

export const TERMINAL_RUN_STATUSES: readonly AgentRunStatus[] = [
  'completed',
  'failed',
  'cancelled',
] as const

export const RUN_STATUS_STYLES: Record<AgentRunStatus, string> = {
  queued: 'border-[var(--border)] bg-[var(--surface-2)] text-[var(--text-secondary)]',
  running:
    'border-[var(--skill-brand-200)] bg-[var(--skill-brand-50)] text-[var(--skill-brand-700)]',
  completed:
    'border-[var(--status-success-bg)] bg-[var(--status-success-bg)] text-[var(--status-success)]',
  failed: 'border-[var(--status-error)] bg-[var(--surface-2)] text-[var(--status-error)]',
  cancelled: 'border-[var(--border)] bg-[var(--surface-2)] text-[var(--text-muted)]',
}

export const RUN_STATUS_I18N: Record<AgentRunStatus, string> = {
  queued: 'runs.statusQueued',
  running: 'runs.statusRunning',
  completed: 'runs.statusCompleted',
  failed: 'runs.statusFailed',
  cancelled: 'runs.statusCancelled',
}

export interface CreateAgentRunRequest {
  release_id: string
  thread_id?: string
  task_id?: string
  trigger_source: 'task' | 'chat' | 'api' | 'scheduler'
  goal?: string
  input_payload?: Record<string, unknown>
}

export interface Execution {
  id: string
  run_id: string
  parent_execution_id: string | null
  attempt_index: number
  executor_kind: string
  runtime_session_ref: string | null
  status: ExecutionStatus
  error_code: string | null
  error_message: string | null
  metrics: Record<string, unknown> | null
  started_at: string | null
  ended_at: string | null
  created_at: string
}

export type ExecutionStatus =
  | 'pending'
  | 'running'
  | 'completed'
  | 'failed'
  | 'cancelled'

export const ACTIVE_EXECUTION_STATUSES: readonly ExecutionStatus[] = [
  'pending',
  'running',
] as const

export const TERMINAL_EXECUTION_STATUSES: readonly ExecutionStatus[] = [
  'completed',
  'failed',
  'cancelled',
] as const

export interface ExecutionEvent {
  id: string
  execution_id: string
  sequence_no: number
  event_type: string
  payload: Record<string, unknown>
  created_at: string
}
