'use client'

import { useCallback } from 'react'
import { MessageSquare, Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ThreadSidebar } from './ThreadSidebar'
import { ChatHistory } from './ChatHistory'
import { ChatInput } from './ChatInput'
import { useThreads, useCreateThread } from '@/hooks/queries/threads'
import { useThreadEvents } from '@/hooks/use-thread-events'
import { useChatSend } from '@/hooks/use-chat-send'
import { useChatStream } from '@/hooks/use-chat-stream'
import { cn } from '@/lib/utils'
import { useTranslation } from '@/lib/i18n'

interface ChatPanelProps {
  agentId: string
  projectId: string
  threadId?: string
  onThreadChange?: (id: string) => void
  showThreadSidebar?: boolean
  className?: string
}

export function ChatPanel({
  agentId,
  projectId,
  threadId,
  onThreadChange,
  showThreadSidebar = true,
  className,
}: ChatPanelProps) {
  const { t } = useTranslation()
  const { data: threads = [], isLoading: threadsLoading } = useThreads(agentId, projectId)
  const createThread = useCreateThread()

  const { data: eventsData, isLoading: eventsLoading } = useThreadEvents(
    threadId || '',
    projectId,
    { enabled: Boolean(threadId) },
  )

  const { send, isSending, executionId } = useChatSend(threadId || '', projectId)
  const { isExecuting } = useChatStream(executionId, threadId || '', projectId)

  const handleCreateThread = useCallback(async () => {
    const thread = await createThread.mutateAsync({
      agent_id: agentId,
    })
    onThreadChange?.(thread.id)
  }, [agentId, createThread, onThreadChange])

  const handleSend = useCallback(
    (message: string, files: File[]) => {
      send(message, files)
    },
    [send],
  )

  return (
    <div className={cn('flex h-full', className)}>
      {showThreadSidebar && (
        <ThreadSidebar
          threads={threads}
          activeThreadId={threadId}
          onSelect={(id) => onThreadChange?.(id)}
          onCreate={handleCreateThread}
          isLoading={threadsLoading}
          isCreating={createThread.isPending}
        />
      )}

      <div className="flex flex-1 flex-col">
        {!threadId ? (
          <div className="flex h-full flex-col items-center justify-center gap-3">
            <MessageSquare className="h-12 w-12 text-[var(--text-muted)]" />
            <p className="text-sm text-[var(--text-muted)]">{t('agents.detail.startChat')}</p>
            <Button onClick={handleCreateThread} disabled={createThread.isPending}>
              <Plus className="mr-1.5 h-4 w-4" /> {t('chat.newChat')}
            </Button>
          </div>
        ) : (
          <>
            <div className="flex-1 overflow-y-auto">
              <ChatHistory
                events={eventsData?.events ?? []}
                isLoading={eventsLoading}
                isExecuting={isExecuting}
              />
            </div>
            <ChatInput onSend={handleSend} disabled={isSending || isExecuting} />
          </>
        )}
      </div>
    </div>
  )
}
