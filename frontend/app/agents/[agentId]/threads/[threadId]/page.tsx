'use client'

import { Loader2, Send } from 'lucide-react'
import { useParams } from 'next/navigation'
import { useEffect, useRef, useState } from 'react'

import { ConversationView } from '@/components/threads/conversation-view'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useThread, useThreadMessages, useCreateMessage } from '@/hooks/queries/threads'
import { useWorkspaces } from '@/hooks/queries/workspaces'

export default function ThreadDetailPage() {
  const params = useParams()
  const threadId = params.threadId as string
  const agentId = params.agentId as string

  const { data: workspaces = [] } = useWorkspaces()
  const personalWorkspace = workspaces.find((ws) => ws.type === 'personal')
  const workspaceId = personalWorkspace?.id || ''

  const { data: thread, isLoading: threadLoading } = useThread(threadId, workspaceId)
  const { data: messages = [], isLoading: messagesLoading } = useThreadMessages(
    threadId,
    workspaceId,
  )
  const sendMutation = useCreateMessage()

  const [input, setInput] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  const handleSend = async () => {
    if (!input.trim()) return

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

  if (threadLoading || messagesLoading) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-[var(--text-muted)]">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        加载中...
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-[var(--border)] bg-[var(--surface-elevated)] px-8 py-3">
        <h2 className="text-sm font-medium text-[var(--text-primary)]">
          {thread?.title || '未命名对话'}
        </h2>
      </div>

      <div className="flex-1 overflow-y-auto px-8 py-4">
        <ConversationView messages={messages} />
        <div ref={messagesEndRef} />
      </div>

      <div className="border-t border-[var(--border)] bg-[var(--surface-elevated)] px-8 py-4">
        <div className="flex gap-2">
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyPress={handleKeyPress}
            placeholder="输入消息..."
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
    </div>
  )
}
