'use client'

import { useEffect, useMemo, useRef } from 'react'
import { Loader2 } from 'lucide-react'
import { ChatEventBubble } from './ChatEventBubble'
import { useTranslation } from '@/lib/i18n'
import type { ThreadEvent } from '@/types/thread'

interface ChatHistoryProps {
  events: ThreadEvent[]
  isLoading?: boolean
  isExecuting?: boolean
}

const IGNORED_EVENTS = new Set([
  'execution_status_change',
  'approval_requested',
  'approval_resolved',
])

export function ChatHistory({ events, isLoading, isExecuting }: ChatHistoryProps) {
  const { t } = useTranslation()
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [events.length])

  const visible = useMemo(
    () =>
      events.filter(
        (e) =>
          !IGNORED_EVENTS.has(e.event_type) &&
          !e.event_type.startsWith('copilot_'),
      ),
    [events],
  )

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-[var(--text-muted)]" />
      </div>
    )
  }

  if (visible.length === 0) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-sm text-[var(--text-muted)]">
          {t('chat.noMessages')}
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-3 px-6 py-4">
      {visible.map((event) => (
        <ChatEventBubble key={event.id} event={event} />
      ))}
      {isExecuting && (
        <div className="flex items-center gap-2 py-2">
          <Loader2 className="h-4 w-4 animate-spin text-[var(--text-muted)]" />
          <span className="text-xs text-[var(--text-muted)]">Agent is working...</span>
        </div>
      )}
      <div ref={endRef} />
    </div>
  )
}
