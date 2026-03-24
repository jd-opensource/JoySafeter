'use client'

import React, { useRef, useEffect, useCallback } from 'react'

import { useChatState, useChatStream } from '../ChatProvider'
import ChatInput from '../components/ChatInput'
import ThreadContent from '../components/ThreadContent'
import type { UploadedFile } from '../services/modeHandlers/types'
import type { ToolCall } from '../types'

interface ConversationPanelProps {
  onSend: (text: string, mode?: string, graphId?: string | null, files?: UploadedFile[]) => void
  onStop: () => void
}

export default function ConversationPanel({ onSend, onStop }: ConversationPanelProps) {
  const { state, dispatch } = useChatState()
  const { text: streamingText, isProcessing, resumeChat } = useChatStream()
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

  const handleResume = useCallback(async () => {
    const interrupt = state.streaming.interrupt
    if (!interrupt || isProcessing) return

    dispatch({ type: 'STREAM_START' })
    try {
      await resumeChat({
        threadId: interrupt.threadId,
        command: { update: {}, goto: null },
      })
    } catch (error) {
      console.error('Failed to resume chat:', error)
    }
  }, [dispatch, isProcessing, resumeChat, state.streaming.interrupt])

  return (
    <div className="flex h-full flex-col">
      {/* Message area */}
      <div className="flex-1 overflow-hidden">
        {state.streaming.interrupt && (
          <div className="border-b border-amber-200 bg-amber-50 px-6 py-3">
            <div className="mx-auto flex max-w-3xl items-center justify-between gap-4">
              <div className="min-w-0">
                <p className="text-sm font-medium text-amber-900">
                  Execution interrupted
                </p>
                <p className="truncate text-xs text-amber-700">
                  {state.streaming.interrupt.nodeLabel || state.streaming.interrupt.nodeName}
                </p>
              </div>
              <button
                type="button"
                onClick={handleResume}
                disabled={isProcessing}
                className="rounded-full bg-amber-600 px-4 py-2 text-xs font-medium text-white transition hover:bg-amber-700 disabled:cursor-not-allowed disabled:opacity-60"
              >
                Resume
              </button>
            </div>
          </div>
        )}
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
      <div className="border-t border-gray-100 bg-white p-4">
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
