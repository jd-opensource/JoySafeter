'use client'

import { Loader2, MessageSquare, Plus, Send } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'

import { ConversationView } from '@/components/threads/conversation-view'
import { ThreadList } from '@/components/threads/thread-list'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  useThreads,
  useThread,
  useThreadMessages,
  useCreateThread,
  useCreateMessage,
} from '@/hooks/queries/threads'
import { useWorkspaces } from '@/hooks/queries/workspaces'
import { useTranslation } from '@/lib/i18n'

interface AgentChatTabProps {
  agentId: string
  threadId?: string
}

export function AgentChatTab({ agentId, threadId }: AgentChatTabProps) {
  const { t } = useTranslation()
  const router = useRouter()

  const { data: workspaces = [] } = useWorkspaces()
  const personalWorkspace = workspaces.find((ws) => ws.type === 'personal')
  const workspaceId = personalWorkspace?.id || ''

  const { data: threads = [], isLoading: threadsLoading } = useThreads(agentId, workspaceId)
  const createThreadMutation = useCreateThread()

  // Thread detail
  const { data: thread, isLoading: threadLoading } = useThread(threadId || '', workspaceId, {
    enabled: Boolean(threadId),
  })
  const { data: messages = [], isLoading: messagesLoading } = useThreadMessages(
    threadId || '',
    workspaceId,
    { enabled: Boolean(threadId) },
  )
  const sendMutation = useCreateMessage()

  const [input, setInput] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleCreateThread = async () => {
    try {
      const newThread = await createThreadMutation.mutateAsync({
        agent_id: agentId,
        workspace_id: workspaceId,
      })
      router.push(`/agents/${agentId}?tab=chat&thread=${newThread.id}`)
    } catch (error) {
      console.error('Failed to create thread:', error)
    }
  }

  const handleSelectThread = (tid: string) => {
    router.push(`/agents/${agentId}?tab=chat&thread=${tid}`)
  }

  const handleSend = async () => {
    if (!input.trim() || !threadId) return
    try {
      await sendMutation.mutateAsync({
        threadId,
        workspaceId,
        role: 'user',
        content: { text: input },
      })
      setInput('')
    } catch (error) {
      console.error('Failed to send message:', error)
    }
  }

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="flex h-full">
      {/* Left panel: thread list */}
      <div className="flex w-72 flex-shrink-0 flex-col border-r border-[var(--border)] bg-[var(--surface-elevated)]">
        <div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-3">
          <h3 className="text-sm font-semibold text-[var(--text-primary)]">
            {t('agents.detail.tabs.chat')}
          </h3>
          <Button
            size="sm"
            variant="ghost"
            onClick={handleCreateThread}
            disabled={createThreadMutation.isPending}
            className="h-7 w-7 p-0"
          >
            {createThreadMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Plus className="h-4 w-4" />
            )}
          </Button>
        </div>
        <div className="flex-1 overflow-y-auto p-3">
          {threadsLoading ? (
            <div className="flex items-center gap-2 py-6 text-sm text-[var(--text-muted)]">
              <Loader2 className="h-4 w-4 animate-spin" />
              {t('common.loading')}
            </div>
          ) : (
            <ThreadList threads={threads} onSelect={handleSelectThread} />
          )}
        </div>
      </div>

      {/* Right panel: conversation or empty state */}
      <div className="flex flex-1 flex-col">
        {!threadId ? (
          <div className="flex h-full flex-col items-center justify-center gap-3">
            <MessageSquare className="h-12 w-12 text-[var(--text-muted)]" />
            <p className="text-sm text-[var(--text-muted)]">
              {t('agents.detail.startChat')}
            </p>
            <Button onClick={handleCreateThread} disabled={createThreadMutation.isPending}>
              {createThreadMutation.isPending ? (
                <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
              ) : (
                <Plus className="mr-1.5 h-4 w-4" />
              )}
              {t('chat.newChat')}
            </Button>
          </div>
        ) : threadLoading || messagesLoading ? (
          <div className="flex h-full items-center justify-center text-sm text-[var(--text-muted)]">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            {t('common.loading')}
          </div>
        ) : (
          <>
            {/* Thread header */}
            <div className="border-b border-[var(--border)] bg-[var(--surface-elevated)] px-6 py-3">
              <h2 className="text-sm font-medium text-[var(--text-primary)]">
                {thread?.title || t('execution.untitled')}
              </h2>
            </div>

            {/* Messages */}
            <div className="flex-1 overflow-y-auto px-6 py-4">
              <ConversationView messages={messages} />
              <div ref={messagesEndRef} />
            </div>

            {/* Input */}
            <div className="border-t border-[var(--border)] bg-[var(--surface-elevated)] px-6 py-4">
              <div className="flex gap-2">
                <Input
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyPress={handleKeyPress}
                  placeholder={t('chat.describeHelpNeeded')}
                  disabled={sendMutation.isPending}
                  className="flex-1"
                />
                <Button
                  onClick={handleSend}
                  disabled={!input.trim() || sendMutation.isPending}
                  className="gap-2"
                >
                  {sendMutation.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Send className="h-4 w-4" />
                  )}
                </Button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
