'use client'

import {
  AlertTriangle,
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
import type { ExecutionEvent, ExecutionEventType } from '@/types/executions'

const EVENT_CONFIG: Record<
  ExecutionEventType,
  { icon: React.ElementType; label: string; style: string }
> = {
  text: { icon: FileText, label: 'Text', style: '' },
  thinking: { icon: MessageSquare, label: 'Thinking', style: 'bg-[var(--bg-secondary)] italic' },
  tool_use: { icon: Wrench, label: 'Tool', style: '' },
  tool_result: { icon: Wrench, label: 'Result', style: '' },
  error: { icon: XCircle, label: 'Error', style: 'border-l-2 border-l-red-500 text-red-600' },
  approval_request: {
    icon: AlertTriangle,
    label: 'Approval Required',
    style: 'border-l-2 border-l-yellow-500 bg-yellow-50/50',
  },
  user_message: { icon: MessageSquare, label: 'User', style: 'bg-blue-50/50' },
  artifact: { icon: Paperclip, label: 'Artifact', style: '' },
  status: { icon: Info, label: 'Status', style: '' },
}

interface ExecutionEventItemProps {
  event: ExecutionEvent
  onApprove?: (eventId: string) => void
  onReject?: (eventId: string) => void
}

export function ExecutionEventItem({ event, onApprove, onReject }: ExecutionEventItemProps) {
  const [expanded, setExpanded] = useState(false)
  const config = EVENT_CONFIG[event.event_type] ?? EVENT_CONFIG.text
  const Icon = config.icon
  const payload = event.payload

  const timestamp = new Date(event.created_at).toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
  })

  const renderContent = () => {
    switch (event.event_type) {
      case 'text':
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
              {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
              Thinking...
            </button>
            {expanded && (
              <p className="mt-1 whitespace-pre-wrap text-sm italic text-[var(--text-secondary)]">
                {String(payload.content ?? payload.text ?? '')}
              </p>
            )}
          </div>
        )

      case 'tool_use':
        return (
          <div>
            <p className="text-sm font-medium text-[var(--text-primary)]">
              {String(payload.tool_name ?? payload.name ?? 'tool')}
            </p>
            <button
              type="button"
              onClick={() => setExpanded(!expanded)}
              className="mt-0.5 flex items-center gap-1 text-xs text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
            >
              {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
              Input
            </button>
            {expanded && (
              <pre className="mt-1 max-h-48 overflow-auto rounded bg-[var(--bg-secondary)] p-2 text-xs text-[var(--text-secondary)]">
                {JSON.stringify(payload.input ?? payload.arguments ?? {}, null, 2)}
              </pre>
            )}
          </div>
        )

      case 'tool_result':
        return (
          <div>
            <button
              type="button"
              onClick={() => setExpanded(!expanded)}
              className="flex items-center gap-1 text-xs text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
            >
              {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
              Output
            </button>
            {expanded && (
              <pre className="mt-1 max-h-48 overflow-auto rounded bg-[var(--bg-secondary)] p-2 text-xs text-[var(--text-secondary)]">
                {typeof payload.output === 'string'
                  ? payload.output
                  : JSON.stringify(payload.output ?? payload.content ?? {}, null, 2)}
              </pre>
            )}
          </div>
        )

      case 'error':
        return (
          <p className="text-sm text-red-600">
            {String(payload.message ?? payload.error ?? 'Unknown error')}
          </p>
        )

      case 'approval_request':
        return (
          <div>
            <p className="text-sm text-[var(--text-primary)]">
              {String(payload.message ?? payload.description ?? 'Agent requests approval')}
            </p>
            <div className="mt-2 flex gap-2">
              <Button size="sm" onClick={() => onApprove?.(event.id)}>
                Approve
              </Button>
              <Button size="sm" variant="outline" onClick={() => onReject?.(event.id)}>
                Reject
              </Button>
            </div>
          </div>
        )

      case 'user_message':
        return (
          <p className="text-sm text-[var(--text-primary)]">
            {String(payload.content ?? payload.text ?? '')}
          </p>
        )

      case 'artifact':
        return (
          <p className="text-sm text-[var(--text-secondary)]">
            {String(payload.title ?? payload.name ?? 'Artifact')}
            {payload.type ? ` (${String(payload.type)})` : ''}
          </p>
        )

      case 'status':
        return (
          <p className="text-sm text-[var(--text-muted)]">
            {String(payload.message ?? payload.status ?? '')}
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
