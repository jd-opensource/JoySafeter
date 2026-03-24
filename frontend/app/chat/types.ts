/** Generate a short random ID for messages and temporary entities */
export const generateId = () => Math.random().toString(36).substring(2, 11)

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

// ─── Typed metadata for streaming events ─────────────────────────────────────

export interface FileTreeEntry {
  action: string
  size?: number
  timestamp?: number
}

export interface NodeLogEntry {
  type: string // common values: 'command' | 'route_decision' | 'loop_iteration' | 'parallel_task' | 'state_update' | 'node_transition'
  nodeName: string
  timestamp: number
  data?: Record<string, unknown>
}

export interface MessageMetadata {
  fileTree?: Record<string, FileTreeEntry>
  nodeExecutionLog?: NodeLogEntry[]
  currentNode?: string
  lastNode?: string
  lastRunId?: string
  lastUpdate?: number
  lastRouteDecision?: any
  lastLoopIteration?: any
  [key: string]: any // keep backwards compat
}

export interface InterruptState {
  nodeName: string
  nodeLabel?: string
  state?: Record<string, unknown>
  threadId: string
}

// LangGraph / OpenAI compatible message structure
export interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: number
  tool_calls?: ToolCall[]
  isStreaming?: boolean
  metadata?: MessageMetadata
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
