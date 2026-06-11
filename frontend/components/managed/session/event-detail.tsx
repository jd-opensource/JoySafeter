'use client'

import type { SessionEvent } from "@/types/managed"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { useTranslation } from "@/lib/i18n"
import { RoleBadge } from "./role-badge"

interface EventDetailProps {
  event: SessionEvent
  mode: "transcript" | "debug"
  sessionStart?: string
  onClose: () => void
}

export function EventDetail({ event, mode, sessionStart, onClose }: EventDetailProps) {
  const { t } = useTranslation()
  const eventType = event.type || event.event_type || ""
  const typeLabel = getTypeLabel(eventType, t)
  const elapsed = sessionStart ? getElapsedTime(sessionStart, event.created_at || event.id || "") : null
  const shortId = event.id ? event.id.slice(0, 16) : ""

  return (
    <div className="h-full flex flex-col border-l border-border bg-card">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
        <div>
          <div className="flex items-center gap-2">
            <RoleBadge eventType={eventType} />
            <span className="text-sm font-medium text-foreground">
              {typeLabel}
            </span>
          </div>
          <div className="text-xs text-muted-foreground mt-1.5 space-y-0.5">
            {elapsed && <div>{elapsed}</div>}
            {mode === "debug" && shortId && (
              <div className="font-mono">{shortId}</div>
            )}
          </div>
        </div>
        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onClose}>
          <X className="w-4 h-4 text-muted-foreground" />
        </Button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4">
        {mode === "debug" ? (
          <div>
            <div className="text-xs text-muted-foreground mb-3 font-mono">{eventType}</div>
            <pre className="text-xs font-mono bg-muted p-3 rounded-lg overflow-x-auto whitespace-pre-wrap break-all leading-relaxed">
              <JsonHighlight json={event} />
            </pre>
          </div>
        ) : (
          <div>
            <h4 className="text-xs font-medium text-muted-foreground mb-3 uppercase tracking-wide">{t("managed.sessions.events.content")}</h4>
            <div className="prose prose-sm dark:prose-invert max-w-none">
              <TranscriptContent event={event} />
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function JsonHighlight({ json }: { json: unknown }) {
  const str = JSON.stringify(json, null, 2)
  const parts = str.split(/("(?:[^"\\]|\\.)*")\s*:/g)

  const elements: React.ReactNode[] = []
  for (let i = 0; i < parts.length; i++) {
    if (i % 2 === 1) {
      // This is a key
      elements.push(
        <span key={i} className="text-blue-400">{parts[i]}</span>
      )
      elements.push(":")
    } else {
      // Value part — highlight string values
      const valuePart = parts[i].replace(/"(?:[^"\\]|\\.)*"/g, (match) => {
        return `\x00STR_START\x00${match}\x00STR_END\x00`
      })
      const subParts = valuePart.split(/\x00STR_START\x00|\x00STR_END\x00/)
      for (let j = 0; j < subParts.length; j++) {
        if (j % 2 === 1) {
          elements.push(
            <span key={`${i}-${j}`} className="text-green-400">{subParts[j]}</span>
          )
        } else {
          // numbers, booleans, null
          const highlighted = subParts[j].replace(/\b(true|false|null)\b/g, '\x00BOOL\x00$1\x00ENDBOOL\x00')
            .replace(/:\s*(\d+(?:\.\d+)?)/g, ': \x00NUM\x00$1\x00ENDNUM\x00')
          const boolParts = highlighted.split(/\x00BOOL\x00|\x00ENDBOOL\x00|\x00NUM\x00|\x00ENDNUM\x00/)
          for (let k = 0; k < boolParts.length; k++) {
            if (k % 2 === 1) {
              elements.push(
                <span key={`${i}-${j}-${k}`} className="text-amber-400">{boolParts[k]}</span>
              )
            } else {
              elements.push(boolParts[k])
            }
          }
        }
      }
    }
  }

  return <>{elements}</>
}

function getTypeLabel(eventType: string, t: (key: string, options?: Record<string, unknown>) => string): string {
  const key = eventType.replace(/\./g, "_")
  const translated = t(`managed.sessions.eventTypes.${key}`)
  if (translated !== `managed.sessions.eventTypes.${key}`) return translated

  return eventType
}

function TranscriptContent({ event }: { event: SessionEvent }) {
  const text = extractText(event)

  if (!text) {
    return (
      <pre className="text-xs font-mono bg-muted p-3 rounded-lg overflow-x-auto">
        {JSON.stringify(event, null, 2)}
      </pre>
    )
  }

  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        pre: ({ children }) => (
          <pre className="overflow-x-auto rounded-lg border border-border bg-muted p-3 text-xs leading-relaxed text-foreground">
            {children}
          </pre>
        ),
        code: ({ children, className }) => (
          <code className={className ? "font-mono text-foreground" : "rounded bg-muted px-1 py-0.5 font-mono text-foreground"}>
            {children}
          </code>
        ),
      }}
    >
      {text}
    </ReactMarkdown>
  )
}

function extractText(event: SessionEvent): string | null {
  if (event.content && Array.isArray(event.content)) {
    return event.content
      .filter((c) => c.type === "text")
      .map((c) => c.text)
      .join("\n")
  }
  if (typeof event.content === "string") {
    return event.content
  }
  const eventType = event.type || event.event_type || ""
  if (eventType.includes("tool") && event.input) {
    return "```json\n" + JSON.stringify(event.input, null, 2) + "\n```"
  }
  if (eventType.includes("tool") && event.output) {
    return "```json\n" + JSON.stringify(event.output, null, 2) + "\n```"
  }
  return null
}

function getElapsedTime(start: string, current: string): string | null {
  const startMs = parseEventTime(start)
  const currentMs = parseEventTime(current)
  if (isNaN(startMs) || isNaN(currentMs)) return null
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
