'use client'

import { AlertCircle, CheckCircle, Loader2, Pause, Play, RefreshCw, XCircle } from 'lucide-react'
import { useEffect, useMemo, useRef } from 'react'

import { Button } from '@/components/ui/button'
import { useExecution, useExecutionEvents } from '@/hooks/queries/executions'
import { useExecutionStream } from '@/hooks/use-execution-stream'
import { cn } from '@/lib/utils'

import { executionService } from '@/services/executionService'

import { ExecutionEventItem } from './execution-event'
import { MessageInput } from './message-input'

const STATUS_CONFIG: Record<string, { icon: React.ElementType; label: string; color: string }> = {
  queued: { icon: Pause, label: 'Queued', color: 'text-[var(--text-muted)]' },
  dispatched: { icon: Play, label: 'Dispatched', color: 'text-[var(--brand-400)]' },
  running: { icon: Loader2, label: 'Running', color: 'text-[var(--status-success)]' },
  interrupt_wait: { icon: Pause, label: 'Waiting', color: 'text-[var(--status-warning)]' },
  approval_wait: { icon: Pause, label: 'Approval Wait', color: 'text-[var(--status-warning)]' },
  completed: { icon: CheckCircle, label: 'Completed', color: 'text-[var(--status-success)]' },
  failed: { icon: XCircle, label: 'Failed', color: 'text-[var(--status-error)]' },
  cancelled: { icon: XCircle, label: 'Cancelled', color: 'text-[var(--text-muted)]' },
}

const ACTIVE_STATUSES = ['queued', 'dispatched', 'running', 'interrupt_wait', 'approval_wait']

interface ExecutionTimelineProps {
  executionId: string
  workspaceId: string
  compact?: boolean
}

export function ExecutionTimeline({ executionId, workspaceId, compact }: ExecutionTimelineProps) {
  const { data: execution, isLoading: isExecLoading, error: execError, refetch: refetchExec } = useExecution(executionId, workspaceId)
  const isActive = execution ? ACTIVE_STATUSES.includes(execution.status) : false

  // WebSocket stream — primary data source
  const {
    events: wsEvents,
    status: wsStatus,
    isConnected,
    wsFailed,
  } = useExecutionStream({ executionId, enabled: Boolean(executionId) })

  // Polling fallback — only enabled when WS fails
  const {
    data: eventsPage,
    isLoading: isEventsLoading,
    error: eventsError,
    refetch: refetchEvents,
  } = useExecutionEvents(executionId, workspaceId, undefined, {
    enabled: Boolean(executionId) && wsFailed,
  })

  // Use WS events when connected, fall back to polling data
  const events = useMemo(() => {
    if (!wsFailed && wsEvents.length > 0) return wsEvents
    return eventsPage?.events ?? wsEvents
  }, [wsFailed, wsEvents, eventsPage])

  const currentStatus = wsStatus ?? execution?.status ?? 'queued'

  const scrollRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom on new events
  useEffect(() => {
    const el = scrollRef.current
    if (el) {
      el.scrollTop = el.scrollHeight
    }
  }, [events.length])

  const statusConfig = STATUS_CONFIG[currentStatus] ?? STATUS_CONFIG.queued
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

  const handleSendMessage = async (message: string) => {
    try {
      await executionService.injectMessage(executionId, message)
    } catch (err) {
      console.error('Failed to inject message', err)
    }
  }

  const handleApprove = async (_eventId: string) => {
    try {
      await executionService.approveAction(executionId, true)
    } catch (err) {
      console.error('Failed to approve action', err)
    }
  }

  const handleReject = async (_eventId: string) => {
    try {
      await executionService.approveAction(executionId, false)
    } catch (err) {
      console.error('Failed to reject action', err)
    }
  }

  const handleRetry = () => {
    void refetchExec()
    void refetchEvents()
  }

  // Error state
  if (execError || eventsError) {
    return (
      <div className={cn('flex flex-col items-center justify-center gap-3', compact ? 'h-80' : 'h-full')}>
        <AlertCircle className="h-8 w-8 text-[var(--status-error)]" />
        <p className="text-sm text-[var(--text-secondary)]">Failed to load execution data</p>
        <Button variant="outline" size="sm" onClick={handleRetry} className="gap-1.5">
          <RefreshCw className="h-3.5 w-3.5" />
          Retry
        </Button>
      </div>
    )
  }

  // Loading state
  if (isExecLoading && !execution) {
    return (
      <div className={cn('flex flex-col items-center justify-center gap-2', compact ? 'h-80' : 'h-full')}>
        <Loader2 className="h-6 w-6 animate-spin text-[var(--text-muted)]" />
        <p className="text-sm text-[var(--text-muted)]">Loading execution...</p>
      </div>
    )
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
              currentStatus === 'running' && 'animate-spin',
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
        <div className="flex items-center gap-2">
          {toolCount > 0 && (
            <span className="text-xs text-[var(--text-muted)]">
              Tools: {toolCount} call{toolCount !== 1 ? 's' : ''}
            </span>
          )}
          {/* Connection indicator */}
          <span
            className={cn(
              'inline-flex h-1.5 w-1.5 rounded-full',
              isConnected ? 'bg-[var(--status-success)]' : 'bg-[var(--text-muted)]',
            )}
            title={isConnected ? 'Live (WebSocket)' : wsFailed ? 'Polling' : 'Connecting...'}
          />
        </div>
      </div>

      {/* Events list */}
      <div ref={scrollRef} className="flex-1 space-y-1 overflow-y-auto py-2">
        {events.length === 0 && !isEventsLoading ? (
          <p className="py-8 text-center text-sm text-[var(--text-muted)]">
            {isActive ? 'Waiting for events...' : 'No events'}
          </p>
        ) : events.length === 0 && isEventsLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-5 w-5 animate-spin text-[var(--text-muted)]" />
          </div>
        ) : (
          events.map((event) => <ExecutionEventItem key={event.id} event={event} onApprove={handleApprove} onReject={handleReject} />)
        )}
      </div>

      {/* Message input */}
      <MessageInput disabled={!isActive} onSend={handleSendMessage} />
    </div>
  )
}
