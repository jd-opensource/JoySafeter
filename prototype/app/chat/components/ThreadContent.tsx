'use client'

import React, { useMemo } from 'react'

import { cn } from '@/lib/core/utils/cn'
import { useTranslation } from '@/lib/i18n'

import { Message, ToolCall } from '../types'

import MessageItem from './MessageItem'

interface ThreadContentProps {
  messages: Message[]
  streamingText?: string
  agentStatus: 'idle' | 'running' | 'connecting' | 'error'
  currentNodeLabel?: string
  onToolClick: (toolCall: ToolCall) => void
  scrollContainerRef: React.RefObject<HTMLDivElement | null>
}

const ThreadContent: React.FC<ThreadContentProps> = ({
  messages,
  streamingText = '',
  agentStatus,
  currentNodeLabel,
  onToolClick,
  scrollContainerRef,
}) => {
  const { t } = useTranslation()

  // When running and last message is assistant, it is shown by Streaming/Processing indicator only
  const messagesToRender = useMemo(() => {
    if (agentStatus === 'running' && messages[messages.length - 1]?.role === 'assistant') {
      return messages.slice(0, -1)
    }
    return messages
  }, [agentStatus, messages])

  return (
    <div
      ref={scrollContainerRef}
      className="h-full overflow-y-auto bg-gray-50 [&::-webkit-scrollbar]:hidden [-ms-overflow-style:none] [scrollbar-width:none]"
    >
      <div className="mx-auto max-w-3xl min-w-0 w-full px-6 py-6">
        <div className="space-y-6 min-w-0">
          {/* Messages - history on top for waterfall layout */}
          {messagesToRender.length === 0 ? (
            <div className="flex items-center justify-center text-gray-400 text-sm py-20">
              {t('chat.startConversation')}
            </div>
          ) : (
            messagesToRender.map((msg, idx) => (
              <MessageItem
                key={msg.id}
                message={msg}
                isLast={idx === messagesToRender.length - 1}
                onToolClick={onToolClick}
              />
            ))
          )}

          {/* Streaming indicator - current reply at bottom */}
          {streamingText && agentStatus === 'running' && (
            <div className="flex justify-start mb-6 animate-in fade-in duration-200">
              <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-600 to-purple-600 flex items-center justify-center mr-4 flex-shrink-0 shadow-md mt-0.5">
                <div className="w-3 h-3 bg-white rounded-full animate-pulse" />
              </div>
              <div className="max-w-[85%] min-w-[50%]">
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-[10px] text-gray-400 px-1.5 py-0.5 bg-gray-100 rounded border border-gray-200">
                    AI
                  </span>
                </div>
                <div className="prose prose-sm prose-gray max-w-none text-gray-800 leading-7">
                  <span className="inline-block w-1.5 h-4 bg-blue-500 animate-pulse rounded-full align-middle mr-1" />
                  {streamingText}
                </div>
              </div>
            </div>
          )}

          {/* Processing indicator - thinking at bottom */}
          {agentStatus === 'running' && messages.length > 0 && !streamingText && (
            <div className="flex justify-start mb-6 animate-in fade-in duration-200">
              <div
                className={cn(
                  'flex items-center gap-4 px-4 py-3 rounded-2xl min-w-0 max-w-[85%]',
                  'bg-white/90 border border-gray-200/80 shadow-sm'
                )}
              >
                <div className="relative flex-shrink-0 w-10 h-10 flex items-center justify-center overflow-hidden rounded-full">
                  <div className="absolute inset-0 w-10 h-10 rounded-full bg-blue-400/20 animate-pulse" />
                  <div className="relative w-8 h-8 rounded-full bg-gradient-to-br from-blue-600 to-purple-600 flex items-center justify-center shadow-md">
                    <div className="flex gap-0.5">
                      <span className="w-2 h-2 bg-white rounded-full animate-bounce [animation-delay:0ms]" />
                      <span className="w-2 h-2 bg-white rounded-full animate-bounce [animation-delay:150ms]" />
                      <span className="w-2 h-2 bg-white rounded-full animate-bounce [animation-delay:300ms]" />
                    </div>
                  </div>
                </div>
                <div className="flex flex-col gap-0.5 min-w-0">
                  <span className="text-sm font-medium text-gray-700 animate-pulse">{t('chat.thinking')}</span>
                  {currentNodeLabel && (
                    <span className="text-xs text-gray-500 truncate" title={currentNodeLabel}>
                      {currentNodeLabel}
                    </span>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default ThreadContent
