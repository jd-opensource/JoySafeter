'use client'

/**
 * Copilot Service
 *
 * Encapsulates Copilot-related API calls, including:
 * - Clear Copilot history
 * - Convert conversation history format
 */

import { apiDelete } from '@/lib/api-client'
import type {
  GraphAction,
  CopilotResponse,
  ConversationMessage,
  StreamGraphActionsCallbacks,
} from '@/types/copilot'

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
   * Clear Copilot history
   */
  async clearHistory(graphId: string): Promise<boolean> {
    try {
      await apiDelete(`graphs/${graphId}/copilot/history`)
      return true
    } catch (error) {
      console.error('Failed to clear copilot history:', error)
      return false
    }
  },

  /**
   * Convert conversation history format (helper method)
   */
  convertConversationHistory,
}
