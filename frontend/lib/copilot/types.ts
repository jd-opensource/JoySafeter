/**
 * Copilot Tool Call Types
 */

export type ToolCallStateType = 'detecting' | 'executing' | 'completed' | 'error' | 'aborted'

export interface ToolCallState {
  id: string
  name: string
  displayName?: string
  state: ToolCallStateType
  parameters?: Record<string, any>
  progress?: string
  duration?: number
  error?: string
}

export interface ToolCallGroup {
  toolCalls: ToolCallState[]
  summary?: string
}
