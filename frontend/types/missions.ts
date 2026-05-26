export interface Mission {
  id: string
  workspace_id: string
  title: string
  description?: string | null
  objective?: string | null
  status: MissionStatus
  priority: MissionPriority
  assignee_type?: 'member' | 'agent' | null
  assignee_id?: string | null
  creator_id: string
  current_execution_id?: string | null
  parent_mission_id?: string | null
  tags?: string[] | null
  position: number
  auto_approve: boolean
  due_date?: string | null
  created_at: string
  updated_at: string
}

export type MissionStatus = 'backlog' | 'todo' | 'in_progress' | 'in_review' | 'done' | 'cancelled'
export type MissionPriority = 'none' | 'low' | 'medium' | 'high' | 'urgent'

export interface CreateMissionRequest {
  workspace_id: string
  title: string
  description?: string
  objective?: string
  priority?: MissionPriority
  parent_mission_id?: string
  tags?: string[]
  auto_approve?: boolean
}

export interface UpdateMissionRequest {
  title?: string
  description?: string
  objective?: string
  status?: MissionStatus
  priority?: MissionPriority
  position?: number
  tags?: string[]
  due_date?: string | null
  assignee_type?: string | null
  assignee_id?: string | null
  auto_approve?: boolean
}

export interface AssignMissionRequest {
  agent_profile_id: string
}

export const MISSION_STATUS_ORDER: MissionStatus[] = [
  'backlog',
  'todo',
  'in_progress',
  'in_review',
  'done',
  'cancelled',
]

export const TERMINAL_MISSION_STATUSES: readonly MissionStatus[] = ['done', 'cancelled'] as const

export const MISSION_STATUS_LABELS: Record<MissionStatus, string> = {
  backlog: 'Backlog',
  todo: 'To Do',
  in_progress: 'In Progress',
  in_review: 'In Review',
  done: 'Done',
  cancelled: 'Cancelled',
}

export const MISSION_PRIORITY_LABELS: Record<MissionPriority, string> = {
  none: 'None',
  low: 'Low',
  medium: 'Medium',
  high: 'High',
  urgent: 'Urgent',
}

export const MISSION_STATUS_STYLES: Record<string, string> = {
  backlog: 'bg-[var(--surface-3)] text-[var(--text-secondary)]',
  todo: 'bg-[var(--surface-3)] text-[var(--brand-400)]',
  in_progress: 'bg-[var(--status-warning-bg)] text-[var(--status-warning)]',
  in_review: 'bg-[var(--surface-3)] text-[var(--text-secondary)]',
  done: 'bg-[var(--status-success-bg)] text-[var(--status-success)]',
  cancelled: 'bg-[var(--surface-3)] text-[var(--text-muted)]',
}

/** Fallback transitions — used before API response arrives. */
export const DEFAULT_MANUAL_TRANSITIONS: Record<MissionStatus, readonly MissionStatus[]> = {
  backlog: ['todo', 'in_progress', 'cancelled'],
  todo: ['backlog', 'in_progress', 'cancelled'],
  in_progress: ['todo', 'in_review', 'done', 'cancelled'],
  in_review: ['todo', 'in_progress', 'done', 'cancelled'],
  done: ['backlog', 'todo'],
  cancelled: ['backlog', 'todo'],
}
