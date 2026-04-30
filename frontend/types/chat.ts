export interface Message {
  id: string
  role: 'user' | 'assistant' | 'system' | 'tool'
  content: string
  tool_calls?: ToolCall[]
  created_at?: string
  timestamp?: number
  isStreaming?: boolean
}

export interface ToolCall {
  id: string
  name: string
  args?: Record<string, unknown>
  input?: Record<string, unknown>
  output?: string
  result?: unknown
  status?: 'running' | 'completed' | 'failed'
  startTime?: number
  endTime?: number
}
