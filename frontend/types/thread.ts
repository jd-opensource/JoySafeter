export interface Thread {
  id: string
  agent_id: string
  project_id?: string
  title: string | null
  status: 'active' | 'archived'
  created_by: string
  created_at: string
  updated_at: string
}

export interface ChatAttachment {
  filename: string
  storage_ref: string
  mime_type: string
  size_bytes: number
}

export interface ThreadEvent {
  id: string
  run_id: string
  execution_id: string
  sequence_no: number
  event_type: string
  payload: Record<string, unknown>
  execution_status: string
  created_at: string
}

export interface CreateThreadRequest {
  agent_id: string
  title?: string
}

export interface UpdateThreadRequest {
  title?: string
  status?: 'active' | 'archived'
}

export interface ChatResponse {
  run_id: string
  execution_id: string
}
