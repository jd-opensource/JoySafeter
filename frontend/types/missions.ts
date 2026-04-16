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
  due_date?: string | null
  created_at: string
  updated_at: string
}

export type MissionStatus = 'backlog' | 'todo' | 'in_progress' | 'in_review' | 'done' | 'blocked' | 'cancelled'
export type MissionPriority = 'none' | 'low' | 'medium' | 'high' | 'urgent'

export interface CreateMissionRequest {
  workspace_id: string
  title: string
  description?: string
  objective?: string
  priority?: MissionPriority
  parent_mission_id?: string
  tags?: string[]
}

export interface UpdateMissionRequest {
  title?: string
  description?: string
  objective?: string
  status?: MissionStatus
  priority?: MissionPriority
  position?: number
  tags?: string[]
}

export interface AssignMissionRequest {
  agent_profile_id: string
}

export const MISSION_STATUS_ORDER: MissionStatus[] = [
  'backlog', 'todo', 'in_progress', 'in_review', 'done', 'blocked', 'cancelled',
]

export const MISSION_STATUS_LABELS: Record<MissionStatus, string> = {
  backlog: 'Backlog',
  todo: 'To Do',
  in_progress: 'In Progress',
  in_review: 'In Review',
  done: 'Done',
  blocked: 'Blocked',
  cancelled: 'Cancelled',
}

export const MISSION_PRIORITY_LABELS: Record<MissionPriority, string> = {
  none: 'None',
  low: 'Low',
  medium: 'Medium',
  high: 'High',
  urgent: 'Urgent',
}
