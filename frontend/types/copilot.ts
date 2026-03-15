/**
 * Copilot Type Definitions (domain / API contract)
 *
 * This file holds types aligned with the backend and stream event contract.
 * Canonical source: backend app/core/copilot/action_types.py
 * Exported JSON Schema: docs/schemas/copilot-contract.json
 *
 * UI presentation types are defined inline where used (e.g. in CopilotStreaming).
 */

export type GraphActionType =
  | 'CREATE_NODE'
  | 'CONNECT_NODES'
  | 'DELETE_NODE'
  | 'UPDATE_CONFIG'
  | 'UPDATE_POSITION'

export interface GraphAction {
  type: GraphActionType
  payload: {
    id?: string
    type?: string
    label?: string
    position?: { x: number; y: number }
    config?: Record<string, unknown>
    source?: string
    target?: string
  }
  reasoning: string
}

export interface CopilotResponse {
  message: string
  actions: GraphAction[]
}

export interface ConversationMessage {
  role: 'user' | 'assistant'
  content: string
  actions?: GraphAction[] // Include actions for context
}

/**
 * Callbacks for Copilot real-time events.
 * Used by WebSocket implementation for standard Copilot,
 * and compatible with SSE events for DeepAgents.
 */
export interface StreamGraphActionsCallbacks {
  onStatus: (stage: string, message: string) => void
  onResult: (response: CopilotResponse) => void
  onError: (error: string) => void
  onThoughtStep: (step: { index: number; content: string }) => void
  onContent: (content: string) => void
  onToolCall: (tool: string, input: Record<string, unknown>) => void
  onToolResult: (action: { type: string; payload: Record<string, unknown>; reasoning?: string }) => void
}
