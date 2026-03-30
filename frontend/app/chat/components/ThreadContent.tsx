'use client'

import { Bot, MessageSquare } from 'lucide-react'
import React, { useMemo } from 'react'


import { useTranslation } from '@/lib/i18n'

import { CopyAction } from '../shared/ActionBar'
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
      className="h-full overflow-y-auto bg-[var(--bg)] [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
    >
      <div className="mx-auto w-full min-w-0 max-w-3xl p-4">
        <div className="min-w-0 space-y-4">
          {/* Messages - history on top for waterfall layout */}
          {messagesToRender.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-3 py-20">
              <div className="rounded-full bg-[var(--brand-50)] p-4">
                <MessageSquare size={24} className="text-[var(--brand-500)]" />
              </div>
              <p className="text-base font-medium text-[var(--text-secondary)]">{t('chat.startConversation')}</p>
              <p className="text-sm text-[var(--text-muted)]">{t('chat.askAnything', { defaultValue: 'Ask anything to get started' })}</p>
            </div>
          ) : (
            messagesToRender.map((msg, idx) => (
              <MessageItem
                key={msg.id}
                message={msg}
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
            <div className="group flex w-full gap-3 justify-start duration-200 animate-in fade-in">
              <div className="mt-0.5 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full bg-[var(--brand-50)]">
                <Bot size={14} className="text-[var(--brand-500)]" />
              </div>
              <div className="max-w-[85%] rounded-2xl rounded-bl-md border border-[var(--border-muted)] bg-[var(--surface-2)] px-4 py-2.5 text-sm leading-relaxed text-[var(--text-primary)]">
                <div className="prose prose-sm max-w-none prose-headings:my-2 prose-p:my-1 prose-ol:my-1 prose-ul:my-1 prose-li:my-0.5">
                  <span className="mr-1 inline-block h-4 w-1.5 animate-pulse rounded-sm bg-[var(--brand-500)] align-middle" />
                  {streamingText}
                </div>
                <div className="mt-1 opacity-0 transition-opacity group-hover:opacity-100">
                  <CopyAction text={streamingText} />
                </div>
              </div>
            </div>
          )}

          {/* Processing indicator - thinking at bottom */}
          {agentStatus === 'running' && messages.length > 0 && !streamingText && (
            <div className="flex w-full gap-3 justify-start duration-200 animate-in fade-in">
              <div className="mt-0.5 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full bg-[var(--brand-50)]">
                <div className="flex gap-0.5">
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-[var(--brand-500)] [animation-delay:0ms]" />
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-[var(--brand-500)] [animation-delay:150ms]" />
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-[var(--brand-500)] [animation-delay:300ms]" />
                </div>
              </div>
              <div className="flex items-center gap-2 rounded-2xl rounded-bl-md border border-[var(--border-muted)] bg-[var(--surface-2)] px-4 py-2.5">
                <span className="animate-pulse text-sm text-[var(--text-secondary)]">
                  {t('chat.thinking')}
                </span>
                {currentNodeLabel && (
                  <span className="truncate text-xs text-[var(--text-muted)]" title={currentNodeLabel}>
                    {currentNodeLabel}
                  </span>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
