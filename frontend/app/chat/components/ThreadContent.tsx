'use client'

import React from 'react'

import { cn } from '@/lib/core/utils/cn'
import { useTranslation } from '@/lib/i18n'

import { Message, ToolCall } from '../types'

import MessageItem from './MessageItem'

interface ThreadContentProps {
  messages: Message[]
  streamingText?: string
  agentStatus: 'idle' | 'running' | 'connecting' | 'error'
  onToolClick: (toolCall: ToolCall) => void
  scrollContainerRef: React.RefObject<HTMLDivElement | null>
}

const ThreadContent: React.FC<ThreadContentProps> = ({
  messages,
  streamingText = '',
  agentStatus,
  onToolClick,
  scrollContainerRef,
}) => {
  const { t } = useTranslation()
  return (
    <div
      ref={scrollContainerRef}
      className="h-full overflow-y-auto bg-gray-50 [&::-webkit-scrollbar]:hidden [-ms-overflow-style:none] [scrollbar-width:none]"
    >
      <div className="mx-auto max-w-3xl min-w-0 w-full px-6 py-6">
        <div className="space-y-6 min-w-0">
          {/* Streaming indicator */}
          {streamingText && agentStatus === 'running' && (
            <div className="flex justify-start mb-6">
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

          {/* Messages */}
          {messages.length === 0 ? (
            <div className="flex items-center justify-center text-gray-400 text-sm py-20">
              {t('chat.startConversation')}
            </div>
          ) : (
            messages.map((msg, idx) => (
              <MessageItem
                key={msg.id}
                message={msg}
                isLast={idx === messages.length - 1}
                onToolClick={onToolClick}
              />
            ))
          )}

          {/* Processing indicator */}
          {agentStatus === 'running' && messages.length > 0 && messages[messages.length - 1]?.role === 'user' && !streamingText && (
            <div className="flex items-center gap-3 text-gray-400 text-sm animate-pulse pl-4">
              <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-100 to-white border border-blue-100 flex items-center justify-center">
                <div className="w-2 h-2 bg-blue-400 rounded-full animate-bounce"></div>
              </div>
              <span>{t('chat.thinking')}</span>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default ThreadContent
