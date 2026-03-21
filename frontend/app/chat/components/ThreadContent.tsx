'use client'

import React, { useMemo } from 'react'

import { cn } from '@/lib/utils'
import { useTranslation } from '@/lib/i18n'

import { Message, ToolCall } from '../types'

import MessageItem from './MessageItem'

interface ThreadContentProps {
  messages: Message[]
  streamingText?: string
  agentStatus: 'idle' | 'running' | 'connecting' | 'error'
  currentNodeLabel?: string
  onToolClick: (toolCall: ToolCall) => void
  onRetry?: (messageContent: string) => void
  scrollContainerRef: React.RefObject<HTMLDivElement | null>
}

export default function ThreadContent({
  messages,
  streamingText = '',
  agentStatus,
  currentNodeLabel,
  onToolClick,
  onRetry,
  scrollContainerRef,
}: ThreadContentProps) {
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
      className="h-full overflow-y-auto bg-gray-50 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
    >
      <div className="mx-auto w-full min-w-0 max-w-3xl px-6 py-6">
        <div className="min-w-0 space-y-6">
          {/* Messages - history on top for waterfall layout */}
          {messagesToRender.length === 0 ? (
            <div className="flex items-center justify-center py-20 text-sm text-gray-400">
              {t('chat.startConversation')}
            </div>
          ) : (
            messagesToRender.map((msg, idx) => (
              <MessageItem
                key={msg.id}
                message={msg}
                isLast={idx === messagesToRender.length - 1}
                onToolClick={onToolClick}
                onRetry={
                  msg.role === 'assistant' && idx === messagesToRender.length - 1 && onRetry
                    ? () => {
                        // Find the preceding user message to re-send
                        for (let i = idx - 1; i >= 0; i--) {
                          if (messagesToRender[i].role === 'user') {
                            onRetry(messagesToRender[i].content)
                            return
                          }
                        }
                      }
                    : undefined
                }
              />
            ))
          )}

          {/* Streaming indicator - current reply at bottom */}
          {streamingText && agentStatus === 'running' && (
            <div className="mb-6 flex justify-start duration-200 animate-in fade-in">
              <div className="mr-4 mt-0.5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-blue-600 to-purple-600 shadow-md">
                <div className="h-3 w-3 animate-pulse rounded-full bg-white" />
              </div>
              <div className="min-w-[50%] max-w-[85%]">
                <div className="mb-2 flex items-center gap-2">
                  <span className="rounded border border-gray-200 bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-400">
                    AI
                  </span>
                </div>
                <div className="prose prose-sm prose-gray max-w-none leading-7 text-gray-800">
                  <span className="mr-1 inline-block h-4 w-1.5 animate-pulse rounded-full bg-blue-500 align-middle" />
                  {streamingText}
                </div>
              </div>
            </div>
          )}

          {/* Processing indicator - thinking at bottom */}
          {agentStatus === 'running' && messages.length > 0 && !streamingText && (
            <div className="mb-6 flex justify-start duration-200 animate-in fade-in">
              <div
                className={cn(
                  'flex min-w-0 max-w-[85%] items-center gap-4 rounded-2xl px-4 py-3',
                  'border border-gray-200/80 bg-white/90 shadow-sm',
                )}
              >
                <div className="relative flex h-10 w-10 flex-shrink-0 items-center justify-center overflow-hidden rounded-full">
                  <div className="absolute inset-0 h-10 w-10 animate-pulse rounded-full bg-blue-400/20" />
                  <div className="relative flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-blue-600 to-purple-600 shadow-md">
                    <div className="flex gap-0.5">
                      <span className="h-2 w-2 animate-bounce rounded-full bg-white [animation-delay:0ms]" />
                      <span className="h-2 w-2 animate-bounce rounded-full bg-white [animation-delay:150ms]" />
                      <span className="h-2 w-2 animate-bounce rounded-full bg-white [animation-delay:300ms]" />
                    </div>
                  </div>
                </div>
                <div className="flex min-w-0 flex-col gap-0.5">
                  <span className="animate-pulse text-sm font-medium text-gray-700">
                    {t('chat.thinking')}
                  </span>
                  {currentNodeLabel && (
                    <span className="truncate text-xs text-gray-500" title={currentNodeLabel}>
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
