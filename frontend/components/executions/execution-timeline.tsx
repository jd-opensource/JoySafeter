'use client'

import { CheckCircle, Loader2, Pause, Play, XCircle } from 'lucide-react'
import { useEffect, useMemo, useRef } from 'react'

import { useExecution, useExecutionEvents } from '@/hooks/queries/executions'
import { cn } from '@/lib/utils'

import { ExecutionEventItem } from './execution-event'
import { MessageInput } from './message-input'

const STATUS_CONFIG: Record<string, { icon: React.ElementType; label: string; color: string }> = {
  queued: { icon: Pause, label: 'Queued', color: 'text-gray-500' },
  dispatched: { icon: Play, label: 'Dispatched', color: 'text-blue-500' },
  running: { icon: Loader2, label: 'Running', color: 'text-green-600' },
  interrupt_wait: { icon: Pause, label: 'Waiting', color: 'text-yellow-600' },
  approval_wait: { icon: Pause, label: 'Approval Wait', color: 'text-yellow-600' },
  completed: { icon: CheckCircle, label: 'Completed', color: 'text-green-600' },
  failed: { icon: XCircle, label: 'Failed', color: 'text-red-600' },
  cancelled: { icon: XCircle, label: 'Cancelled', color: 'text-gray-500' },
}

interface ExecutionTimelineProps {
  executionId: string
  workspaceId: string
  compact?: boolean
}

export function ExecutionTimeline({ executionId, workspaceId, compact }: ExecutionTimelineProps) {
  const { data: execution } = useExecution(executionId, workspaceId)
  const isActive = execution
    ? ['queued', 'dispatched', 'running', 'interrupt_wait', 'approval_wait'].includes(execution.status)
    : false

  const { data: eventsPage } = useExecutionEvents(executionId, workspaceId, undefined, {
    enabled: Boolean(executionId),
  })

  const events = useMemo(() => eventsPage?.events ?? [], [eventsPage])
  const scrollRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom on new events
  useEffect(() => {
    const el = scrollRef.current
    if (el) {
      el.scrollTop = el.scrollHeight
    }
  }, [events.length])

  const statusConfig = STATUS_CONFIG[execution?.status ?? 'queued'] ?? STATUS_CONFIG.queued
  const StatusIcon = statusConfig.icon

  const duration = useMemo(() => {
    if (!execution?.started_at) return null
    const start = new Date(execution.started_at).getTime()
    const end = execution.finished_at ? new Date(execution.finished_at).getTime() : Date.now()
    const secs = Math.floor((end - start) / 1000)
    const m = Math.floor(secs / 60)
    const s = secs % 60
    return `${m}m ${s.toString().padStart(2, '0')}s`
  }, [execution?.started_at, execution?.finished_at])

  const toolCount = useMemo(
    () => events.filter((e) => e.event_type === 'tool_use').length,
    [events],
  )

  const handleSendMessage = (message: string) => {
    // For now, log the message. Full injection requires a service endpoint.
    console.log('send-message-to-execution', executionId, message)
  }

  return (
    <div className={cn('flex flex-col', compact ? 'h-80' : 'h-full')}>
      {/* Status header */}
      <div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-2.5">
        <div className="flex items-center gap-2">
          <StatusIcon
            className={cn(
              'h-4 w-4',
              statusConfig.color,
              execution?.status === 'running' && 'animate-spin',
            )}
          />
          <span className={cn('text-sm font-medium', statusConfig.color)}>
            {statusConfig.label}
          </span>
          {duration && (
            <span className="text-xs text-[var(--text-muted)]">
              Duration: {duration}
            </span>
          )}
        </div>
        {toolCount > 0 && (
          <span className="text-xs text-[var(--text-muted)]">
            Tools: {toolCount} call{toolCount !== 1 ? 's' : ''}
          </span>
        )}
      </div>

      {/* Events list */}
      <div ref={scrollRef} className="flex-1 space-y-1 overflow-y-auto py-2">
        {events.length === 0 ? (
          <p className="py-8 text-center text-sm text-[var(--text-muted)]">
            {isActive ? 'Waiting for events...' : 'No events'}
          </p>
        ) : (
          events.map((event) => <ExecutionEventItem key={event.id} event={event} />)
        )}
      </div>

      {/* Message input */}
      <MessageInput disabled={!isActive} onSend={handleSendMessage} />
    </div>
  )
}
