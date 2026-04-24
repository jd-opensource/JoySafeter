'use client'

import { Bot, User, Wrench, Info, Loader2, CheckCircle, ExternalLink } from 'lucide-react'
import ReactMarkdown from 'react-markdown'

import type { ThreadMessage } from '@/types/thread'
import { cn } from '@/lib/utils'
import { useTranslation } from '@/lib/i18n'

interface ConversationViewProps {
  messages: ThreadMessage[]
  /** Currently running execution — shows spinner on its badge */
  activeExecutionId?: string | null
  /** Click handler for execution badges */
  onExecutionClick?: (executionId: string) => void
}

function extractText(content: Record<string, unknown>): string {
  if (typeof content === 'string') return content
  if (content && typeof content === 'object' && 'text' in content) {
    return String(content.text ?? '')
  }
  return JSON.stringify(content)
}

function ExecutionBadge({
  message,
  isActive,
  onClick,
}: {
  message: ThreadMessage
  isActive: boolean
  onClick?: (executionId: string) => void
}) {
  if (!message.execution_id) return null

  return (
    <button
      type="button"
      onClick={() => onClick?.(message.execution_id!)}
      className={cn(
        'mt-1.5 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium transition-colors',
        isActive
          ? 'bg-[var(--status-success)]/15 text-[var(--status-success)]'
          : 'bg-[var(--surface-3)] text-[var(--text-muted)] hover:bg-[var(--surface-4)]',
      )}
    >
      {isActive ? (
        <Loader2 className="h-2.5 w-2.5 animate-spin" />
      ) : (
        <ExternalLink className="h-2.5 w-2.5" />
      )}
      <span>{isActive ? 'Running' : 'View execution'}</span>
    </button>
  )
}

export function ConversationView({
  messages,
  activeExecutionId,
  onExecutionClick,
}: ConversationViewProps) {
  const { t } = useTranslation()

  if (messages.length === 0) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-sm text-[var(--text-muted)]">{t('chat.noMessages')}</p>
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
        const text = extractText(message.content)

        if (isSystem || isTool) {
          return (
            <div key={message.id} className="flex justify-center">
              <div className="flex max-w-md items-center gap-2 rounded-lg bg-[var(--surface-2)] px-3 py-2 text-xs text-[var(--text-muted)]">
                {isTool ? <Wrench className="h-3 w-3" /> : <Info className="h-3 w-3" />}
                <span>{text}</span>
              </div>
            </div>
          )
        }

        const badgeActive = !!(
          activeExecutionId &&
          message.execution_id === activeExecutionId
        )

        return (
          <div
            key={message.id}
            className={cn('flex', isUser ? 'justify-end' : 'justify-start')}
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
                {isAssistant ? (
                  <div className="prose prose-sm max-w-none break-words text-sm text-[var(--text-primary)] prose-p:my-1 prose-pre:my-2 prose-pre:rounded prose-pre:bg-[var(--surface-3)] prose-pre:p-2 prose-code:rounded prose-code:bg-[var(--surface-3)] prose-code:px-1 prose-code:text-xs">
                    <ReactMarkdown>{text}</ReactMarkdown>
                  </div>
                ) : (
                  <p className="whitespace-pre-wrap break-words text-sm">{text}</p>
                )}
                <div className="flex items-center gap-2">
                  <span className="mt-1 block text-xs opacity-70">
                    {new Date(message.created_at).toLocaleTimeString()}
                  </span>
                  {isAssistant && (
                    <ExecutionBadge
                      message={message}
                      isActive={badgeActive}
                      onClick={onExecutionClick}
                    />
                  )}
                </div>
              </div>
              {isUser && <User className="mt-0.5 h-4 w-4 flex-shrink-0" />}
            </div>
          </div>
        )
      })}
    </div>
  )
}
