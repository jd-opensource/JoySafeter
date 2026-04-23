'use client'

import { MessageSquare } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { useTranslation } from '@/lib/i18n'
import type { Thread } from '@/types/thread'

interface ThreadListProps {
  threads: Thread[]
  onSelect: (threadId: string) => void
}

export function ThreadList({ threads, onSelect }: ThreadListProps) {
  const { t } = useTranslation()

  if (threads.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center">
        <MessageSquare className="mb-3 h-12 w-12 text-[var(--text-muted)]" />
        <p className="text-sm text-[var(--text-muted)]">{t('chat.noChats')}</p>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {threads.map((thread) => (
        <Card
          key={thread.id}
          className="cursor-pointer border-[var(--border)] bg-[var(--surface-1)] p-4 transition-colors hover:bg-[var(--surface-2)]"
          onClick={() => onSelect(thread.id)}
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <MessageSquare className="h-4 w-4 text-[var(--text-muted)]" />
              <span className="text-sm font-medium text-[var(--text-primary)]">
                {thread.title || t('chat.untitled')}
              </span>
              <Badge variant={thread.status === 'active' ? 'default' : 'secondary'}>
                {t(`chat.status.${thread.status}`)}
              </Badge>
            </div>
            <span className="text-xs text-[var(--text-muted)]">
              {new Date(thread.created_at).toLocaleDateString()}
            </span>
          </div>
        </Card>
      ))}
    </div>
  )
}
