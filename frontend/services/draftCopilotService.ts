'use client'

/**
 * Draft Copilot Service
 *
 * Encapsulates Build-stage draft copilot helpers.
 */

import type {
  GraphAction,
  CopilotResponse,
  ConversationMessage,
  StreamGraphActionsCallbacks,
} from '@/types/copilot'
import { apiPost } from '@/lib/api-client'

export type { GraphAction, CopilotResponse, ConversationMessage, StreamGraphActionsCallbacks }

function convertConversationHistory(
  history: Array<{ role: 'user' | 'model'; text: string; actions?: GraphAction[] }>,
): Array<ConversationMessage> {
  const ERROR_KEYWORDS = ['request cancelled', 'systemError', 'error', 'cancelled']

  return history
    .filter((msg) => {
      const isError = ERROR_KEYWORDS.some((keyword) =>
        msg.text.toLowerCase().includes(keyword.toLowerCase()),
      )
      if (isError) return false

      return msg.text && msg.text.trim().length > 0
    })
    .map((msg) => {
      const result: ConversationMessage = {
        role: msg.role === 'user' ? 'user' : 'assistant',
        content: msg.text,
      }
      if (msg.role === 'model' && msg.actions && msg.actions.length > 0) {
        result.actions = msg.actions
      }
      return result
    })
}

export const draftCopilotService = {
  convertConversationHistory,

  async dispatchRun(params: {
    agentId: string
    versionId: string
    projectId: string
    prompt: string
    graphContext: Record<string, unknown>
    conversationHistory: Array<{ role: 'user' | 'model'; text: string; actions?: GraphAction[] }>
    mode?: string
    providerName?: string
    modelName?: string
  }): Promise<{ run_id: string; execution_id: string }> {
    return apiPost<{ run_id: string; execution_id: string }>('copilot/run', {
      agent_id: params.agentId,
      version_id: params.versionId,
      project_id: params.projectId,
      prompt: params.prompt,
      graph_context: params.graphContext,
      conversation_history: convertConversationHistory(params.conversationHistory),
      mode: params.mode || 'deepagents',
      provider_name: params.providerName,
      model_name: params.modelName,
    })
  },
}
