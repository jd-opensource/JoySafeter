'use client'

import {
  Bot,
  Wrench,
  AlertCircle,
  ChevronDown,
  Loader2,
  CheckCircle,
  XCircle,
  Package,
} from 'lucide-react'
import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { cn } from '@/lib/utils'
import { ChatFilePreview } from './ChatFilePreview'
import type { ThreadEvent } from '@/types/thread'

interface ChatEventBubbleProps {
  event: ThreadEvent
}

interface AttachmentData {
  filename: string
  storage_ref: string
  mime_type: string
  size_bytes: number
}

export function ChatEventBubble({ event }: ChatEventBubbleProps) {
  const { event_type, payload } = event
  const [collapsed, setCollapsed] = useState(true)

  if (event_type === 'user_message') {
    const text = (payload.text as string) || ''
    const attachments = (payload.attachments as AttachmentData[]) || []

    return (
      <div className="flex justify-end">
        <div className="max-w-[70%] rounded-lg bg-[var(--skill-brand-600)] px-4 py-3 text-white">
          <p className="whitespace-pre-wrap break-words text-sm">{text}</p>
          {attachments.map((a) => (
            <ChatFilePreview
              key={a.storage_ref}
              filename={a.filename}
              storageRef={a.storage_ref}
              mimeType={a.mime_type}
              sizeBytes={a.size_bytes}
            />
          ))}
          <span className="mt-1 block text-xs opacity-70">
            {new Date(event.created_at).toLocaleTimeString()}
          </span>
        </div>
      </div>
    )
  }

  if (event_type === 'assistant_text') {
    const text = (payload.text as string) || (payload.delta as string) || ''
    return (
      <div className="flex justify-start">
        <div className="flex max-w-[70%] gap-3 rounded-lg bg-[var(--surface-2)] px-4 py-3">
          <Bot className="mt-0.5 h-4 w-4 flex-shrink-0 text-[var(--text-muted)]" />
          <div className="min-w-0 flex-1">
            <div className="prose prose-sm max-w-none break-words text-sm text-[var(--text-primary)]">
              <ReactMarkdown>{text}</ReactMarkdown>
            </div>
            <span className="mt-1 block text-xs text-[var(--text-muted)]">
              {new Date(event.created_at).toLocaleTimeString()}
            </span>
          </div>
        </div>
      </div>
    )
  }

  if (event_type === 'thinking') {
    const text = (payload.text as string) || ''
    return (
      <div className="flex items-start gap-1.5">
        <button
          type="button"
          onClick={() => setCollapsed(!collapsed)}
          className="flex items-center gap-1.5 text-xs text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
        >
          <ChevronDown className={cn('h-3 w-3 transition-transform', !collapsed && 'rotate-180')} />
          Thinking...
        </button>
        {!collapsed && (
          <div className="max-w-md rounded bg-[var(--surface-2)] p-2 text-xs text-[var(--text-muted)]">
            {text}
          </div>
        )}
      </div>
    )
  }

  if (event_type === 'tool_use_start') {
    const name = (payload.name as string) || 'tool'
    return (
      <button
        type="button"
        onClick={() => setCollapsed(!collapsed)}
        className="flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--surface-2)] px-3 py-2 text-xs"
      >
        <Wrench className="h-3 w-3 text-[var(--text-muted)]" />
        <span className="font-medium text-[var(--text-primary)]">{name}</span>
        <Loader2 className="h-3 w-3 animate-spin text-[var(--text-muted)]" />
        <ChevronDown className={cn('h-3 w-3 transition-transform', !collapsed && 'rotate-180')} />
        {!collapsed && (
          <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap text-[var(--text-muted)]">
            {JSON.stringify(payload.input, null, 2)}
          </pre>
        )}
      </button>
    )
  }

  if (event_type === 'tool_use_end') {
    const name = (payload.name as string) || 'tool'
    const success = payload.success !== false
    return (
      <button
        type="button"
        onClick={() => setCollapsed(!collapsed)}
        className="flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--surface-2)] px-3 py-2 text-xs"
      >
        <Wrench className="h-3 w-3 text-[var(--text-muted)]" />
        <span className="font-medium text-[var(--text-primary)]">{name}</span>
        {success ? (
          <CheckCircle className="h-3 w-3 text-green-500" />
        ) : (
          <XCircle className="h-3 w-3 text-red-500" />
        )}
        {!collapsed && (
          <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap text-[var(--text-muted)]">
            {typeof payload.output === 'string'
              ? payload.output
              : JSON.stringify(payload.output, null, 2)}
          </pre>
        )}
      </button>
    )
  }

  if (event_type === 'error') {
    return (
      <div className="rounded-md border border-red-500/20 bg-red-500/5 px-4 py-3">
        <div className="flex items-center gap-2 text-sm text-red-400">
          <AlertCircle className="h-4 w-4" />
          <span>{(payload.message as string) || 'Error'}</span>
        </div>
        {typeof payload.trace === 'string' && (
          <button
            type="button"
            onClick={() => setCollapsed(!collapsed)}
            className="mt-1 text-xs text-red-400/70"
          >
            {collapsed ? 'Show trace' : 'Hide trace'}
            {!collapsed && <pre className="mt-1 max-h-40 overflow-auto">{payload.trace}</pre>}
          </button>
        )}
      </div>
    )
  }

  if (event_type === 'artifact_created') {
    return (
      <div className="flex items-center gap-2 rounded-md border border-[var(--border)] bg-[var(--surface-2)] px-3 py-2 text-xs">
        <Package className="h-3 w-3 text-[var(--text-muted)]" />
        <span className="text-[var(--text-primary)]">
          Artifact: {(payload.name as string) || 'output'}
        </span>
      </div>
    )
  }

  if (event_type === 'execution_started' || event_type === 'execution_completed') {
    const isComplete = event_type === 'execution_completed'
    const terminalStatus = (payload.terminal_status as string) || event.execution_status
    return (
      <div className="flex justify-center">
        <span
          className={cn(
            'rounded-full px-3 py-0.5 text-[10px] font-medium',
            isComplete && terminalStatus === 'succeeded' && 'bg-green-500/10 text-green-500',
            isComplete && terminalStatus !== 'succeeded' && 'bg-red-500/10 text-red-400',
            !isComplete && 'bg-[var(--surface-3)] text-[var(--text-muted)]',
          )}
        >
          {isComplete ? `Execution ${terminalStatus}` : 'Execution started'}
        </span>
      </div>
    )
  }

  return null
}
