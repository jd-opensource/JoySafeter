'use client'

/**
 * Copilot Service
 *
 * Encapsulates Copilot-related helpers, including:
 * - Convert conversation history format
 */

import type {
  GraphAction,
  CopilotResponse,
  ConversationMessage,
  StreamGraphActionsCallbacks,
} from '@/types/copilot'
import { apiPost } from '@/lib/api-client'

// Re-export types
export type { GraphAction, CopilotResponse, ConversationMessage, StreamGraphActionsCallbacks }

// ==================== Helper Functions ====================

/**
 * Convert frontend conversation history to API format.
 * Filters out error messages and empty content.
 * Includes actions for context in multi-turn conversations.
 */
function convertConversationHistory(
  history: Array<{ role: 'user' | 'model'; text: string; actions?: GraphAction[] }>,
): Array<ConversationMessage> {
  const ERROR_KEYWORDS = ['request cancelled', 'systemError', 'error', 'cancelled']

  return history
    .filter((msg) => {
      // Skip error/cancelled messages
      const isError = ERROR_KEYWORDS.some((keyword) =>
        msg.text.toLowerCase().includes(keyword.toLowerCase()),
      )
      if (isError) return false

      // Only include messages with actual content
      return msg.text && msg.text.trim().length > 0
    })
    .map((msg) => {
      const result: ConversationMessage = {
        role: msg.role === 'user' ? 'user' : 'assistant',
        content: msg.text,
      }
      // Include actions if present (for assistant messages)
      if (msg.role === 'model' && msg.actions && msg.actions.length > 0) {
        result.actions = msg.actions
      }
      return result
    })
}

// ==================== Service ====================

export const copilotService = {
  /**
   * Convert conversation history format (helper method)
   */
  convertConversationHistory,

  /**
   * Dispatch copilot through execution engine for persistent history.
   * Returns { run_id, execution_id } — subscribe to execution WS for events.
   */
  async dispatchRun(params: {
    agentId: string
    prompt: string
    graphContext: Record<string, unknown>
    conversationHistory: Array<{ role: 'user' | 'model'; text: string; actions?: GraphAction[] }>
    mode?: string
    providerName?: string
    modelName?: string
  }): Promise<{ run_id: string; execution_id: string }> {
    return apiPost<{ run_id: string; execution_id: string }>('copilot/run', {
      agent_id: params.agentId,
      prompt: params.prompt,
      graph_context: params.graphContext,
      conversation_history: convertConversationHistory(params.conversationHistory),
      mode: params.mode || 'deepagents',
      provider_name: params.providerName,
      model_name: params.modelName,
    })
  },
}
