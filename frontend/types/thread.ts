export interface Thread {
  id: string
  agent_id: string
  workspace_id: string
  title: string | null
  status: 'active' | 'archived'
  created_by: string
  created_at: string
  updated_at: string
}

export interface ThreadMessage {
  id: string
  thread_id: string
  run_id: string | null
  execution_id: string | null
  role: 'user' | 'assistant' | 'system' | 'tool'
  content: Record<string, unknown>
  created_at: string
}

export interface ThreadDetail extends Thread {
  messages: ThreadMessage[]
}

export interface CreateThreadRequest {
  agent_id: string
  title?: string
}

export interface UpdateThreadRequest {
  title?: string
  status?: 'active' | 'archived'
}

export interface CreateMessageRequest {
  role: 'user' | 'assistant' | 'system' | 'tool'
  content: Record<string, unknown>
}

export interface ChatResponse {
  run_id: string
  execution_id: string
}
