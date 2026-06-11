/**
 * useCopilotWebSocketHandler - WebSocket event handler hook for Build Copilot
 *
 * Architecture: Backend is the single writer for graph state. On "result" we only
 * do optimistic render (applyAIChanges, no save). On "done" we invalidate caches
 * and clear session. The callback system ensures onResult
 * completes before onDone runs.
 */

import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef } from 'react'

import type { StageType } from '@/hooks/copilot/useCopilotStreaming'
import { versionKeys } from '@/hooks/queries/agentVersions'
import { useTranslation } from '@/lib/i18n'
import type { AppErrorPayload } from '@/types/agent-run'
import type { GraphAction } from '@/types/copilot'

import { hasCurrentMessage } from '../utils/copilotUtils'
import { useGraphStore } from '../stores/graphStore'

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

      onError: (error: AppErrorPayload) => {
        if (!refs.isMountedRef.current) return
        try {
          actions.clearStreaming()
          let errorMessage = error.message
          if (error.code === 'MODEL_NO_CREDENTIALS') {
            errorMessage = t('workspace.copilotError.credentialNotConfigured', {
              defaultValue: 'No model configured. Please set up your LLM credentials in settings.',
            })
          } else if (error.code === 'BUILD_COPILOT_MODEL_REQUIRED') {
            errorMessage = t('workspace.copilotError.buildCopilotModelRequired', {
              defaultValue: 'Build Copilot has no model configured. Select a model and try again.',
            })
          } else if (error.code === 'MODEL_NOT_FOUND') {
            errorMessage = t('workspace.copilotError.modelNotFound', {
              defaultValue: 'Model not found. Please check your model configuration.',
            })
          } else if (error.code === 'MODEL_NAME_REQUIRED') {
            errorMessage = t('workspace.copilotError.modelNameRequired', {
              defaultValue: 'No model selected. Please select a model first.',
            })
          } else if (error.code === 'CREDENTIAL_ERROR') {
            errorMessage = t('workspace.copilotError.credential', {
              defaultValue: 'Authentication error. Please check API credentials.',
            })
          } else if (
            error.code === 'WEBSOCKET_CONNECTION_FAILED' ||
            error.code === 'WEBSOCKET_UNAVAILABLE'
          ) {
            errorMessage = t('workspace.copilotError.connection', {
              defaultValue: 'Connection error. Please check your network.',
            })
          } else {
            errorMessage = `${t('workspace.systemError')}: ${error.message}`
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
          const { versionId, projectId } = useGraphStore.getState()
          if (versionId && projectId) {
            queryClient.invalidateQueries({
              queryKey: versionKeys.graphState(graphId, versionId, projectId),
            })
          }
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
