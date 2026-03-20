/**
 * useCopilotWebSocketHandler - WebSocket event handler hook for Copilot
 *
 * Architecture: Backend is the single writer for graph state. On "result" we only
 * do optimistic render (applyAIChanges, no save). On "done" we invalidate caches
 * and clear session. Message queue in use-copilot-websocket ensures onResult
 * completes before onDone runs.
 */

import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef } from 'react'

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
  const stateRef = useRef(state)
  useEffect(() => {
    stateRef.current = state
  }, [state])

  const callbacks = useMemo(
    () => ({
      onConnect: () => {
        if (!refs.isMountedRef.current) return
        const s = stateRef.current
        if (s.loading && !s.currentStage && !s.streamingContent) {
          actions.setCurrentStage({ stage: 'thinking', message: '已连接，正在处理...' })
        }
      },

      onDisconnect: () => {},

      onStatus: (stage: string, message: string) => {
        if (!refs.isMountedRef.current) return
        actions.setCurrentStage({ stage: stage as StageType, message })
        if (!hasCurrentMessage(stateRef.current.messages, true)) {
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

      onToolResult: (action: {
        type: string
        payload: Record<string, unknown>
        reasoning?: string
      }) => {
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
          }
        } catch (error) {
          console.error('[CopilotHandler] Error in onResult:', error)
        }
      },

      onError: (error: string) => {
        if (!refs.isMountedRef.current) return
        try {
          actions.clearStreaming()
          let errorMessage = error
          if (error.includes('Credential') || error.includes('API key')) {
            errorMessage = t('workspace.copilot.error.credential', {
              defaultValue: 'Authentication error. Please check API credentials.',
            })
          } else if (error.includes('Connection') || error.includes('WebSocket')) {
            errorMessage = t('workspace.copilot.error.connection', {
              defaultValue: 'Connection error. Please check your network.',
            })
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

      onDone: async () => {
        if (!refs.isMountedRef.current) return
        refs.isCreatingSessionRef.current = false
        if (graphId) {
          // Invalidate to allow AgentBuilder/useGraphState to refetch authoritative backend state
          queryClient.invalidateQueries({ queryKey: graphKeys.state(graphId) })
          queryClient.invalidateQueries({ queryKey: graphKeys.copilotHistory(graphId) })
        }
        actions.clearStreaming()
        actions.clearSession()
        actions.setLoading(false)
      },
    }),
    [actions, refs, graphId, queryClient, t],
  )

  return callbacks
}
