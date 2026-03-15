/**
 * useCopilotWebSocketHandler - WebSocket event handler hook for Copilot
 *
 * Encapsulates all WebSocket event handling logic with proper mount checks
 * and error handling.
 */

import { useQueryClient } from '@tanstack/react-query'
import { useMemo } from 'react'

import type { StageType } from '@/hooks/copilot/useCopilotStreaming'
import { graphKeys } from '@/hooks/queries/graphs'
import { useTranslation } from '@/lib/i18n'
import type { GraphAction } from '@/types/copilot'

import type { CopilotState, CopilotActions, CopilotRefs } from './useCopilotState'
import { hasCurrentMessage } from '../utils/copilotUtils'

interface UseCopilotWebSocketHandlerOptions {
  state: CopilotState
  actions: CopilotActions
  refs: CopilotRefs
  graphId?: string
}

export function useCopilotWebSocketHandler({
  state,
  actions,
  refs,
  graphId,
}: UseCopilotWebSocketHandlerOptions) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()

  // Memoize callbacks to prevent unnecessary re-renders
  // Using refs to access latest values without adding to dependencies
  const callbacks = useMemo(() => ({
    onConnect: () => {
      if (!refs.isMountedRef.current) return
      // Only set thinking status if we are loading and have no stage/content yet
      if (state.loading && !state.currentStage && !state.streamingContent) {
        actions.setCurrentStage({ stage: 'thinking', message: '已连接，正在处理...' })
      }
    },

    onDisconnect: () => {
      // WebSocket disconnected - no action needed as cleanup handles this
    },

    onStatus: (stage: string, message: string) => {
      if (!refs.isMountedRef.current) return
      actions.setCurrentStage({ stage: stage as StageType, message })

      // Create message placeholder on first status event
      if (!hasCurrentMessage(state.messages, true)) {
        actions.setThinkingMessage()
      }
    },

    onContent: (content: string) => {
      if (!refs.isMountedRef.current) return
      actions.appendContent(content)
    },

    onThoughtStep: (step: { index: number; content: string }) => {
      if (!refs.isMountedRef.current) return
      actions.addThoughtStep(step)
    },

    onToolCall: (tool: string, input: Record<string, unknown>) => {
      if (!refs.isMountedRef.current) return
      actions.setCurrentToolCall({ tool, input })
    },

    onToolResult: (action: { type: string; payload: Record<string, unknown>; reasoning?: string }) => {
      if (!refs.isMountedRef.current) return
      actions.addToolResult(action)
    },

    onResult: async (response: { message: string; actions?: GraphAction[] }) => {
      if (!refs.isMountedRef.current) return

      try {
        actions.clearStreaming()
        const normalizedMessage = response.message.replace(/\n{2,}/g, '\n')
        actions.finalizeCurrentMessage(normalizedMessage, response.actions)

        if (response.actions && response.actions.length > 0) {
          await actions.executeActions(response.actions)
          if (!refs.isMountedRef.current) return
        }

        // Backend is source of truth: refetch graph state and history to sync with persisted state
        if (graphId && refs.isMountedRef.current) {
          queryClient.invalidateQueries({ queryKey: graphKeys.state(graphId) })
          queryClient.invalidateQueries({ queryKey: graphKeys.copilotHistory(graphId) })
        }
      } catch (error) {
        console.error('[CopilotHandler] Error in onResult:', error)
      } finally {
        if (refs.isMountedRef.current) {
          refs.isCreatingSessionRef.current = false
          actions.clearSession()
          actions.setLoading(false)
        }
      }
    },

    onError: (error: string) => {
      if (!refs.isMountedRef.current) return

      try {
        actions.clearStreaming()

        let errorMessage = error
        if (error.includes('Credential') || error.includes('API key')) {
          errorMessage = t('workspace.copilot.error.credential', { defaultValue: 'Authentication error. Please check API credentials.' })
        } else if (error.includes('Connection') || error.includes('WebSocket')) {
          errorMessage = t('workspace.copilot.error.connection', { defaultValue: 'Connection error. Please check your network.' })
        } else {
          errorMessage = `${t('workspace.systemError')}: ${error}`
        }

        actions.finalizeCurrentMessage(errorMessage)
      } finally {
        if (refs.isMountedRef.current) {
          refs.isCreatingSessionRef.current = false
          actions.clearSession()
          actions.setLoading(false)
        }
      }
    },

    onDone: () => {
      if (!refs.isMountedRef.current) return
      refs.isCreatingSessionRef.current = false
      actions.clearStreaming()
      actions.clearSession()
      actions.setLoading(false)
    },
  }), [
    // Dependencies - using state and actions from props
    state.loading,
    state.currentStage,
    state.messages,
    actions,
    refs,
    graphId,
    queryClient,
    t,
  ])

  return callbacks
}
