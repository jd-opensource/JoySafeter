'use client'

import { useRef, useCallback, useState } from "react"
import type { SessionEvent } from "@/types/managed"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { X, Copy, Check } from "lucide-react"
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
  const contentRef = useRef<HTMLDivElement>(null)
  const [copied, setCopied] = useState(false)
  const eventType = event.type || event.event_type || ""
  const typeLabel = getTypeLabel(eventType, t)
  const elapsed = sessionStart ? getElapsedTime(sessionStart, event.created_at || event.id || "") : null
  const shortId = event.id ? event.id.slice(0, 16) : ""

  const handleCopyRichText = useCallback(async () => {
    if (!contentRef.current) return
    try {
      // Get the rendered HTML for rich text copy
      const html = contentRef.current.innerHTML
      // Also get plain text fallback
      const plainText = contentRef.current.innerText || contentRef.current.textContent || ""

      // Use Clipboard API with both HTML and plain text MIME types
      const blob = new Blob([html], { type: "text/html" })
      const textBlob = new Blob([plainText], { type: "text/plain" })
      await navigator.clipboard.write([
        new ClipboardItem({
          "text/html": blob,
          "text/plain": textBlob,
        }),
      ])
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // Fallback: copy plain text
      const text = contentRef.current.innerText || contentRef.current.textContent || ""
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }, [])

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
            <div className="flex items-center justify-between mb-3">
              <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wide">{t("managed.sessions.events.content")}</h4>
              <Button
                variant="ghost"
                size="sm"
                className="h-7 gap-1.5 text-xs text-muted-foreground hover:text-foreground"
                onClick={handleCopyRichText}
              >
                {copied ? (
                  <>
                    <Check className="w-3.5 h-3.5 text-green-500" />
                    <span className="text-green-500">{t("common.copied")}</span>
                  </>
                ) : (
                  <>
                    <Copy className="w-3.5 h-3.5" />
                    <span>{t("common.copy")}</span>
                  </>
                )}
              </Button>
            </div>
            <div ref={contentRef} className="prose prose-sm dark:prose-invert max-w-none">
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
  // Background sub-agent — render a structured markdown card with all known fields
  const eventTypeForBg = event.type || event.event_type || ""
  if (eventTypeForBg === "session.error") {
    return renderSessionErrorMarkdown(event)
  }

  if (eventTypeForBg === "agent.bg_task_started"
      || eventTypeForBg === "agent.bg_task_progress"
      || eventTypeForBg === "agent.bg_task_finished") {
    const ev = event as unknown as {
      phase?: string
      description?: string
      task_id?: string
      tool_use_id?: string
      status?: string
      summary?: string
      result?: string
      output_file?: string
      last_tool_name?: string
      total_tokens?: number
      tool_uses?: number
      duration_ms?: number
    }
    const lines: string[] = []
    if (ev.summary) lines.push(`**${ev.summary}**`)
    else if (ev.description) lines.push(`**${ev.description}**`)
    lines.push("")
    if (ev.phase) lines.push(`- phase: \`${ev.phase}\``)
    if (ev.status) lines.push(`- status: \`${ev.status}\``)
    if (ev.task_id) lines.push(`- task_id: \`${ev.task_id}\``)
    if (ev.tool_use_id) lines.push(`- tool_use_id: \`${ev.tool_use_id}\``)
    if (ev.last_tool_name) lines.push(`- last_tool: \`${ev.last_tool_name}\``)
    if (ev.output_file) lines.push(`- output_file: \`${ev.output_file}\``)
    if (ev.total_tokens != null) lines.push(`- total_tokens: ${ev.total_tokens}`)
    if (ev.tool_uses != null) lines.push(`- tool_uses: ${ev.tool_uses}`)
    if (ev.duration_ms != null) lines.push(`- duration: ${ev.duration_ms} ms`)
    if (ev.result) {
      lines.push("")
      lines.push("### Result")
      lines.push("")
      lines.push(ev.result)
    }
    return lines.join("\n")
  }

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
    return renderToolInputMarkdown(event)
  }
  if (eventType.includes("tool") && event.output) {
    return "```json\n" + JSON.stringify(event.output, null, 2) + "\n```"
  }
  return null
}

function renderSessionErrorMarkdown(event: SessionEvent): string | null {
  const rawError = event.error ?? (
    event.payload && typeof event.payload === "object"
      ? (event.payload as Record<string, unknown>).error
      : undefined
  )

  if (typeof rawError === "string") {
    return rawError
  }
  if (!rawError || typeof rawError !== "object") {
    return null
  }

  const error = rawError as Record<string, unknown>
  const lines: string[] = []
  const message = stringValue(error.message)
  const type = stringValue(error.type)
  const code = stringValue(error.code)
  const status = stringValue(error.status_code ?? error.status ?? error.http_status)
  const retryStatus = error.retry_status && typeof error.retry_status === "object"
    ? stringValue((error.retry_status as Record<string, unknown>).type)
    : null

  if (message) lines.push(message)
  else if (type) lines.push(`模型调用失败: ${type}`)

  const details: string[] = []
  if (type) details.push(`- type: \`${type}\``)
  if (status) details.push(`- status: \`${status}\``)
  if (code) details.push(`- code: \`${code}\``)
  if (retryStatus) details.push(`- retry: \`${retryStatus}\``)
  if (details.length > 0) {
    if (lines.length > 0) lines.push("")
    lines.push(...details)
  }

  const upstream = error.upstream_body ?? error.upstream_response ?? error.details
  const upstreamText = formatUnknownDiagnostic(upstream)
  if (upstreamText) {
    lines.push("")
    lines.push("### Upstream response")
    lines.push("")
    lines.push("```json")
    lines.push(upstreamText)
    lines.push("```")
  }

  return lines.length > 0 ? lines.join("\n") : null
}

function stringValue(value: unknown): string | null {
  if (value == null) return null
  if (typeof value === "string") return value
  if (typeof value === "number" || typeof value === "boolean") return String(value)
  return null
}

function formatUnknownDiagnostic(value: unknown): string | null {
  if (value == null) return null
  if (typeof value === "string") {
    const trimmed = value.trim()
    if (!trimmed) return null
    try {
      return JSON.stringify(JSON.parse(trimmed), null, 2)
    } catch {
      return trimmed
    }
  }
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

/**
 * Render a tool_use event's input in human-readable form.
 *
 * Mirrors claude-code's per-tool TUI renderers (src/tools/<X>Tool/UI.tsx
 * `renderToolUseMessage`). The cc style is intentionally minimal:
 *   • Bash → just the command text (in a fenced bash block here for syntax)
 *   • Grep → `pattern: "...", path: "..."` single line
 *   • Read → `path · lines a-b` dot-joined
 *   • Write/Edit → file path + diff in fenced block
 *   • Task/Agent → description + prompt
 *
 * Bold/headings are avoided — they over-format what should read like
 * a terminal command echo. Falls back to fenced JSON for unknown tools.
 *
 * Handles two payload shapes — input may be a parsed object (current) or a
 * doubly-encoded JSON string (legacy events from before orchestrator-rs
 * mapping.rs parsed input_json server-side).
 */
function renderToolInputMarkdown(event: SessionEvent): string {
  let raw = event.input as unknown
  if (typeof raw === "string") {
    try {
      raw = JSON.parse(raw)
    } catch {
      return "```\n" + (raw as string) + "\n```"
    }
  }
  if (!raw || typeof raw !== "object") {
    return "```json\n" + JSON.stringify(event.input, null, 2) + "\n```"
  }
  const input = raw as Record<string, unknown>
  const toolName = String(event.tool || event.tool_name || event.name || "")

  // Bash — claude-code shows the command text plain. Use a bash fence
  // for monospaced syntax highlighting; description (if present, e.g.
  // from a `# label` comment) goes underneath as italic.
  if (toolName === "Bash" && typeof input.command === "string") {
    const command = input.command as string
    const out = ["```bash", command, "```"]
    if (typeof input.description === "string" && input.description) {
      out.push("", `_${input.description}_`)
    }
    return out.join("\n")
  }

  // Grep — cc renders: pattern: "...", path: "..."
  if (toolName === "Grep") {
    const parts: string[] = []
    if (input.pattern) parts.push(`pattern: "${String(input.pattern)}"`)
    if (input.path) parts.push(`path: "${String(input.path)}"`)
    if (input.glob) parts.push(`glob: "${String(input.glob)}"`)
    if (input.output_mode) parts.push(`mode: ${String(input.output_mode)}`)
    if (input.type) parts.push(`type: ${String(input.type)}`)
    return parts.length > 0
      ? parts.join(", ")
      : "```json\n" + JSON.stringify(input, null, 2) + "\n```"
  }

  // Read — cc renders: path  · lines X-Y  · pages 1-3
  if (toolName === "Read" && typeof input.file_path === "string") {
    const segs: string[] = [`\`${input.file_path as string}\``]
    if (input.pages) segs.push(`pages ${String(input.pages)}`)
    if (input.offset != null || input.limit != null) {
      const start = (input.offset as number) ?? 1
      const end = input.limit != null ? start + (input.limit as number) - 1 : null
      segs.push(end ? `lines ${start}-${end}` : `from line ${start}`)
    }
    return segs.join(" · ")
  }

  // Write — file path + content fence
  if (toolName === "Write" && typeof input.file_path === "string") {
    const lang = guessFenceLang(input.file_path as string)
    return [
      `\`${input.file_path as string}\``,
      "",
      "```" + lang,
      String(input.content ?? ""),
      "```",
    ].join("\n")
  }

  // Edit — file path + old/new fences (cc shows them as a colored diff in TUI)
  if (toolName === "Edit" && typeof input.file_path === "string") {
    const lang = guessFenceLang(input.file_path as string)
    const out: string[] = [`\`${input.file_path as string}\``]
    if (input.old_string) {
      out.push("", "_— old —_", "```" + lang, String(input.old_string), "```")
    }
    if (input.new_string) {
      out.push("", "_+ new +_", "```" + lang, String(input.new_string), "```")
    }
    if (input.replace_all) out.push("", "_replace_all_")
    return out.join("\n")
  }

  // Glob — pattern: "...", path: "..."
  if (toolName === "Glob") {
    const parts: string[] = []
    if (input.pattern) parts.push(`pattern: "${String(input.pattern)}"`)
    if (input.path) parts.push(`path: "${String(input.path)}"`)
    return parts.length > 0
      ? parts.join(", ")
      : "```json\n" + JSON.stringify(input, null, 2) + "\n```"
  }

  // WebFetch — url + prompt
  if (toolName === "WebFetch") {
    const parts: string[] = []
    if (input.url) parts.push(`${String(input.url)}`)
    if (input.prompt) parts.push("", `_${String(input.prompt)}_`)
    return parts.join("\n")
  }
  if (toolName === "WebSearch" && input.query) {
    return `"${String(input.query)}"`
  }

  // Task / Agent — sub-agent dispatch
  if (toolName === "Task" || toolName === "Agent") {
    const out: string[] = []
    if (input.description) out.push(String(input.description))
    const meta: string[] = []
    if (input.subagent_type) meta.push(`subagent: \`${String(input.subagent_type)}\``)
    if (input.model) meta.push(`model: \`${String(input.model)}\``)
    if (input.run_in_background) meta.push("background")
    if (meta.length) out.push(meta.join(" · "))
    if (input.prompt) out.push("", String(input.prompt))
    return out.join("\n")
  }

  // TodoWrite — list
  if (toolName === "TodoWrite" && Array.isArray(input.todos)) {
    return (input.todos as Array<Record<string, unknown>>)
      .map((t) => {
        const status = String(t.status || "")
        const icon = status === "completed" ? "✅" : status === "in_progress" ? "🔵" : "⏳"
        return `${icon} ${String(t.content || t.subject || "")}`
      })
      .join("\n")
  }

  return "```json\n" + JSON.stringify(input, null, 2) + "\n```"
}

function guessFenceLang(filePath: string): string {
  const ext = filePath.split(".").pop()?.toLowerCase() ?? ""
  const map: Record<string, string> = {
    ts: "ts", tsx: "tsx", js: "js", jsx: "jsx",
    py: "python", go: "go", rs: "rust", java: "java",
    c: "c", cpp: "cpp", h: "c", hpp: "cpp",
    sh: "bash", bash: "bash", zsh: "bash",
    yml: "yaml", yaml: "yaml", json: "json", md: "markdown",
    toml: "toml", sql: "sql", html: "html", css: "css", scss: "scss",
    rb: "ruby", php: "php", kt: "kotlin", swift: "swift",
  }
  return map[ext] || ""
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
