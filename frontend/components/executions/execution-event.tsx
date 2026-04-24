'use client'

import {
  AlertTriangle,
  CheckCircle,
  ChevronDown,
  ChevronRight,
  FileText,
  Info,
  MessageSquare,
  Paperclip,
  Wrench,
  XCircle,
} from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { ExecutionEvent, ExecutionEventType } from '@/types/agent-run'

const TEXT_CFG = { icon: FileText, label: 'Text', style: '' } as const
const TOOL_CFG = { icon: Wrench, label: 'Tool', style: '' } as const
const RESULT_CFG = { icon: Wrench, label: 'Result', style: '' } as const
const APPROVAL_CFG = {
  icon: AlertTriangle,
  label: 'Approval Required',
  style: 'border-l-2 border-l-[var(--status-warning)] bg-[var(--status-warning-bg)]',
} as const
const ARTIFACT_CFG = { icon: Paperclip, label: 'Artifact', style: '' } as const

const EVENT_CONFIG: Partial<
  Record<ExecutionEventType, { icon: React.ElementType; label: string; style: string }>
> = {
  assistant_text: TEXT_CFG,
  thinking: { icon: MessageSquare, label: 'Thinking', style: 'bg-[var(--surface-3)] italic' },
  tool_use_start: TOOL_CFG,
  tool_use_end: RESULT_CFG,
  error: {
    icon: XCircle,
    label: 'Error',
    style: 'border-l-2 border-l-[var(--status-error)] text-[var(--status-error)]',
  },
  approval_requested: APPROVAL_CFG,
  user_message: { icon: MessageSquare, label: 'User', style: 'bg-[var(--surface-3)]' },
  artifact_created: ARTIFACT_CFG,
  execution_status_change: { icon: Info, label: 'Status', style: '' },
  execution_started: { icon: Info, label: 'Started', style: '' },
  execution_completed: { icon: Info, label: 'Completed', style: '' },
  approval_resolved: { icon: CheckCircle, label: 'Resolved', style: '' },
}

interface ExecutionEventItemProps {
  event: ExecutionEvent
  onApprove?: (eventId: string) => void
  onReject?: (eventId: string) => void
  disabled?: boolean
  isPendingApproval?: boolean
}

export function ExecutionEventItem({
  event,
  onApprove,
  onReject,
  disabled,
  isPendingApproval,
}: ExecutionEventItemProps) {
  const [expanded, setExpanded] = useState(false)
  const defaultConfig = { icon: Info, label: event.event_type, style: '' }
  const config = EVENT_CONFIG[event.event_type] ?? defaultConfig
  const Icon = config.icon
  const payload = event.payload ?? {}

  const timestamp = new Date(event.created_at).toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
  })

  const renderContent = () => {
    switch (event.event_type) {
      case 'assistant_text':
        return (
          <p className="whitespace-pre-wrap text-sm text-[var(--text-primary)]">
            {String(payload.content ?? payload.text ?? '')}
          </p>
        )

      case 'thinking':
        return (
          <div>
            <button
              type="button"
              onClick={() => setExpanded(!expanded)}
              className="flex items-center gap-1 text-xs text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
            >
              {expanded ? (
                <ChevronDown className="h-3 w-3" />
              ) : (
                <ChevronRight className="h-3 w-3" />
              )}
              Thinking...
            </button>
            {expanded && (
              <p className="mt-1 whitespace-pre-wrap text-sm italic text-[var(--text-secondary)]">
                {String(payload.content ?? payload.text ?? '')}
              </p>
            )}
          </div>
        )

      case 'tool_use_start': {
        const tool = (payload.tool as Record<string, unknown>) ?? {}
        const toolName = String(tool.name ?? payload.tool_name ?? payload.name ?? 'tool')
        const toolInput = tool.input ?? payload.input ?? payload.arguments ?? {}
        return (
          <div>
            <p className="text-sm font-medium text-[var(--text-primary)]">{toolName}</p>
            <button
              type="button"
              onClick={() => setExpanded(!expanded)}
              className="mt-0.5 flex items-center gap-1 text-xs text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
            >
              {expanded ? (
                <ChevronDown className="h-3 w-3" />
              ) : (
                <ChevronRight className="h-3 w-3" />
              )}
              Input
            </button>
            {expanded && (
              <pre className="mt-1 max-h-48 overflow-auto rounded bg-[var(--surface-3)] p-2 text-xs text-[var(--text-secondary)]">
                {JSON.stringify(toolInput, null, 2)}
              </pre>
            )}
          </div>
        )
      }

      case 'tool_use_end':
        return (
          <div>
            <button
              type="button"
              onClick={() => setExpanded(!expanded)}
              className="flex items-center gap-1 text-xs text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
            >
              {expanded ? (
                <ChevronDown className="h-3 w-3" />
              ) : (
                <ChevronRight className="h-3 w-3" />
              )}
              Output
            </button>
            {expanded && (
              <pre className="mt-1 max-h-48 overflow-auto rounded bg-[var(--surface-3)] p-2 text-xs text-[var(--text-secondary)]">
                {typeof payload.output === 'string'
                  ? payload.output
                  : JSON.stringify(payload.output ?? payload.content ?? {}, null, 2)}
              </pre>
            )}
          </div>
        )

      case 'error':
        return (
          <p className="text-sm text-[var(--status-error)]">
            {String(payload.message ?? payload.error ?? 'Unknown error')}
          </p>
        )

      case 'approval_requested': {
        const toolName = String(payload.tool_name ?? '')
        const toolInput = payload.input ?? {}
        return (
          <div>
            <p className="text-sm font-medium text-[var(--text-primary)]">
              {String(payload.message ?? `Agent wants to use: ${toolName || 'unknown tool'}`)}
            </p>
            {toolName && (
              <div className="mt-1">
                <button
                  type="button"
                  onClick={() => setExpanded(!expanded)}
                  className="flex items-center gap-1 text-xs text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
                >
                  {expanded ? (
                    <ChevronDown className="h-3 w-3" />
                  ) : (
                    <ChevronRight className="h-3 w-3" />
                  )}
                  {toolName} input
                </button>
                {expanded && (
                  <pre className="mt-1 max-h-48 overflow-auto rounded bg-[var(--surface-3)] p-2 text-xs text-[var(--text-secondary)]">
                    {JSON.stringify(toolInput, null, 2)}
                  </pre>
                )}
              </div>
            )}
            <div className="mt-2 flex gap-2">
              {isPendingApproval ? (
                <>
                  <Button size="sm" onClick={() => onApprove?.(event.id)} disabled={disabled}>
                    Approve
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => onReject?.(event.id)}
                    disabled={disabled}
                  >
                    Reject
                  </Button>
                </>
              ) : (
                <span className="text-xs text-[var(--text-muted)]">Resolved</span>
              )}
            </div>
          </div>
        )
      }

      case 'approval_resolved':
        return (
          <p className="text-xs text-[var(--text-muted)]">
            {payload.decision === 'auto_approved'
              ? 'Auto-approved'
              : payload.decision === 'approved'
                ? 'Approved'
                : 'Rejected'}
          </p>
        )

      case 'user_message':
        return (
          <p className="text-sm text-[var(--text-primary)]">
            {String(payload.content ?? payload.text ?? '')}
          </p>
        )

      case 'artifact_created':
        return (
          <p className="text-sm text-[var(--text-secondary)]">
            {String(payload.title ?? payload.name ?? 'Artifact')}
            {payload.type ? ` (${String(payload.type)})` : ''}
          </p>
        )

      case 'execution_status_change':
      case 'execution_started':
      case 'execution_completed':
        return (
          <p className="text-sm text-[var(--text-muted)]">
            {String(payload.message ?? payload.status ?? config.label)}
          </p>
        )

      default:
        return (
          <pre className="text-xs text-[var(--text-secondary)]">
            {JSON.stringify(payload, null, 2)}
          </pre>
        )
    }
  }

  return (
    <div className={cn('flex gap-3 rounded-md px-3 py-2', config.style)}>
      <div className="flex flex-col items-center gap-1 pt-0.5">
        <span className="text-[10px] tabular-nums text-[var(--text-muted)]">{timestamp}</span>
        <Icon className="h-4 w-4 shrink-0 text-[var(--text-muted)]" />
      </div>
      <div className="min-w-0 flex-1">{renderContent()}</div>
    </div>
  )
}
