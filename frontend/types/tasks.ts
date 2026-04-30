export interface Task {
  id: string
  workspace_id: string
  title: string
  description?: string | null
  goal?: string | null
  status: TaskStatus
  priority: TaskPriority
  /** Backend primary field for assigned agent */
  agent_id?: string | null
  /** Legacy alias kept for backward compatibility */
  assignee_type?: 'member' | 'agent' | null
  /** Legacy alias kept for backward compatibility; prefer agent_id */
  assignee_id?: string | null
  creator_id: string
  /** ID of the most recent AgentRun for this task */
  latest_run_id?: string | null
  /** ID of the current Execution for this task's active AgentRun */
  current_execution_id?: string | null
  parent_task_id?: string | null
  tags?: string[] | null
  position: number
  auto_approve: boolean
  due_date?: string | null
  created_at: string
  updated_at: string
}

export type TaskStatus = 'backlog' | 'todo' | 'in_progress' | 'in_review' | 'done' | 'cancelled'
export type TaskPriority = 'none' | 'low' | 'medium' | 'high' | 'urgent'

export interface CreateTaskRequest {
  workspace_id: string
  title: string
  description?: string
  goal?: string
  priority?: TaskPriority
  parent_task_id?: string
  tags?: string[]
  auto_approve?: boolean
}

export interface UpdateTaskRequest {
  title?: string
  description?: string
  goal?: string
  status?: TaskStatus
  priority?: TaskPriority
  position?: number
  tags?: string[]
  due_date?: string | null
  assignee_type?: string | null
  assignee_id?: string | null
  auto_approve?: boolean
}

export interface AssignTaskRequest {
  agent_id: string
}

export const TASK_STATUS_ORDER: TaskStatus[] = [
  'backlog',
  'todo',
  'in_progress',
  'in_review',
  'done',
  'cancelled',
]

/** Statuses treated as "inactive" in UI (hide dispatch button, etc.).
 *  Note: Backend allows reopening these via backlog transition — they are NOT truly terminal. */
export const INACTIVE_TASK_STATUSES: readonly TaskStatus[] = ['done', 'cancelled'] as const

/** @deprecated Use INACTIVE_TASK_STATUSES — done/cancelled can be reopened via backlog */
export const TERMINAL_TASK_STATUSES = INACTIVE_TASK_STATUSES

export const TASK_STATUS_LABELS: Record<TaskStatus, string> = {
  backlog: '待处理',
  todo: '待执行',
  in_progress: '进行中',
  in_review: '需检查',
  done: '已完成',
  cancelled: '已取消',
}

export const TASK_PRIORITY_LABELS: Record<TaskPriority, string> = {
  none: '无',
  low: '低',
  medium: '中',
  high: '高',
  urgent: '紧急',
}

export const TASK_STATUS_STYLES: Record<string, string> = {
  backlog: 'bg-[var(--surface-3)] text-[var(--text-secondary)]',
  todo: 'bg-[var(--surface-3)] text-[var(--brand-400)]',
  in_progress: 'bg-[var(--status-warning-bg)] text-[var(--status-warning)]',
  in_review: 'bg-[var(--surface-3)] text-[var(--text-secondary)]',
  done: 'bg-[var(--status-success-bg)] text-[var(--status-success)]',
  cancelled: 'bg-[var(--surface-3)] text-[var(--text-muted)]',
}

/** Fallback transitions — used before API response arrives.
 *  Must mirror backend TASK_STATES in core/state_machines/definitions.py */
export const DEFAULT_MANUAL_TRANSITIONS: Record<TaskStatus, readonly TaskStatus[]> = {
  backlog: ['todo', 'in_progress', 'cancelled'],
  todo: ['in_progress', 'backlog', 'cancelled'],
  in_progress: ['done', 'in_review', 'cancelled', 'backlog'],
  in_review: ['in_progress', 'done', 'backlog', 'cancelled'],
  done: ['backlog'],
  cancelled: ['backlog'],
}
