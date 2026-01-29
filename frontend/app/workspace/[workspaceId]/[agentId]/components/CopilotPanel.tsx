'use client'

/**
 * CopilotPanel - Main Copilot component
 *
 * Architecture:
 * - useCopilotState: Unified state management
 * - useCopilotWebSocketHandler: WebSocket event handling
 * - useCopilotActions: Business logic (send, stop, reset)
 * - useCopilotEffects: Side effects (session recovery, auto-scroll, URL params)
 *
 * This component is now focused solely on UI rendering and composition.
 */

import { Loader2 } from 'lucide-react'
import { useParams } from 'next/navigation'
import React, { useCallback } from 'react'

import { CopilotErrorBoundary } from '@/components/copilot/CopilotErrorBoundary'
import { useCopilotWebSocket } from '@/hooks/use-copilot-websocket'
import { useTranslation } from '@/lib/i18n'

import { useCopilotActions } from '../hooks/useCopilotActions'
import { useCopilotEffects } from '../hooks/useCopilotEffects'
import { useCopilotState } from '../hooks/useCopilotState'
import { useCopilotWebSocketHandler } from '../hooks/useCopilotWebSocketHandler'
import { formatActionContent, getStageConfig } from '../utils/copilotUtils'

import { CopilotChat } from './copilot/CopilotChat'
import { CopilotInput } from './copilot/CopilotInput'
import { CopilotStreaming } from './copilot/CopilotStreaming'

// Export types
export type { GraphAction } from '@/types/copilot'

export const CopilotPanel: React.FC = () => {
  const { t } = useTranslation()
  const params = useParams()
  const graphId = params.agentId as string | undefined

  // Unified state management
  const { state, actions, refs } = useCopilotState(graphId)

  // WebSocket event handlers
  const webSocketCallbacks = useCopilotWebSocketHandler({
    state,
    actions,
    refs,
    graphId,
  })

  // Business logic handlers
  const {
    handleSend,
    handleSendWithInput,
    handleStop,
    handleReset,
    handleAIDecision,
  } = useCopilotActions({
    state,
    actions,
    refs,
    graphId,
  })

  // Side effects (session recovery, auto-scroll, URL params, etc.)
  useCopilotEffects({
    state,
    actions,
    refs,
    graphId,
    handleSendWithInput,
  })

  // WebSocket connection
  useCopilotWebSocket({
    sessionId: state.currentSessionId,
    callbacks: webSocketCallbacks,
    autoReconnect: true,
  })

  // Stage config
  const stageConfig = getStageConfig(t)

  // Copy streaming content handler
  const handleCopyStreaming = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(state.streamingContent)
      if (!refs.isMountedRef.current) return

      // Clear previous timeout if exists
      if (refs.copyTimeoutRef.current) {
        clearTimeout(refs.copyTimeoutRef.current)
        refs.copyTimeoutRef.current = null
      }

      actions.setCopiedStreaming(true)
      refs.copyTimeoutRef.current = setTimeout(() => {
        if (refs.isMountedRef.current) {
          actions.setCopiedStreaming(false)
        }
        refs.copyTimeoutRef.current = null
      }, 2000)
    } catch (err) {
      console.error('Failed to copy:', err)
    }
  }, [state.streamingContent, actions, refs])

  return (
    <CopilotErrorBoundary>
      <div className="flex flex-col h-full bg-white relative">
        {/* Messages and streaming area */}
        <div
          className="flex-1 overflow-y-auto p-3 space-y-5 custom-scrollbar"
          ref={refs.scrollRef}
        >
          {/* Loading history indicator */}
          {state.loadingHistory && (
            <div className="flex items-center justify-center py-4">
              <Loader2 size={16} className="animate-spin text-purple-500 mr-2" />
              <span className="text-xs text-gray-500">{t('workspace.loadingHistory')}</span>
            </div>
          )}

          {/* Chat messages */}
          <CopilotChat
            messages={state.messages}
            loadingHistory={state.loadingHistory}
            expandedItems={state.expandedItems}
            onToggleExpand={actions.toggleExpand}
            formatActionContent={formatActionContent}
          />

          {/* Streaming content */}
          <CopilotStreaming
            loading={state.loading}
            currentStage={state.currentStage}
            streamingContent={state.streamingContent}
            currentToolCall={state.currentToolCall}
            toolResults={state.toolResults}
            expandedToolTypes={state.expandedToolTypes}
            copiedStreaming={state.copiedStreaming}
            streamingContentRef={refs.streamingContentRef}
            stageConfig={stageConfig}
            onToggleToolType={actions.toggleToolType}
            onCopyStreaming={handleCopyStreaming}
          />
        </div>

        {/* Input area */}
        <CopilotInput
          input={state.input}
          loading={state.loading}
          executingActions={state.executingActions}
          messagesCount={state.messages.length}
          onInputChange={actions.setInput}
          onSend={handleSend}
          onStop={handleStop}
          onReset={handleReset}
          onAIDecision={handleAIDecision}
        />
      </div>
    </CopilotErrorBoundary>
  )
}
