'use client'

import { Plus, Loader2, MessageSquare } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { useTranslation } from '@/lib/i18n'
import type { Thread } from '@/types/thread'

interface ThreadSidebarProps {
  threads: Thread[]
  activeThreadId?: string
  onSelect: (threadId: string) => void
  onCreate: () => void
  isLoading?: boolean
  isCreating?: boolean
}

export function ThreadSidebar({
  threads,
  activeThreadId,
  onSelect,
  onCreate,
  isLoading,
  isCreating,
}: ThreadSidebarProps) {
  const { t } = useTranslation()

  return (
    <div className="flex w-64 flex-shrink-0 flex-col border-r border-[var(--border)] bg-[var(--surface-elevated)]">
      <div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-3">
        <h3 className="text-sm font-semibold text-[var(--text-primary)]">
          {t('agents.detail.tabs.chat')}
        </h3>
        <Button
          size="sm"
          variant="ghost"
          onClick={onCreate}
          disabled={isCreating}
          className="h-7 w-7 p-0"
        >
          {isCreating ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Plus className="h-4 w-4" />
          )}
        </Button>
      </div>
      <div className="flex-1 overflow-y-auto p-2">
        {isLoading ? (
          <div className="flex items-center gap-2 py-6 text-sm text-[var(--text-muted)]">
            <Loader2 className="h-4 w-4 animate-spin" /> {t('common.loading')}
          </div>
        ) : threads.length === 0 ? (
          <p className="py-6 text-center text-xs text-[var(--text-muted)]">
            No threads yet
          </p>
        ) : (
          threads.map((thread) => (
            <button
              key={thread.id}
              type="button"
              onClick={() => onSelect(thread.id)}
              className={cn(
                'flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm transition-colors',
                thread.id === activeThreadId
                  ? 'bg-[var(--surface-3)] text-[var(--text-primary)]'
                  : 'text-[var(--text-secondary)] hover:bg-[var(--surface-2)]',
              )}
            >
              <MessageSquare className="h-3.5 w-3.5 flex-shrink-0" />
              <span className="truncate">
                {thread.title || 'Untitled'}
              </span>
            </button>
          ))
        )}
      </div>
    </div>
  )
}
