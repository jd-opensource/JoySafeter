'use client'

import { Bot, User, Wrench, Info } from 'lucide-react'

import type { ThreadMessage } from '@/types/thread'
import { cn } from '@/lib/utils'

interface ConversationViewProps {
  messages: ThreadMessage[]
}

export function ConversationView({ messages }: ConversationViewProps) {
  if (messages.length === 0) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-sm text-[var(--text-muted)]">No messages yet. Start the conversation!</p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {messages.map((message) => {
        const isUser = message.role === 'user'
        const isAssistant = message.role === 'assistant'
        const isTool = message.role === 'tool'
        const isSystem = message.role === 'system'

        // Extract text content
        const text = typeof message.content === 'object' && message.content !== null
          ? (message.content as { text?: string }).text || JSON.stringify(message.content)
          : String(message.content)

        if (isSystem || isTool) {
          return (
            <div key={message.id} className="flex justify-center">
              <div className="flex max-w-md items-center gap-2 rounded-lg bg-[var(--surface-2)] px-3 py-2 text-xs text-[var(--text-muted)]">
                {isTool ? (
                  <Wrench className="h-3 w-3" />
                ) : (
                  <Info className="h-3 w-3" />
                )}
                <span>{text}</span>
              </div>
            </div>
          )
        }

        return (
          <div
            key={message.id}
            className={cn(
              'flex',
              isUser ? 'justify-end' : 'justify-start',
            )}
          >
            <div
              className={cn(
                'flex max-w-[70%] gap-3 rounded-lg px-4 py-3',
                isUser
                  ? 'bg-[var(--skill-brand-600)] text-white'
                  : 'bg-[var(--surface-2)] text-[var(--text-primary)]',
              )}
            >
              {isAssistant && (
                <Bot className="mt-0.5 h-4 w-4 flex-shrink-0 text-[var(--text-muted)]" />
              )}
              <div className="min-w-0 flex-1">
                <p className="whitespace-pre-wrap break-words text-sm">{text}</p>
                <span className="mt-1 block text-xs opacity-70">
                  {new Date(message.created_at).toLocaleTimeString()}
                </span>
              </div>
              {isUser && (
                <User className="mt-0.5 h-4 w-4 flex-shrink-0" />
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
