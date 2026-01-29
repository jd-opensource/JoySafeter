export interface Position {
  x: number
  y: number
}

export interface Viewport {
  x: number
  y: number
  zoom: number
}

export enum NodeType {
  USER = 'USER',
  AI = 'AI',
}

// LangGraph / OpenAI compatible message structure
export interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: number
  tool_calls?: ToolCall[]
  isStreaming?: boolean
  metadata?: {
    lastNode?: string
    lastRunId?: string
    lastUpdate?: number
    [key: string]: any
  }
}

export interface ToolCall {
  id: string
  name: string
  args: Record<string, any>
  status: 'running' | 'completed' | 'failed'
  result?: any
  startTime: number
  endTime?: number
}

// Legacy CanvasNode for Builder (keeping for compatibility with Builder)
export interface CanvasNode {
  id: string
  parentId: string | null
  type: NodeType
  content: string
  position: Position
  width: number
  isStreaming?: boolean
  createdAt: number
  toolCalls?: ToolCall[]
  data?: any
}

export interface Edge {
  id: string
  source: string
  target: string
}

export interface ChatMessage {
  role: 'user' | 'model'
  parts: { text: string }[]
}

export type ViewMode = 'chat' | 'builder'
