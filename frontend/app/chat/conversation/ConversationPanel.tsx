'use client'

import React, { useRef, useEffect, useCallback } from 'react'

import { useChatState, useChatStream } from '../ChatProvider'
import type { ToolCall } from '../types'

import MessageList from './MessageList'
import ChatInput from './ChatInput'
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

  return (
    <div className="flex h-full flex-col">
      {/* Message area */}
      <div className="flex-1 overflow-hidden">
        <MessageList
          messages={state.messages}
          streamingText={streamingText}
          agentStatus={agentStatus}
          currentNodeLabel={currentNodeLabel}
          onToolClick={handleToolClick}
          scrollContainerRef={scrollRef}
        />
      </div>

      {/* Input area */}
      <div className="border-t border-gray-100 bg-white px-6 py-4">
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
