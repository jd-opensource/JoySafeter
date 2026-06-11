'use client'

import type { ReactNode } from "react"
import type { SessionEvent } from "@/types/managed"
import { useTranslation } from "@/lib/i18n"
import { RoleBadge } from "./role-badge"

interface EventRowProps {
  event: SessionEvent
  sessionStart: string
  selected: boolean
  onClick: () => void
  mode: "transcript" | "debug"
}

export function EventRow({ event, sessionStart, selected, onClick, mode }: EventRowProps) {
  const { t } = useTranslation()
  const eventTime = event.created_at || event.id || ""
  const elapsed = getElapsedTime(sessionStart, eventTime)
  const preview = getPreview(event, mode, t)
  const metrics = getMetrics(event, t)
  const eventType = event.type || event.event_type || ""
  const toolName = event.tool || event.tool_name || event.name

  return (
    <div
      onClick={onClick}
      className={`flex items-start gap-3 px-4 py-2.5 cursor-pointer transition-colors border-b border-border last:border-b-0 ${
        selected ? "bg-accent" : "hover:bg-accent/40"
      }`}
    >
      <RoleBadge eventType={eventType} toolName={toolName} />
      <div className="flex-1 min-w-0">
        <p className="text-sm text-foreground truncate">{preview}</p>
      </div>
      {metrics && (
        <div className="flex items-center gap-2 shrink-0">
          {metrics}
        </div>
      )}
      <span className="text-xs text-muted-foreground shrink-0 tabular-nums">
        {elapsed}
      </span>
    </div>
  )
}

function getElapsedTime(start: string, current: string): string {
  const startMs = parseEventTime(start)
  const currentMs = parseEventTime(current)
  if (isNaN(startMs) || isNaN(currentMs)) return ""
  const ms = currentMs - startMs
  if (ms < 0) return "0:00:00"
  const secs = Math.floor(ms / 1000)
  const mins = Math.floor(secs / 60)
  const hrs = Math.floor(mins / 60)
  return `${hrs}:${String(mins % 60).padStart(2, "0")}:${String(secs % 60).padStart(2, "0")}`
}

function parseEventTime(value: string): number {
  if (!value) return NaN
  const d = new Date(value).getTime()
  if (!isNaN(d)) return d
  const hex = value.replace(/^evt_/, "").replace(/-/g, "")
  if (hex.length >= 12) {
    const ts = parseInt(hex.slice(0, 12), 16)
    if (ts > 1_000_000_000_000 && ts < 2_000_000_000_000) return ts
  }
  return NaN
}

function getPreview(event: SessionEvent, mode: "transcript" | "debug", t: (key: string, options?: Record<string, unknown>) => string): string {
  const eventType = event.type || event.event_type || ""
  const withCollapsedCount = (label: string) => {
    const collapsedSuffix = event._collapsedCount && event._collapsedCount > 1 ? ` ×${event._collapsedCount}` : ""
    return `${label}${collapsedSuffix}`
  }

  if (eventType === "session.status_running") return withCollapsedCount(t("managed.sessions.events.sessionRunning"))
  if (eventType === "session.status_idle") {
    if (isRequiresActionIdle(event)) return withCollapsedCount(t("managed.sessions.events.sessionRequiresAction"))
    return withCollapsedCount(t("managed.sessions.events.sessionIdle"))
  }

  if (mode === "debug") {
    if (eventType === "span.model_request_start") return t("managed.sessions.events.modelRequest", { model: event.model || "" })
    if (eventType === "span.model_request_end") {
      const usage = event.usage || {}
      const input = usage.input_tokens ?? "?"
      const output = usage.output_tokens ?? "?"
      const cacheRead = usage.cache_read_input_tokens ?? usage.cache_read_tokens
      const cacheWrite = usage.cache_creation_input_tokens ?? usage.cache_write_tokens
      let s = cacheRead
        ? t("managed.sessions.events.tokenUsageWithCache", { input, cacheRead, output })
        : t("managed.sessions.events.tokenUsage", { input, output })
      if (cacheWrite) s += ` · ${t("managed.sessions.events.cacheWrite", { count: cacheWrite })}`
      return s
    }
    if (eventType === "agent.thinking") return t("managed.sessions.events.thinking")
  }

  // Tool use: preview shows tool name(s)
  const isToolUse = eventType === "agent.tool_use" || eventType === "agent.mcp_tool_use" || eventType === "agent.custom_tool_use" || eventType === "tool_use"
  if (isToolUse) {
    return event.tool || event.tool_name || event.name || eventType
  }

  if (event.content && Array.isArray(event.content) && event.content[0]?.text) {
    return event.content[0].text
  }
  if (typeof event.content === "string" && event.content) {
    return event.content
  }

  return withCollapsedCount(eventType)
}

function isRequiresActionIdle(event: SessionEvent): boolean {
  return typeof event.stop_reason === "object"
    && event.stop_reason !== null
    && (event.stop_reason as { type?: string }).type === "requires_action"
}

const TOOL_USE_TYPES = new Set([
  "agent.tool_use", "agent.mcp_tool_use", "agent.custom_tool_use",
  "tool_use",
])

const MonitorIcon = () => (
  <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <rect x="2" y="3" width="20" height="14" rx="2"/>
    <line x1="8" y1="21" x2="16" y2="21"/>
    <line x1="12" y1="17" x2="12" y2="21"/>
  </svg>
)

const ClockIcon = () => (
  <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <circle cx="12" cy="12" r="10"/>
    <polyline points="12 6 12 12 16 14"/>
  </svg>
)

function getMetrics(event: SessionEvent, t: (key: string) => string): ReactNode | null {
  const eventType = event.type || event.event_type || ""
  if (eventType === "span.model_request_end") return null

  const isTool = TOOL_USE_TYPES.has(eventType)
  const parts: ReactNode[] = []

  // Error badge for tool events with is_error
  if (event.is_error) {
    parts.push(
      <span key="error" className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400">
        {t("managed.sessions.roles.error")}
      </span>
    )
  }

  // Token usage — only for agent messages, not tools
  if (!isTool) {
    const usage = event.usage
    const input = usage?.input_tokens ?? event.input_tokens
    const output = usage?.output_tokens ?? event.output_tokens
    if (input || output) {
      parts.push(
        <span key="tokens" className="inline-flex items-center gap-1 text-xs text-muted-foreground font-mono">
          <MonitorIcon />
          {formatTokens(input || 0)} / {formatTokens(output || 0)}
        </span>
      )
    }
  }

  // Duration — only for tool events
  if (isTool) {
    const ms = event.duration_ms
    if (ms != null && ms > 0) {
      parts.push(
        <span key="duration" className="inline-flex items-center gap-1 text-xs text-muted-foreground font-mono">
          <ClockIcon />
          {ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`}
        </span>
      )
    }
  }

  return parts.length > 0 ? <>{parts}</> : null
}

function formatTokens(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`
  return String(n)
}
