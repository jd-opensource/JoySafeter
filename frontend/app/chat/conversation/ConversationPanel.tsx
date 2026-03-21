'use client'

import React, { useRef, useEffect, useCallback } from 'react'

import { useChatState, useChatStream } from '../ChatProvider'
import type { ToolCall } from '../types'

import ThreadContent from '../components/ThreadContent'
import ChatInput from '../components/ChatInput'
import type { UploadedFile } from '../services/modeHandlers/types'

interface ConversationPanelProps {
  onSend: (text: string, mode?: string, graphId?: string | null, files?: UploadedFile[]) => void
  onStop: () => void
}

export default function ConversationPanel({ onSend, onStop }: ConversationPanelProps) {
  const { state, dispatch } = useChatState()
  const { text: streamingText, isProcessing } = useChatStream()
  const scrollRef = useRef<HTMLDivElement>(null)

  // Determine agent status from streaming state
  const agentStatus: 'idle' | 'running' | 'connecting' | 'error' = isProcessing ? 'running' : 'idle'

  // Current node label from last message metadata
  const lastMsg = state.messages[state.messages.length - 1]
  const currentNodeLabel = lastMsg?.metadata?.currentNode

  // Auto-scroll on new content
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [state.messages, streamingText])

  const handleToolClick = useCallback(
    (toolCall: ToolCall) => {
      dispatch({ type: 'SELECT_TOOL', tool: toolCall })
      dispatch({ type: 'SHOW_PREVIEW' })
    },
    [dispatch],
  )

  const handleSetInput = useCallback(
    (value: string) => {
      dispatch({ type: 'SET_INPUT', value })
    },
    [dispatch],
  )

  const handleRetry = useCallback(
    (messageContent: string) => {
      if (!isProcessing) {
        onSend(messageContent, state.mode.currentMode, state.mode.currentGraphId)
      }
    },
    [isProcessing, onSend, state.mode.currentMode, state.mode.currentGraphId],
  )

  return (
    <div className="flex h-full flex-col">
      {/* Message area */}
      <div className="flex-1 overflow-hidden">
        <ThreadContent
          messages={state.messages}
          streamingText={streamingText}
          agentStatus={agentStatus}
          currentNodeLabel={currentNodeLabel}
          onToolClick={handleToolClick}
          onRetry={handleRetry}
          scrollContainerRef={scrollRef}
        />
      </div>

      {/* Input area */}
      <div className="bg-white px-6 py-4 shadow-[0_-4px_24px_-4px_rgba(0,0,0,0.06)]">
        <ChatInput
          input={state.input}
          setInput={handleSetInput}
          onSubmit={onSend}
          isProcessing={isProcessing}
          onStop={onStop}
          currentMode={state.mode.currentMode}
          currentGraphId={state.mode.currentGraphId}
        />
      </div>
    </div>
  )
}
