'use client'

import type { ReactNode } from 'react'
import type { SessionEvent } from '@/types/managed'
import { useTranslation } from '@/lib/i18n'
import { RoleBadge } from './role-badge'

interface EventRowProps {
  event: SessionEvent
  sessionStart: string
  selected: boolean
  onClick: () => void
  mode: 'transcript' | 'debug'
}

export function EventRow({ event, sessionStart, selected, onClick, mode }: EventRowProps) {
  const { t } = useTranslation()
  const eventTime = event.created_at || event.id || ''
  const elapsed = getElapsedTime(sessionStart, eventTime)
  const preview = getPreview(event, mode, t)
  const metrics = getMetrics(event, t)
  const eventType = event.type || event.event_type || ''
  const toolName = event.tool || event.tool_name || event.name

  // Identify stdio-protocol events that are not real LLM tool executions but
  // belong to the --permission-prompt-tool approval handshake or interrupt
  // signal. We keep them in the debug view (they carry the protocol ids)
  // but dim them visually so they don't compete with the conversation.
  const protocolKind: 'approval-request' | 'approval-ack' | 'interrupt' | null = (() => {
    if (
      eventType === 'agent.tool_use' &&
      (event as { is_control_request?: boolean }).is_control_request
    ) {
      return 'approval-request'
    }
    if (eventType === 'user.tool_confirmation') return 'approval-ack'
    if (eventType === 'user.interrupt') return 'interrupt'
    return null
  })()
  const protocolLabel =
    protocolKind === 'approval-request'
      ? t('managed.sessions.events.protocolApprovalRequest')
      : protocolKind === 'approval-ack'
        ? t('managed.sessions.events.protocolApprovalAck')
        : null

  return (
    <div
      onClick={onClick}
      className={`flex cursor-pointer items-start gap-3 border-b border-border px-4 py-2.5 transition-colors last:border-b-0 ${
        selected
          ? 'bg-accent'
          : protocolKind
            ? 'border-l-2 border-l-amber-400 bg-muted/40 hover:bg-muted/60'
            : 'hover:bg-accent/40'
      } ${protocolKind ? 'opacity-75' : ''}`}
    >
      <RoleBadge eventType={eventType} toolName={toolName} />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm text-foreground">
          {preview}
          {protocolLabel && (
            <span className="ml-2 inline-flex items-center rounded border border-amber-400/60 bg-amber-50 px-1.5 py-0.5 align-middle text-[10px] font-medium text-amber-700 dark:bg-amber-950/30 dark:text-amber-300">
              {protocolLabel}
            </span>
          )}
        </p>
      </div>
      {metrics && <div className="flex shrink-0 items-center gap-2">{metrics}</div>}
      <span className="shrink-0 text-xs tabular-nums text-muted-foreground">{elapsed}</span>
    </div>
  )
}

function getElapsedTime(start: string, current: string): string {
  const startMs = parseEventTime(start)
  const currentMs = parseEventTime(current)
  if (isNaN(startMs) || isNaN(currentMs)) return ''
  const ms = currentMs - startMs
  if (ms < 0) return '0:00:00'
  const secs = Math.floor(ms / 1000)
  const mins = Math.floor(secs / 60)
  const hrs = Math.floor(mins / 60)
  return `${hrs}:${String(mins % 60).padStart(2, '0')}:${String(secs % 60).padStart(2, '0')}`
}

function parseEventTime(value: string): number {
  if (!value) return NaN
  const d = new Date(value).getTime()
  if (!isNaN(d)) return d
  const hex = value.replace(/^evt_/, '').replace(/-/g, '')
  if (hex.length >= 12) {
    const ts = parseInt(hex.slice(0, 12), 16)
    if (ts > 1_000_000_000_000 && ts < 2_000_000_000_000) return ts
  }
  return NaN
}

function getPreview(
  event: SessionEvent,
  mode: 'transcript' | 'debug',
  t: (key: string, options?: Record<string, unknown>) => string,
): ReactNode {
  const eventType = event.type || event.event_type || ''
  const withCollapsedCount = (label: string) => {
    const collapsedSuffix =
      event._collapsedCount && event._collapsedCount > 1 ? ` ×${event._collapsedCount}` : ''
    return `${label}${collapsedSuffix}`
  }

  if (eventType === 'session.status_running')
    return withCollapsedCount(t('managed.sessions.events.sessionRunning'))
  if (eventType === 'session.status_idle') {
    if (isRequiresActionIdle(event))
      return withCollapsedCount(t('managed.sessions.events.sessionRequiresAction'))
    return withCollapsedCount(t('managed.sessions.events.sessionIdle'))
  }

  if (mode === 'debug') {
    if (eventType === 'span.model_request_start')
      return t('managed.sessions.events.modelRequest', { model: event.model || '' })
    if (eventType === 'span.model_request_end') {
      const usage = event.usage || {}
      const input = usage.input_tokens ?? '?'
      const output = usage.output_tokens ?? '?'
      const cacheRead = usage.cache_read_input_tokens ?? usage.cache_read_tokens
      const cacheWrite = usage.cache_creation_input_tokens ?? usage.cache_write_tokens
      let s = cacheRead
        ? t('managed.sessions.events.tokenUsageWithCache', { input, cacheRead, output })
        : t('managed.sessions.events.tokenUsage', { input, output })
      if (cacheWrite) s += ` · ${t('managed.sessions.events.cacheWrite', { count: cacheWrite })}`
      return s
    }
    if (eventType === 'agent.thinking') return t('managed.sessions.events.thinking')
  }

  // Tool use: preview shows `ToolName(args)` like claude-code's TUI.
  // Bash → Bash(grep -rn "..."), Read → Read(/path/to/file),
  // Grep → Grep(pattern: "..."), etc. Long values get truncated.
  const isToolUse =
    eventType === 'agent.tool_use' ||
    eventType === 'agent.mcp_tool_use' ||
    eventType === 'agent.custom_tool_use' ||
    eventType === 'tool_use'
  if (isToolUse) {
    return formatToolUsePreview(event)
  }

  // Background sub-agent lifecycle (Task tool with run_in_background=true)
  if (
    eventType === 'agent.bg_task_started' ||
    eventType === 'agent.bg_task_progress' ||
    eventType === 'agent.bg_task_finished'
  ) {
    const ev = event as unknown as {
      description?: string
      task_id?: string
      status?: string
      summary?: string
      last_tool_name?: string
      total_tokens?: number
      tool_uses?: number
      duration_ms?: number
    }
    const desc = ev.description || ev.task_id || ''
    if (eventType === 'agent.bg_task_started') {
      return truncateRowText(
        withCollapsedCount(t('managed.sessions.events.bgTaskStarted', { description: desc })),
      )
    }
    if (eventType === 'agent.bg_task_progress') {
      const lastTool = ev.last_tool_name ? ` · ${ev.last_tool_name}` : ''
      return truncateRowText(
        withCollapsedCount(
          t('managed.sessions.events.bgTaskProgress', { description: desc }) + lastTool,
        ),
      )
    }
    // finished
    const status = ev.status || 'completed'
    return truncateRowText(
      withCollapsedCount(
        ev.summary || t('managed.sessions.events.bgTaskFinished', { description: desc, status }),
      ),
    )
  }

  if (event.content && Array.isArray(event.content) && event.content[0]?.text) {
    return truncateRowText(event.content[0].text)
  }
  if (typeof event.content === 'string' && event.content) {
    return truncateRowText(event.content)
  }

  // Friendly preview for the stdio-protocol approval ack — never expose the
  // raw "user.tool_confirmation" event type in the UI.
  if (eventType === 'user.tool_confirmation') {
    const approved = (event as { approved?: boolean }).approved
    const denyMsg = (event as { deny_message?: string }).deny_message
    if (approved) return withCollapsedCount(t('managed.sessions.events.toolConfirmationApproved'))
    if (denyMsg) {
      return withCollapsedCount(
        t('managed.sessions.events.toolConfirmationDeniedWithReason', { reason: denyMsg }),
      )
    }
    return withCollapsedCount(t('managed.sessions.events.toolConfirmationDenied'))
  }

  // Friendly preview for interrupt — never expose raw "user.interrupt".
  if (eventType === 'user.interrupt') {
    return withCollapsedCount(t('managed.sessions.events.interruptRequested'))
  }

  return withCollapsedCount(eventType)
}

function isRequiresActionIdle(event: SessionEvent): boolean {
  return (
    typeof event.stop_reason === 'object' &&
    event.stop_reason !== null &&
    (event.stop_reason as { type?: string }).type === 'requires_action'
  )
}

const TOOL_USE_TYPES = new Set([
  'agent.tool_use',
  'agent.mcp_tool_use',
  'agent.custom_tool_use',
  'tool_use',
])

const MonitorIcon = () => (
  <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <rect x="2" y="3" width="20" height="14" rx="2" />
    <line x1="8" y1="21" x2="16" y2="21" />
    <line x1="12" y1="17" x2="12" y2="21" />
  </svg>
)

const ClockIcon = () => (
  <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <circle cx="12" cy="12" r="10" />
    <polyline points="12 6 12 12 16 14" />
  </svg>
)

function getMetrics(event: SessionEvent, t: (key: string) => string): ReactNode | null {
  const eventType = event.type || event.event_type || ''
  if (eventType === 'span.model_request_end') return null

  const isTool = TOOL_USE_TYPES.has(eventType)
  const parts: ReactNode[] = []

  // Error badge for tool events with is_error
  if (event.is_error) {
    parts.push(
      <span
        key="error"
        className="inline-flex items-center rounded bg-red-100 px-1.5 py-0.5 text-[10px] font-semibold text-red-700 dark:bg-red-900/40 dark:text-red-400"
      >
        {t('managed.sessions.roles.error')}
      </span>,
    )
  }

  // Token usage — only for agent messages, not tools
  if (!isTool) {
    const usage = event.usage
    const input = usage?.input_tokens ?? event.input_tokens
    const output = usage?.output_tokens ?? event.output_tokens
    if (input || output) {
      parts.push(
        <span
          key="tokens"
          className="inline-flex items-center gap-1 font-mono text-xs text-muted-foreground"
        >
          <MonitorIcon />
          {formatTokens(input || 0)} / {formatTokens(output || 0)}
        </span>,
      )
    }
  }

  // Duration — only for tool events
  if (isTool) {
    const ms = event.duration_ms
    if (ms != null && ms > 0) {
      parts.push(
        <span
          key="duration"
          className="inline-flex items-center gap-1 font-mono text-xs text-muted-foreground"
        >
          <ClockIcon />
          {ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`}
        </span>,
      )
    }
  }

  return parts.length > 0 ? <>{parts}</> : null
}

function formatTokens(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`
  return String(n)
}

/**
 * Format a tool_use event preview as `**ToolName**(<dim>args</dim>)`,
 * mirroring claude-code's TUI (AssistantToolUseMessage.tsx):
 *   - tool name is bold + emphasised so it can be scanned vertically
 *   - args wrapped in parens, dimmed, single-line truncated
 *
 * Returns a JSX element so the visual hierarchy doesn't collapse into a
 * single text run (which is what made it look noisy before).
 */
// Single-line truncation cap shared across all event-row previews
// (user/agent messages, tool args, bg-task progress). Matches claude-code's
// MAX_COMMAND_DISPLAY_CHARS in src/tools/BashTool/UI.tsx so the visual
// density is consistent with what users see in the cc TUI.
const ROW_DISPLAY_MAX_CHARS = 160

/**
 * Collapse newlines/whitespace and truncate to ROW_DISPLAY_MAX_CHARS.
 * Used to normalize free-form text fields (user/agent messages, summaries)
 * so every row in the timeline keeps a consistent height and density.
 */
function truncateRowText(text: string): string {
  const collapsed = text.replace(/\s+/g, ' ').trim()
  return collapsed.length > ROW_DISPLAY_MAX_CHARS
    ? collapsed.slice(0, ROW_DISPLAY_MAX_CHARS) + '…'
    : collapsed
}

/**
 * Strip the sandbox cwd prefix (`/workspace/`) from a path so the timeline
 * shows relative paths the way claude-code's TUI does via `getDisplayPath`.
 * Bare `/workspace` becomes `.` for clarity.
 */
function stripSandboxCwd(p: string): string {
  if (p === '/workspace' || p === '/workspace/') return '.'
  if (p.startsWith('/workspace/')) return p.slice('/workspace/'.length)
  return p
}

/**
 * Strip the sandbox cwd from any `/workspace/...` substring inside a Bash
 * command so long greps/finds shrink nicely. We're conservative — only swap
 * when the prefix is preceded by a token boundary so we don't mangle URLs
 * or quoted strings that happen to contain "/workspace/".
 */
function stripSandboxCwdInCommand(cmd: string): string {
  return cmd.replace(/(^|[\s"'`(=:])\/workspace\//g, '$1')
}

function formatToolUsePreview(event: SessionEvent): ReactNode {
  const toolName = String(event.tool || event.tool_name || event.name || '')
  if (!toolName) return event.type || event.event_type || ''
  const arg = extractToolArgString(event, toolName)
  if (!arg) {
    return <span className="font-medium text-foreground">{toolName}</span>
  }
  return (
    <span className="inline-flex items-baseline gap-0.5 align-baseline">
      <span className="font-medium text-foreground">{toolName}</span>
      <span className="font-mono text-xs text-muted-foreground">({arg})</span>
    </span>
  )
}

function extractToolArgString(event: SessionEvent, toolName: string): string {
  // Normalize: event.input may be an object or a (legacy) JSON string.
  let raw = event.input as unknown
  if (typeof raw === 'string') {
    try {
      raw = JSON.parse(raw)
    } catch {
      /* keep as string */
    }
  }
  const input = raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : null

  let arg: string | null = null
  if (input) {
    switch (toolName) {
      case 'Bash':
      case 'BashOutput':
      case 'KillBash':
        if (typeof input.command === 'string') {
          arg = stripSandboxCwdInCommand(input.command)
        } else if (typeof input.bash_id === 'string') {
          arg = input.bash_id
        }
        break
      case 'Read':
      case 'Write':
      case 'FileRead':
      case 'FileWrite':
        if (typeof input.file_path === 'string') arg = stripSandboxCwd(input.file_path)
        break
      case 'Edit':
      case 'FileEdit':
      case 'NotebookEdit':
        if (typeof input.file_path === 'string' || typeof input.notebook_path === 'string') {
          arg = stripSandboxCwd(String(input.file_path || input.notebook_path))
        }
        break
      case 'Grep': {
        const parts: string[] = []
        if (input.pattern) parts.push(`"${String(input.pattern)}"`)
        if (input.path) parts.push(stripSandboxCwd(String(input.path)))
        if (parts.length) arg = parts.join(', ')
        break
      }
      case 'Glob': {
        if (input.pattern) arg = String(input.pattern)
        if (input.path) {
          const p = stripSandboxCwd(String(input.path))
          arg = arg ? `${arg}, ${p}` : p
        }
        break
      }
      case 'WebFetch':
        if (typeof input.url === 'string') arg = input.url
        break
      case 'WebSearch':
        if (typeof input.query === 'string') arg = `"${input.query}"`
        break
      case 'Task':
      case 'Agent':
        if (typeof input.description === 'string') arg = input.description
        else if (typeof input.subagent_type === 'string') arg = input.subagent_type
        break
      case 'TodoWrite':
        if (Array.isArray(input.todos)) arg = `${input.todos.length} items`
        break
      case 'LSP':
        if (typeof input.operation === 'string') arg = String(input.operation)
        break
      default:
        for (const key of ['query', 'name', 'path', 'file_path', 'command', 'url', 'input']) {
          const v = input[key]
          if (typeof v === 'string') {
            arg = key === 'path' || key === 'file_path' ? stripSandboxCwd(v) : v
            break
          }
        }
        break
    }
  }

  if (arg == null || arg.length === 0) return ''
  // Collapse internal whitespace/newlines so the row stays single-line.
  const collapsed = arg.replace(/\s+/g, ' ').trim()
  return collapsed.length > ROW_DISPLAY_MAX_CHARS
    ? collapsed.slice(0, ROW_DISPLAY_MAX_CHARS) + '…'
    : collapsed
}
