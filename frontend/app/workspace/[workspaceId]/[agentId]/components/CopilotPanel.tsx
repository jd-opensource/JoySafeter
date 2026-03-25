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
import { useCallback, useMemo, useState } from 'react'

import { CopilotErrorBoundary } from '@/components/copilot/CopilotErrorBoundary'
import { useModels } from '@/hooks/queries/models'
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

export type CopilotMode = import('./copilot/CopilotInput').CopilotMode

export function CopilotPanel() {
  const { t } = useTranslation()
  const params = useParams()
  const graphId = params.agentId as string | undefined

  const [copilotMode, setCopilotMode] = useState<CopilotMode>('deepagents')

  // Default model label from settings (for status bar)
  const { data: models = [] } = useModels()
  const defaultModelLabel = useMemo(() => {
    const defaultModel = models.find((m) => m.isDefault === true && m.isAvailable !== false)
    if (defaultModel) return defaultModel.label
    const first = models.find((m) => m.isAvailable !== false)
    return first?.label ?? ''
  }, [models])

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
  const { handleSend, handleSendWithInput, handleStop, handleReset, handleAIDecision } =
    useCopilotActions({
      state,
      actions,
      refs,
      graphId,
      copilotMode,
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
        // eslint-disable-next-line react-hooks/immutability
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
      <div className="relative flex h-full flex-col bg-[var(--surface-1)]">
        {/* Messages and streaming area */}
        <div className="custom-scrollbar flex-1 space-y-5 overflow-y-auto p-3" ref={refs.scrollRef}>
          {/* Loading history indicator */}
          {state.loadingHistory && (
            <div className="flex items-center justify-center py-4">
              <Loader2 size={16} className="mr-2 animate-spin text-purple-500" />
              <span className="text-xs text-[var(--text-tertiary)]">{t('workspace.loadingHistory')}</span>
            </div>
          )}

          {/* Chat messages */}
          <CopilotChat
            messages={state.messages}
            loadingHistory={state.loadingHistory}
            expandedItems={state.expandedItems}
            onToggleExpand={actions.toggleExpand}
            formatActionContent={formatActionContent}
            onBlueprintSelect={handleSendWithInput}
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
          onSendWithText={handleSendWithInput}
          copilotMode={copilotMode}
          onModeChange={setCopilotMode}
          modelLabel={defaultModelLabel || undefined}
        />
      </div>
    </CopilotErrorBoundary>
  )
}
