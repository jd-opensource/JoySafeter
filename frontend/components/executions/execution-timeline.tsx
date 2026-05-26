'use client'

import { AlertCircle, CheckCircle, Loader2, Pause, Play, RefreshCw, XCircle } from 'lucide-react'
import { useEffect, useMemo, useRef } from 'react'

import { Button } from '@/components/ui/button'
import { useExecution, useExecutionEvents } from '@/hooks/queries/executions'
import { useExecutionStream } from '@/hooks/use-execution-stream'
import { cn } from '@/lib/utils'
import { ACTIVE_EXECUTION_STATUSES } from '@/types/executions'

import { missionService } from '@/services/missionService'

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

interface ExecutionTimelineProps {
  executionId: string
  workspaceId: string
  compact?: boolean
  /** Set to false for terminal executions to skip WebSocket and polling. Defaults to true. */
  isLive?: boolean
  /** When set, write operations (message/approve) use mission-scoped endpoints. */
  missionId?: string
}

export function ExecutionTimeline({
  executionId,
  workspaceId,
  compact,
  isLive = true,
  missionId,
}: ExecutionTimelineProps) {
  const {
    data: execution,
    isLoading: isExecLoading,
    error: execError,
    refetch: refetchExec,
  } = useExecution(executionId, workspaceId)
  const isActive = execution ? ACTIVE_EXECUTION_STATUSES.includes(execution.status) : false
  const shouldStream = isLive && isActive && Boolean(executionId)

  // WebSocket stream — primary data source (disabled for terminal executions)
  const {
    events: wsEvents,
    status: wsStatus,
    isConnected,
    wsFailed,
  } = useExecutionStream({ executionId, enabled: shouldStream })

  // Polling fallback — only enabled when WS fails and execution is live
  const {
    data: eventsPage,
    isLoading: isEventsLoading,
    error: eventsError,
    refetch: refetchEvents,
  } = useExecutionEvents(executionId, workspaceId, undefined, {
    enabled: Boolean(executionId) && (shouldStream ? wsFailed : true),
  })

  // Use WS events when connected, fall back to polling data
  const events = useMemo(() => {
    if (!wsFailed && wsEvents.length > 0) return wsEvents
    return eventsPage?.events ?? wsEvents
  }, [wsFailed, wsEvents, eventsPage])

  const currentStatus = wsStatus ?? execution?.status ?? 'queued'

  const pendingApprovalEventId = useMemo(() => {
    if (currentStatus !== 'approval_wait') return null
    for (let i = events.length - 1; i >= 0; i--) {
      const et = events[i].event_type
      if (et === 'approval_request' || et === 'approval_requested') return events[i].id
    }
    return null
  }, [currentStatus, events])

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
    () =>
      events.filter((e) => e.event_type === 'tool_use' || e.event_type === 'tool_use_start').length,
    [events],
  )

  const tokenDisplay = useMemo(() => {
    const summary = execution?.result_summary as Record<string, number> | undefined
    if (!summary) return null
    const input = summary.input_tokens ?? 0
    const output = summary.output_tokens ?? 0
    if (!input && !output) return null
    const fmt = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n))
    return `${fmt(input)} in / ${fmt(output)} out`
  }, [execution?.result_summary])

  const handleSendMessage = async (message: string) => {
    if (!missionId) return
    try {
      await missionService.injectExecutionMessage(missionId, workspaceId, message)
    } catch (err) {
      console.error('Failed to inject message', err)
    }
  }

  const handleApproveOrReject = async (_eventId: string, approved: boolean) => {
    if (!missionId) return
    try {
      await missionService.approveExecutionAction(missionId, workspaceId, approved)
    } catch (err) {
      console.error(`Failed to ${approved ? 'approve' : 'reject'} action`, err)
    }
  }

  const actionsDisabled = !missionId

  const handleRetry = () => {
    void refetchExec()
    void refetchEvents()
  }

  // Error state
  if (execError || eventsError) {
    return (
      <div
        className={cn(
          'flex flex-col items-center justify-center gap-3',
          compact ? 'h-80' : 'h-full',
        )}
      >
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
      <div
        className={cn(
          'flex flex-col items-center justify-center gap-2',
          compact ? 'h-80' : 'h-full',
        )}
      >
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
            <span className="text-xs text-[var(--text-muted)]">Duration: {duration}</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {toolCount > 0 && (
            <span className="text-xs text-[var(--text-muted)]">
              Tools: {toolCount} call{toolCount !== 1 ? 's' : ''}
            </span>
          )}
          {tokenDisplay && (
            <span className="text-xs text-[var(--text-muted)]">Tokens: {tokenDisplay}</span>
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
          events.map((event) => (
            <ExecutionEventItem
              key={`${event.execution_id}-${event.seq}`}
              event={event}
              onApprove={(id) => handleApproveOrReject(id, true)}
              onReject={(id) => handleApproveOrReject(id, false)}
              disabled={actionsDisabled}
              isPendingApproval={event.id === pendingApprovalEventId}
            />
          ))
        )}
      </div>

      {/* Message input */}
      <MessageInput disabled={!isActive || actionsDisabled} onSend={handleSendMessage} />
    </div>
  )
}
