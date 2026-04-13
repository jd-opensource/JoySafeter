/**
 * useCopilotWebSocketHandler - WebSocket event handler hook for Copilot
 *
 * Architecture: Backend is the single writer for graph state. On "result" we only
 * do optimistic render (applyAIChanges, no save). On "done" we invalidate caches
 * and clear session. The callback system ensures onResult
 * completes before onDone runs.
 *
 * The handleCopilotEvent bridge receives ChatStreamEvent from the shared chat WS
 * and dispatches to the existing callback system (onStatus, onContent, etc.).
 */

import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useRef } from 'react'

import type { StageType } from '@/hooks/copilot/useCopilotStreaming'
import { graphKeys } from '@/hooks/queries/graphs'
import { useTranslation } from '@/lib/i18n'
import type { ChatStreamEvent } from '@/services/chatBackend'
import type { GraphAction } from '@/types/copilot'

import { hasCurrentMessage } from '../utils/copilotUtils'

import type { CopilotState, CopilotActions, CopilotRefs } from './useCopilotState'

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
          actions.setCurrentStage({ stage: 'thinking', message: 'Connected, processing...' })
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

      onError: (error: string, code?: string) => {
        if (!refs.isMountedRef.current) return
        try {
          actions.clearStreaming()
          let errorMessage = error
          if (code === 'MODEL_NO_CREDENTIALS') {
            errorMessage = t('workspace.copilot.error.credentialNotConfigured', {
              defaultValue: 'No model configured. Please set up your LLM credentials in settings.',
            })
          } else if (code === 'MODEL_NOT_FOUND') {
            errorMessage = t('workspace.copilot.error.modelNotFound', {
              defaultValue: 'Model not found. Please check your model configuration.',
            })
          } else if (code === 'MODEL_NAME_REQUIRED') {
            errorMessage = t('workspace.copilot.error.modelNameRequired', {
              defaultValue: 'No model selected. Please select a model first.',
            })
          } else if (code === 'CREDENTIAL_ERROR') {
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

  /**
   * Bridge: receives ChatStreamEvent from the shared chat WS onEvent callback
   * and dispatches to the existing copilot callback system.
   *
   * The copilot backend emits events through the standard envelope format.
   * Copilot-specific event types (thought_step, tool_call, tool_result, result)
   * are carried in evt.data.type when the envelope type is generic, or may
   * use the envelope type directly.
   */
  const handleCopilotEvent = useCallback(
    (evt: ChatStreamEvent) => {
      const data = evt.data as Record<string, unknown> | undefined
      if (!data) return

      // Check for copilot-specific type in data, fall back to envelope type
      const type = (data.type as string | undefined) || evt.type
      if (!type) return

      switch (type) {
        case 'status':
          callbacks.onStatus(
            (data.stage as string) ?? evt.type,
            (data.message as string) ?? '',
          )
          break
        case 'content':
          callbacks.onContent((data.content as string) ?? '')
          break
        case 'thought_step':
          callbacks.onThoughtStep?.(data.step as { index: number; content: string })
          break
        case 'tool_call':
          callbacks.onToolCall(
            data.tool as string,
            data.input as Record<string, unknown>,
          )
          break
        case 'tool_result':
          callbacks.onToolResult(
            data.action as {
              type: string
              payload: Record<string, unknown>
              reasoning?: string
            },
          )
          break
        case 'result':
          callbacks.onResult?.({
            message: (data.message as string) ?? '',
            actions: data.actions as GraphAction[] | undefined,
          })
          break
        case 'error':
          callbacks.onError(
            (data.message as string) ?? 'Unknown error',
            data.code as string | undefined,
          )
          break
        case 'done':
          callbacks.onDone?.()
          break
      }
    },
    [callbacks],
  )

  return { ...callbacks, handleCopilotEvent }
}
