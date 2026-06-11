import { useCallback } from 'react'

import { ApiError } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import { agentRunService } from '@/services/agentRunService'
import { draftCopilotService } from '@/services/draftCopilotService'

import { useGraphStore } from '../stores/graphStore'

import type { CopilotState, CopilotActions, CopilotRefs } from './useCopilotState'

export type CopilotMode = 'standard' | 'deepagents'

interface UseCopilotActionsOptions {
  state: CopilotState
  actions: CopilotActions
  refs: CopilotRefs
  copilotMode?: CopilotMode
  selectedProviderName?: string
  selectedModelName?: string
}

export function useCopilotActions({
  state,
  actions,
  refs,
  copilotMode = 'deepagents',
  selectedProviderName,
  selectedModelName,
}: UseCopilotActionsOptions) {
  const { t } = useTranslation()
  const { getGraphContext } = useGraphStore()

  const handleSendWithInput = useCallback(
    async (userText: string) => {
      if (!userText.trim() || state.loading || !refs.isMountedRef.current) return

      actions.setInput('')
      actions.addMessage({ role: 'user', text: userText })

      if (!refs.isMountedRef.current) return
      actions.setLoading(true)
      actions.clearStreaming()

      // Follow-up to active execution
      if (state.currentExecutionId) {
        try {
          await agentRunService.sendMessage(state.currentExecutionId, userText)
        } catch (e) {
          console.error('[CopilotPanel] Failed to send follow-up:', e)
          if (refs.isMountedRef.current) {
            actions.setLoading(false)
            actions.finalizeCurrentMessage(t('workspace.systemError'))
          }
        }
        return
      }

      // eslint-disable-next-line react-hooks/immutability
      refs.isCreatingSessionRef.current = true
      actions.clearSession()

      const graphContext = getGraphContext()
      const storeState = useGraphStore.getState()
      const storeGraphId = storeState.graphId
      const storeAgentId = storeState.agentId
      const storeVersionId = storeState.versionId
      const storeProjectId = storeState.projectId

      if (!storeGraphId || !storeAgentId || !storeVersionId || !storeProjectId) {
        console.error('[CopilotPanel] Missing graph, agent, version, or project in store')
        if (refs.isMountedRef.current) {
          actions.setLoading(false)
          actions.finalizeCurrentMessage(
            `${t('workspace.systemError')}: ${t('workspace.couldNotProcessRequest')}`,
          )
        }
        return
      }

      try {
        actions.setCurrentStage({ stage: 'thinking', message: 'Connecting...' })
        actions.setThinkingMessage()

        const { run_id, execution_id } = await draftCopilotService.dispatchRun({
          agentId: storeAgentId,
          versionId: storeVersionId,
          projectId: storeProjectId,
          prompt: userText,
          graphContext,
          conversationHistory: state.messages,
          mode: copilotMode,
          providerName: selectedProviderName,
          modelName: selectedModelName,
        })

        if (!refs.isMountedRef.current) return

        // Bridge auto-subscribes to /ws/executions when executionId is set
        actions.setSession(run_id, execution_id)
        // eslint-disable-next-line react-hooks/immutability
        refs.isCreatingSessionRef.current = false
      } catch (e: unknown) {
        console.error('[DraftCopilotPanel] Failed to dispatch copilot run:', e)

        if (!refs.isMountedRef.current) return

        actions.setLoading(false)
        actions.clearStreaming()

        let errorMessage = t('workspace.couldNotProcessRequest')

        if (e instanceof ApiError) {
          if (e.status === 401 || e.status === 403) {
            errorMessage = t('workspace.copilotError.auth', {
              defaultValue: 'Authentication error. Please check your credentials.',
            })
          } else if (e.code === 'NETWORK_ERROR' || e.code === 'REQUEST_TIMEOUT') {
            errorMessage = t('workspace.copilotError.network', {
              defaultValue: 'Network error. Please check your connection and try again.',
            })
          } else if (e.message) {
            errorMessage = e.message
          }
        }

        actions.finalizeCurrentMessage(`${t('workspace.systemError')}: ${errorMessage}`)
        refs.isCreatingSessionRef.current = false
        actions.clearSession()
      }
    },
    [
      state.loading,
      state.messages,
      state.currentExecutionId,
      actions,
      refs,
      copilotMode,
      selectedProviderName,
      selectedModelName,
      getGraphContext,
      t,
    ],
  )

  const handleSend = useCallback(async () => {
    if (!state.input.trim() || state.loading) return
    await handleSendWithInput(state.input.trim())
  }, [state.input, state.loading, handleSendWithInput])

  const handleStop = useCallback(async () => {
    if (state.currentRunId) {
      try {
        await agentRunService.cancel(state.currentRunId)
      } catch (e) {
        console.warn('[Copilot] Failed to cancel run:', e)
      }
    }

    actions.clearSession()

    if (!refs.isMountedRef.current) return
    actions.setLoading(false)
    actions.clearStreaming()

    // eslint-disable-next-line react-hooks/immutability
    refs.isCreatingSessionRef.current = false
    actions.removeCurrentMessage()
    actions.addMessage({ role: 'model', text: t('workspace.requestCancelled') })
  }, [state.currentRunId, actions, refs, t])

  const handleReset = useCallback(async () => {
    actions.clearSession()

    if (!refs.isMountedRef.current) return
    actions.clearMessages()
    actions.setInput('')
    actions.setLoading(false)
    actions.clearStreaming()
    actions.clearExpandedItems()
    // eslint-disable-next-line react-hooks/immutability
    refs.hasProcessedUrlInputRef.current = false
  }, [actions, refs])

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
