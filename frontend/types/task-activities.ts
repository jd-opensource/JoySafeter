export type ActivityAuthorType = 'member' | 'agent'
export type ActivityType = 'comment' | 'status_change' | 'progress_update' | 'system'

export interface TaskActivity {
  id: string
  task_id: string
  project_id?: string
  author_type: ActivityAuthorType
  author_id: string
  content: string
  type: ActivityType
  parent_activity_id: string | null
  created_at: string
  updated_at: string
}

export interface CreateTaskActivityRequest {
  content: string
  parent_activity_id?: string
}

export interface TaskActivityListResponse {
  items: TaskActivity[]
  has_more: boolean
  next_cursor: string | null
}
