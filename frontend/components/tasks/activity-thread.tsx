'use client'

import { AlertCircle, Bot, CornerDownRight, Loader2, MessageSquare, Send, User } from 'lucide-react'
import { useMemo, useRef, useState, useEffect, useCallback } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useTaskActivities, useCreateTaskActivity } from '@/hooks/queries/taskActivities'
import { useAgents, useAgentNameMap } from '@/hooks/queries/agents'
import { cn } from '@/lib/utils'
import { formatRelativeTime } from '@/lib/utils/runHelpers'
import type { TaskActivity } from '@/types/task-activities'

const MENTION_RE = /\[@([^\]]*)\]\(mention:\/\/(agent|member)\/[^)]+\)/g

function renderContentWithMentions(content: string) {
  const parts: (string | React.ReactElement)[] = []
  let lastIndex = 0

  for (const match of content.matchAll(MENTION_RE)) {
    if (match.index! > lastIndex) {
      parts.push(content.slice(lastIndex, match.index))
    }
    parts.push(
      <span
        key={match.index}
        className="bg-[var(--brand-400)]/10 rounded px-1 font-medium text-[var(--brand-400)]"
      >
        @{match[1]}
      </span>,
    )
    lastIndex = match.index! + match[0].length
  }

  if (lastIndex < content.length) {
    parts.push(content.slice(lastIndex))
  }

  return parts.length > 0 ? parts : content
}

interface ActivityThreadProps {
  taskId: string
  workspaceId: string
}

export function ActivityThread({ taskId, workspaceId }: ActivityThreadProps) {
  const { data, isLoading, hasNextPage, fetchNextPage, isFetchingNextPage } = useTaskActivities(
    taskId,
    workspaceId,
  )

  const createActivity = useCreateTaskActivity()
  const [newContent, setNewContent] = useState('')
  const [replyTo, setReplyTo] = useState<string | null>(null)
  const [mentionQuery, setMentionQuery] = useState<string | null>(null)
  const [mentionStart, setMentionStart] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const { data: agents = [] } = useAgents(workspaceId, { enabled: Boolean(workspaceId) })
  const agentNameMap = useAgentNameMap(workspaceId)
  const bottomRef = useRef<HTMLDivElement>(null)
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const isAtBottomRef = useRef(true)

  const allActivities = useMemo(() => {
    if (!data?.pages) return []
    return data.pages.flatMap((page) => page.items)
  }, [data])

  // Group into threads: root activities + their replies
  const threads = useMemo(() => {
    const roots: TaskActivity[] = []
    const repliesByParent: Record<string, TaskActivity[]> = {}

    for (const a of allActivities) {
      if (a.parent_activity_id) {
        const parentId = a.parent_activity_id
        if (!repliesByParent[parentId]) repliesByParent[parentId] = []
        repliesByParent[parentId].push(a)
      } else {
        roots.push(a)
      }
    }
    return roots.map((root) => ({
      root,
      replies: repliesByParent[root.id] || [],
    }))
  }, [allActivities])

  const handleScroll = useCallback(() => {
    const el = scrollContainerRef.current
    if (!el) return
    isAtBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40
  }, [])

  useEffect(() => {
    if (isAtBottomRef.current) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [allActivities.length])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = newContent.trim()
    if (!trimmed) return
    setMentionQuery(null)
    createActivity.mutate(
      {
        taskId,
        workspaceId,
        content: trimmed,
        parent_activity_id: replyTo ?? undefined,
      },
      {
        onSuccess: () => {
          setNewContent('')
          setReplyTo(null)
        },
      },
    )
  }

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value
    setNewContent(value)

    const cursorPos = e.target.selectionStart ?? value.length
    const textBeforeCursor = value.slice(0, cursorPos)
    const atMatch = textBeforeCursor.match(/@(\w*)$/)
    if (atMatch) {
      setMentionQuery(atMatch[1].toLowerCase())
      setMentionStart(cursorPos - atMatch[0].length)
    } else {
      setMentionQuery(null)
    }
  }

  const handleSelectAgent = (agentId: string, agentName: string) => {
    const before = newContent.slice(0, mentionStart)
    const after = newContent.slice(mentionStart + (mentionQuery?.length ?? 0) + 1)
    const mention = `[@${agentName}](mention://agent/${agentId})`
    setNewContent(before + mention + ' ' + after)
    setMentionQuery(null)
    inputRef.current?.focus()
  }

  const filteredAgents = useMemo(() => {
    if (mentionQuery === null) return []
    return agents.filter((a) => a.name.toLowerCase().includes(mentionQuery))
  }, [agents, mentionQuery])

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-6">
        <Loader2 className="h-4 w-4 animate-spin text-[var(--text-muted)]" />
      </div>
    )
  }

  return (
    <div ref={scrollContainerRef} onScroll={handleScroll} className="flex flex-col">
      {/* Load more */}
      {hasNextPage && (
        <button
          type="button"
          onClick={() => fetchNextPage()}
          disabled={isFetchingNextPage}
          className="mb-2 text-xs text-[var(--brand-400)] hover:underline disabled:opacity-50"
        >
          {isFetchingNextPage ? 'Loading...' : 'Load earlier activity'}
        </button>
      )}

      {/* Empty state */}
      {threads.length === 0 && (
        <p className="py-4 text-center text-xs text-[var(--text-muted)]">No activity yet</p>
      )}

      {/* Activity threads */}
      <div className="space-y-3">
        {threads.map(({ root, replies }) => (
          <div key={root.id}>
            <ActivityItem
              activity={root}
              onReply={() => setReplyTo(root.id)}
              agentNameMap={agentNameMap}
            />
            {replies.map((reply) => (
              <div key={reply.id} className="ml-6 mt-1.5">
                <ActivityItem activity={reply} isReply agentNameMap={agentNameMap} />
              </div>
            ))}
          </div>
        ))}
      </div>

      <div ref={bottomRef} />

      {/* Input */}
      <form onSubmit={handleSubmit} className="relative mt-3 flex flex-col gap-2">
        {replyTo && (
          <div className="flex items-center gap-1 text-xs text-[var(--text-muted)]">
            <CornerDownRight className="h-3 w-3" />
            <span>Replying to comment</span>
            <button
              type="button"
              onClick={() => setReplyTo(null)}
              className="ml-1 text-[var(--brand-400)] hover:underline"
            >
              Cancel
            </button>
          </div>
        )}
        {/* @mention dropdown */}
        {filteredAgents.length > 0 && (
          <div className="absolute bottom-full left-0 mb-1 w-56 rounded-md border border-[var(--border)] bg-[var(--surface-elevated)] py-1 shadow-lg">
            {filteredAgents.slice(0, 5).map((agent) => (
              <button
                key={agent.id}
                type="button"
                onClick={() => handleSelectAgent(agent.id, agent.name)}
                className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-[var(--surface-3)]"
              >
                <Bot className="h-3.5 w-3.5 text-[var(--brand-400)]" />
                <span className="text-[var(--text-primary)]">{agent.name}</span>
              </button>
            ))}
          </div>
        )}
        <div className="flex items-center gap-2">
          <Input
            ref={inputRef}
            value={newContent}
            onChange={handleInputChange}
            placeholder={
              replyTo
                ? 'Write a reply... (@ to mention agent)'
                : 'Write a comment... (@ to mention agent)'
            }
            className="flex-1 text-sm"
          />
          <Button
            type="submit"
            size="icon"
            disabled={!newContent.trim() || createActivity.isPending}
          >
            {createActivity.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Send className="h-4 w-4" />
            )}
          </Button>
        </div>
      </form>
    </div>
  )
}

// ---- Single activity item ----

function ActivityItem({
  activity,
  onReply,
  isReply,
  agentNameMap,
}: {
  activity: TaskActivity
  onReply?: () => void
  isReply?: boolean
  agentNameMap?: Record<string, string>
}) {
  const isAgent = activity.author_type === 'agent'
  const isSystem = activity.type === 'system'

  return (
    <div
      className={cn(
        'rounded-lg px-3 py-2',
        isSystem
          ? 'border border-[var(--status-error-bg)] bg-[var(--status-error-bg)]'
          : 'border border-[var(--border)] bg-[var(--surface-3)]',
      )}
    >
      <div className="flex items-center gap-1.5">
        {isAgent ? (
          <Bot className="h-3.5 w-3.5 text-[var(--brand-400)]" />
        ) : (
          <User className="h-3.5 w-3.5 text-[var(--text-muted)]" />
        )}
        <span className="text-xs font-medium text-[var(--text-secondary)]">
          {isAgent ? (agentNameMap?.[activity.author_id] ?? 'Agent') : 'You'}
        </span>
        {isSystem && (
          <span className="flex items-center gap-0.5 text-xs text-[var(--status-error)]">
            <AlertCircle className="h-3 w-3" />
            System
          </span>
        )}
        {activity.type === 'progress_update' && (
          <span className="text-xs text-[var(--status-success)]">Update</span>
        )}
        <span className="ml-auto text-[10px] text-[var(--text-muted)]">
          {formatRelativeTime(activity.created_at)}
        </span>
      </div>
      <p
        className={cn(
          'mt-1 whitespace-pre-wrap text-sm leading-relaxed',
          isSystem ? 'text-[var(--status-error)]' : 'text-[var(--text-primary)]',
        )}
      >
        {renderContentWithMentions(activity.content)}
      </p>
      {onReply && !isReply && (
        <button
          type="button"
          onClick={onReply}
          className="mt-1 flex items-center gap-1 text-[10px] text-[var(--text-muted)] hover:text-[var(--brand-400)]"
        >
          <MessageSquare className="h-3 w-3" />
          Reply
        </button>
      )}
    </div>
  )
}
