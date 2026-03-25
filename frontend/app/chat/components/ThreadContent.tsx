'use client'

import { MessageSquare } from 'lucide-react'
import React, { useMemo } from 'react'


import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'

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
      <div className="mx-auto w-full min-w-0 max-w-3xl px-6 py-6">
        <div className="min-w-0 space-y-6">
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
            <div className="group mb-6 flex justify-start duration-200 animate-in fade-in">
              <div className="mr-4 mt-0.5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-[var(--brand-500)] to-[var(--brand-700)] shadow-md">
                <div className="h-3 w-3 animate-pulse rounded-full bg-white" />
              </div>
              <div className="min-w-[50%] max-w-[85%]">
                <div className="mb-2 flex items-center gap-2">
                  <span className="rounded border border-[var(--brand-200)] bg-[var(--brand-50)] px-1.5 py-0.5 text-[10px] text-[var(--brand-500)]">
                    AI
                  </span>
                </div>
                <div className="prose prose-sm max-w-none leading-7 text-[var(--text-primary)]">
                  <span className="mr-1 inline-block h-4 w-1.5 animate-pulse rounded-full bg-[var(--brand-500)] align-middle" />
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
            <div className="mb-6 flex justify-start duration-200 animate-in fade-in">
              <div
                className={cn(
                  'flex min-w-0 max-w-[85%] items-center gap-4 rounded-2xl px-4 py-3',
                  'border border-[var(--border)] bg-[var(--surface-1)]/90 shadow-sm backdrop-blur-sm',
                )}
              >
                <div className="relative flex h-10 w-10 flex-shrink-0 items-center justify-center overflow-hidden rounded-full">
                  <div className="absolute inset-0 h-10 w-10 animate-pulse rounded-full bg-[var(--brand-400)]/20" />
                  <div className="relative flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-[var(--brand-500)] to-[var(--brand-700)] shadow-md">
                    <div className="flex gap-0.5">
                      <span className="h-2 w-2 animate-bounce rounded-full bg-white [animation-delay:0ms]" />
                      <span className="h-2 w-2 animate-bounce rounded-full bg-white [animation-delay:150ms]" />
                      <span className="h-2 w-2 animate-bounce rounded-full bg-white [animation-delay:300ms]" />
                    </div>
                  </div>
                </div>
                <div className="flex min-w-0 flex-col gap-0.5">
                  <span className="animate-pulse text-sm font-medium text-[var(--text-secondary)]">
                    {t('chat.thinking')}
                  </span>
                  {currentNodeLabel && (
                    <span className="truncate text-xs text-[var(--text-muted)]" title={currentNodeLabel}>
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
