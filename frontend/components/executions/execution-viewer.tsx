'use client'

import {
  AlertCircle,
  CheckCircle,
  ChevronDown,
  ChevronUp,
  Loader2,
  Pause,
  Play,
  RefreshCw,
  XCircle,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { useExecution, useExecutionEvents } from '@/hooks/queries/agentRuns'
import { useExecutionStream } from '@/hooks/use-execution-stream'
import { cn } from '@/lib/utils'
import { formatDuration } from '@/lib/utils/dateHelpers'
import { ACTIVE_EXECUTION_STATUSES } from '@/types/agent-run'
import type { ExecutionEvent } from '@/types/agent-run'

import { ExecutionEventItem } from './execution-event'
import { MessageInput } from './message-input'

const STATUS_CONFIG: Record<string, { icon: React.ElementType; label: string; color: string }> = {
  pending: { icon: Pause, label: 'Pending', color: 'text-[var(--text-muted)]' },
  dispatched: { icon: Play, label: 'Dispatched', color: 'text-[var(--brand-400)]' },
  running: { icon: Loader2, label: 'Running', color: 'text-[var(--status-success)]' },
  approval_wait: { icon: Pause, label: 'Approval Wait', color: 'text-[var(--status-warning)]' },
  succeeded: { icon: CheckCircle, label: 'Succeeded', color: 'text-[var(--status-success)]' },
  failed: { icon: XCircle, label: 'Failed', color: 'text-[var(--status-error)]' },
  cancelled: { icon: XCircle, label: 'Cancelled', color: 'text-[var(--text-muted)]' },
}

interface ExecutionViewerProps {
  executionId: string
  workspaceId: string
  compact?: boolean
  isLive?: boolean
  showArtifacts?: boolean
  /** Callback for sending messages into the execution. If omitted, input is hidden. */
  onSendMessage?: (message: string) => void
  /** Callback for approve/reject actions. If omitted, action buttons are disabled. */
  onApprove?: (eventId: string, approved: boolean) => void
}

export function ExecutionViewer({
  executionId,
  workspaceId,
  compact,
  isLive = true,
  showArtifacts = true,
  onSendMessage,
  onApprove,
}: ExecutionViewerProps) {
  const {
    data: execution,
    isLoading: isExecLoading,
    error: execError,
    refetch: refetchExec,
  } = useExecution(executionId)

  const shouldStream = isLive && ACTIVE_EXECUTION_STATUSES.includes(
    (execution?.status ?? 'pending') as never,
  )

  const { events: wsEvents, status: wsStatus, isConnected, wsFailed } = useExecutionStream({
    executionId,
    enabled: shouldStream,
  })

  const {
    data: polledEventsPage,
    isLoading: isEventsLoading,
    error: eventsError,
    refetch: refetchEvents,
  } = useExecutionEvents(executionId, {
    enabled: (!shouldStream || wsFailed) && Boolean(executionId),
  })

  const events: ExecutionEvent[] = shouldStream && !wsFailed ? wsEvents : (polledEventsPage ?? [])
  const currentStatus = (shouldStream && !wsFailed ? wsStatus : null) ?? execution?.status ?? 'pending'
  const isActive = ACTIVE_EXECUTION_STATUSES.includes(currentStatus as never)

  // Artifacts from event stream
  const artifacts = useMemo(() => {
    if (!showArtifacts) return []
    return events
      .filter((e) => e.event_type === 'artifact_created')
      .map((e) => ({
        type: 'file' as const,
        title: (e.payload as Record<string, string>)?.uri || (e.payload as Record<string, string>)?.name || 'artifact',
        content: (e.payload as Record<string, string>)?.content || '',
        language: (e.payload as Record<string, string>)?.language,
      }))
  }, [events, showArtifacts])

  const pendingApprovalEventId = useMemo(() => {
    if (currentStatus !== 'approval_wait') return null
    for (let i = events.length - 1; i >= 0; i--) {
      const et = events[i].event_type
      if (et === 'approval_requested') return events[i].id
    }
    return null
  }, [currentStatus, events])

  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [events.length])

  const statusConfig = STATUS_CONFIG[currentStatus] ?? STATUS_CONFIG.pending
  const StatusIcon = statusConfig.icon

  const duration = useMemo(
    () => formatDuration(execution?.started_at, execution?.ended_at),
    [execution?.started_at, execution?.ended_at],
  )

  const toolCount = useMemo(
    () => events.filter((e) => e.event_type === 'tool_use_start').length,
    [events],
  )

  const tokenDisplay = useMemo(() => {
    const summary = execution?.metrics as Record<string, number> | undefined
    if (!summary) return null
    const input = summary.input_tokens ?? 0
    const output = summary.output_tokens ?? 0
    if (!input && !output) return null
    const fmt = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n))
    return `${fmt(input)} in / ${fmt(output)} out`
  }, [execution?.metrics])

  const handleApproveOrReject = (eventId: string, approved: boolean) => {
    onApprove?.(eventId, approved)
  }

  const handleRetry = () => {
    void refetchExec()
    void refetchEvents()
  }

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
            className={cn('h-4 w-4', statusConfig.color, currentStatus === 'running' && 'animate-spin')}
          />
          <span className={cn('text-sm font-medium', statusConfig.color)}>{statusConfig.label}</span>
          {duration && <span className="text-xs text-[var(--text-muted)]">{duration}</span>}
        </div>
        <div className="flex items-center gap-2">
          {toolCount > 0 && (
            <span className="text-xs text-[var(--text-muted)]">
              Tools: {toolCount} call{toolCount !== 1 ? 's' : ''}
            </span>
          )}
          {tokenDisplay && <span className="text-xs text-[var(--text-muted)]">{tokenDisplay}</span>}
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
              disabled={!onApprove}
              isPendingApproval={event.id === pendingApprovalEventId}
            />
          ))
        )}
      </div>

      {/* Artifact panel */}
      {showArtifacts && artifacts.length > 0 && (
        <div className="border-t border-[var(--border)]">
          <ArtifactSection artifacts={artifacts} />
        </div>
      )}

      {/* Message input — only shown when callback is provided */}
      {onSendMessage && <MessageInput disabled={!isActive} onSend={onSendMessage} />}
    </div>
  )
}

/** Collapsible artifact section */
function ArtifactSection({ artifacts }: { artifacts: Array<{ type: string; title: string; content: string; language?: string }> }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <>
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center justify-between px-4 py-2 text-xs font-medium text-[var(--text-secondary)] hover:bg-[var(--surface-2)]"
      >
        <span>Artifacts ({artifacts.length})</span>
        {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
      </button>
      {expanded && (
        <div className="max-h-48 overflow-y-auto">
          {artifacts.map((a, i) => (
            <div key={i} className="border-t border-[var(--border)] px-4 py-2">
              <p className="mb-1 text-xs font-medium text-[var(--text-secondary)]">{a.title}</p>
              {a.content && (
                <pre className="max-h-32 overflow-auto rounded bg-[var(--surface-3)] p-2 text-xs">
                  <code>{a.content}</code>
                </pre>
              )}
            </div>
          ))}
        </div>
      )}
    </>
  )
}
