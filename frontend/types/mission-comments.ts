export type CommentAuthorType = 'member' | 'agent'
export type CommentType = 'comment' | 'status_change' | 'progress_update' | 'system'

export interface MissionComment {
  id: string
  task_id: string
  workspace_id: string
  author_type: CommentAuthorType
  author_id: string
  content: string
  type: CommentType
  parent_comment_id: string | null
  created_at: string
  updated_at: string
}

export interface CreateMissionCommentRequest {
  content: string
  parent_comment_id?: string
}

export interface MissionCommentListResponse {
  items: MissionComment[]
  has_more: boolean
  next_cursor: string | null
}
