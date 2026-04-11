/**
 * useCopilotActions - Business logic hook for Copilot actions
 *
 * Handles all user interactions: send, stop, reset, AI decision, etc.
 * Uses Run Center (runService.createRun) + shared chat WS (getChatWsClient) for execution.
 */

import { useQueryClient } from '@tanstack/react-query'
import { useParams } from 'next/navigation'
import { useCallback, useRef } from 'react'

import { graphKeys } from '@/hooks/queries/graphs'
import { useTranslation } from '@/lib/i18n'
import { generateUUID } from '@/lib/utils/uuid'
import { getChatWsClient } from '@/lib/ws/chat/chatWsClient'
import type { CopilotExtension } from '@/lib/ws/chat/types'
import type { ChatStreamEvent } from '@/services/chatBackend'
import { copilotService } from '@/services/copilotService'
import { runService } from '@/services/runService'

import { useBuilderStore } from '../stores/builderStore'

import type { CopilotState, CopilotActions, CopilotRefs } from './useCopilotState'

export type CopilotMode = 'standard' | 'deepagents'

interface UseCopilotActionsOptions {
  state: CopilotState
  actions: CopilotActions
  refs: CopilotRefs
  graphId?: string
  copilotMode?: CopilotMode
  selectedModel?: string
  onCopilotEvent?: (evt: ChatStreamEvent) => void
}

export function useCopilotActions({
  state,
  actions,
  refs,
  graphId,
  copilotMode = 'deepagents',
  selectedModel,
  onCopilotEvent,
}: UseCopilotActionsOptions) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const params = useParams()
  const currentGraphId = params.agentId as string | undefined
  const { getGraphContext } = useBuilderStore()
  const activeRequestIdRef = useRef<string | null>(null)

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

        // 1. Create run via Run Center
        let runId: string | null = null
        try {
          const runResponse = await runService.createRun({
            agent_name: 'copilot',
            graph_id: graphId || storeGraphId,
            message: userText,
          })
          runId = runResponse.run_id
        } catch (err) {
          console.warn('[Copilot] Failed to create run, proceeding without persistence', err)
        }

        // Check if component is still mounted
        if (!refs.isMountedRef.current) return

        // Save run_id
        if (runId) {
          actions.setSession(runId)
        }

        // Show initial loading state
        actions.setCurrentStage({ stage: 'thinking', message: 'Connecting...' })
        actions.setThinkingMessage()

        // 2. Send via shared chat WS
        const extension: CopilotExtension = {
          kind: 'copilot',
          runId,
          graphContext,
          conversationHistory: historyMessages as unknown as Array<Record<string, unknown>>,
          mode: copilotMode || 'deepagents',
        }

        const requestId = generateUUID()
        activeRequestIdRef.current = requestId

        const result = await getChatWsClient().sendChat({
          requestId,
          input: {
            message: userText,
            model: selectedModel,
          },
          graphId: graphId || storeGraphId,
          extension,
          onEvent: (evt) => onCopilotEvent?.(evt),
        })

        if (result.terminal === 'error' && refs.isMountedRef.current) {
          actions.setLoading(false)
          actions.clearStreaming()
          refs.isCreatingSessionRef.current = false
          actions.clearSession()
        }
      } catch (e: unknown) {
        console.error('[CopilotPanel] Failed to send copilot message:', e)

        if (!refs.isMountedRef.current) return

        actions.setLoading(false)
        actions.clearStreaming()

        // Provide user-friendly error messages
        let errorMessage = t('workspace.couldNotProcessRequest')

        if (e && typeof e === 'object') {
          const error = e as { response?: { status?: number }; message?: string }
          if (error.response?.status === 401 || error.response?.status === 403) {
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
      } finally {
        activeRequestIdRef.current = null
      }
    },
    [state.loading, state.messages, actions, refs, graphId, copilotMode, selectedModel, getGraphContext, t, onCopilotEvent],
  )

  const handleSend = useCallback(async () => {
    if (!state.input.trim() || state.loading) return
    await handleSendWithInput(state.input.trim())
  }, [state.input, state.loading, handleSendWithInput])

  const handleStop = useCallback(() => {
    // Send chat.stop frame to cancel the backend stream
    const requestId = activeRequestIdRef.current
    if (requestId) {
      getChatWsClient().stopByRequestId(requestId)
      activeRequestIdRef.current = null
    }

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
