/**
 * useCopilotWebSocketHandler - WebSocket event handler hook for Copilot
 * 
 * Encapsulates all WebSocket event handling logic with proper mount checks
 * and error handling.
 */

import { useQueryClient } from '@tanstack/react-query'
import { useMemo, useCallback } from 'react'

import type { StageType } from '@/hooks/copilot/useCopilotStreaming'
import { graphKeys } from '@/hooks/queries/graphs'
import { useTranslation } from '@/lib/i18n'
import type { GraphAction } from '@/types/copilot'

import type { CopilotState, CopilotActions, CopilotRefs } from './useCopilotState'

interface UseCopilotWebSocketHandlerOptions {
  state: CopilotState
  actions: CopilotActions
  refs: CopilotRefs
  graphId?: string
}

/**
 * Helper function to check if there's a current message being streamed
 */
function hasCurrentMessage(messages: Array<{ role: string; text?: string }>, checkEmptyText = true): boolean {
  if (messages.length === 0) return false
  const lastMessage = messages[messages.length - 1]
  if (lastMessage.role !== 'model') return false
  if (checkEmptyText && lastMessage.text) return false
  return true
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
      // Use current state values
      const { loading, currentStage } = state
      if (loading && !currentStage) {
        actions.setCurrentStage({ stage: 'thinking', message: '已连接，正在思考...' })
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
      
      actions.clearStreaming()
      
      const normalizedMessage = response.message.replace(/\n{2,}/g, '\n')
      actions.finalizeCurrentMessage(normalizedMessage, response.actions)
      
      // Execute actions if present
      if (response.actions && response.actions.length > 0) {
        await actions.executeActions(response.actions)
        if (!refs.isMountedRef.current) return
      }
      
      // Invalidate graph state cache
      if (graphId && refs.isMountedRef.current) {
        queryClient.invalidateQueries({ queryKey: graphKeys.state(graphId) })
      }
      
      // Reset session creation flag
      refs.isCreatingSessionRef.current = false
      
      // Clear session after completion
      if (refs.isMountedRef.current) {
        actions.clearSession()
        actions.setLoading(false)
      }
    },
    
    onError: (error: string) => {
      if (!refs.isMountedRef.current) return
      
      actions.clearStreaming()
      
      // Provide user-friendly error messages
      let errorMessage = error
      if (error.includes('Credential') || error.includes('API key')) {
        errorMessage = t('workspace.copilot.error.credential', { 
          defaultValue: 'Authentication error. Please check your API credentials in settings.' 
        })
      } else if (error.includes('Connection') || error.includes('WebSocket')) {
        errorMessage = t('workspace.copilot.error.connection', { 
          defaultValue: 'Connection error. Please check your network connection and try again.' 
        })
      } else if (error.includes('Max reconnection')) {
        errorMessage = t('workspace.copilot.error.reconnect', { 
          defaultValue: 'Connection lost. Please refresh the page and try again.' 
        })
      } else {
        errorMessage = `${t('workspace.systemError')}: ${error}`
      }
      
      actions.finalizeCurrentMessage(errorMessage)
      
      // Reset session creation flag on error
      refs.isCreatingSessionRef.current = false
      
      if (refs.isMountedRef.current) {
        actions.clearSession()
        actions.setLoading(false)
      }
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
