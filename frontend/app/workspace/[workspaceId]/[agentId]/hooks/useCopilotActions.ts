/**
 * useCopilotActions - Business logic hook for Copilot actions
 *
 * Handles all user interactions: send, stop, reset, AI decision, etc.
 */

import { useQueryClient } from '@tanstack/react-query'
import { useParams } from 'next/navigation'
import { useCallback } from 'react'

import { graphKeys } from '@/hooks/queries/graphs'
import { useTranslation } from '@/lib/i18n'
import { copilotService } from '@/services/copilotService'

import { useBuilderStore } from '../stores/builderStore'

import type { CopilotState, CopilotActions, CopilotRefs } from './useCopilotState'

export type CopilotMode = 'standard' | 'deepagents'

interface UseCopilotActionsOptions {
  state: CopilotState
  actions: CopilotActions
  refs: CopilotRefs
  graphId?: string
  copilotMode?: CopilotMode
}

export function useCopilotActions({
  state,
  actions,
  refs,
  graphId,
  copilotMode = 'deepagents',
}: UseCopilotActionsOptions) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const params = useParams()
  const currentGraphId = params.agentId as string | undefined
  const { getGraphContext } = useBuilderStore()

  const handleSendWithInput = useCallback(
    async (userText: string) => {
      if (!userText.trim() || state.loading || !refs.isMountedRef.current) return

      actions.setInput('')
      actions.addMessage({ role: 'user', text: userText })

      if (!refs.isMountedRef.current) return
      actions.setLoading(true)
      actions.clearStreaming()

      // Mark that we're creating a new session
      // eslint-disable-next-line react-hooks/immutability
      refs.isCreatingSessionRef.current = true
      actions.clearSession()

      // Get serialized context from store
      const graphContext = getGraphContext()
      const storeGraphId = useBuilderStore.getState().graphId

      if (!storeGraphId) {
        console.error('[CopilotPanel] No graphId in store')
        if (refs.isMountedRef.current) {
          actions.setLoading(false)
        }
        return
      }

      try {
        // Convert conversation history to OpenAI format
        const historyMessages = copilotService.convertConversationHistory(state.messages)

        // Create Copilot session
        const sessionResult = await copilotService.createCopilotTask({
          userPrompt: userText,
          graphContext,
          conversationHistory: historyMessages,
          graphId: graphId || null,
          mode: copilotMode,
        })

        // Check if component is still mounted
        if (!refs.isMountedRef.current) return

        const sessionId = sessionResult.session_id
        actions.setSession(sessionId)

        // Show initial loading state
        actions.setCurrentStage({ stage: 'thinking', message: '正在连接并准备处理...' })
        actions.setThinkingMessage()
      } catch (e: unknown) {
        console.error('[CopilotPanel] Failed to create Copilot session:', e)

        if (!refs.isMountedRef.current) return

        actions.setLoading(false)
        actions.clearStreaming()

        // Provide user-friendly error messages
        let errorMessage = t('workspace.couldNotProcessRequest')

        if (e && typeof e === 'object') {
          const error = e as { response?: { status?: number }; message?: string }
          if (error.response?.status === 503) {
            errorMessage = t('workspace.copilot.error.redis', {
              defaultValue: 'Service temporarily unavailable. Please try again later.',
            })
          } else if (error.response?.status === 401 || error.response?.status === 403) {
            errorMessage = t('workspace.copilot.error.auth', {
              defaultValue: 'Authentication error. Please check your credentials.',
            })
          } else if (error.message?.includes('fetch') || error.message?.includes('network')) {
            errorMessage = t('workspace.copilot.error.network', {
              defaultValue: 'Network error. Please check your connection and try again.',
            })
          }
        }

        actions.finalizeCurrentMessage(`${t('workspace.systemError')}: ${errorMessage}`)
        refs.isCreatingSessionRef.current = false
        actions.clearSession()
      }
    },
    [state.loading, state.messages, actions, refs, graphId, copilotMode, getGraphContext, t],
  )

  const handleSend = useCallback(async () => {
    if (!state.input.trim() || state.loading) return
    await handleSendWithInput(state.input.trim())
  }, [state.input, state.loading, handleSendWithInput])

  const handleStop = useCallback(() => {
    actions.clearSession()

    if (!refs.isMountedRef.current) return
    actions.setLoading(false)
    actions.clearStreaming()

    // eslint-disable-next-line react-hooks/immutability
    refs.isCreatingSessionRef.current = false
    actions.removeCurrentMessage()
    actions.addMessage({ role: 'model', text: t('workspace.requestCancelled') })
  }, [actions, refs, t])

  const handleReset = useCallback(async () => {
    actions.clearSession()

    const idToClear = graphId ?? currentGraphId
    let serverCleared = true
    if (idToClear) {
      serverCleared = await copilotService.clearHistory(idToClear)
      if (!refs.isMountedRef.current) return
      if (serverCleared && idToClear) {
        queryClient.invalidateQueries({ queryKey: graphKeys.copilotHistory(idToClear) })
      }
    }

    if (!serverCleared) {
      console.warn('[Copilot] Clear history failed on server, keeping local list')
      return
    }

    if (!refs.isMountedRef.current) return
    actions.clearMessages()
    actions.setInput('')
    actions.setLoading(false)
    actions.clearStreaming()
    actions.clearExpandedItems()
    // eslint-disable-next-line react-hooks/immutability
    refs.hasProcessedUrlInputRef.current = false
  }, [actions, refs, graphId, currentGraphId, queryClient])

  const handleAIDecision = useCallback(() => {
    if (!state.loading) {
      handleSendWithInput(t('workspace.aiDecisionPrompt'))
    }
  }, [state.loading, handleSendWithInput, t])

  return {
    handleSend,
    handleSendWithInput,
    handleStop,
    handleReset,
    handleAIDecision,
  }
}
