'use client'

import { useRef, useCallback, useEffect, useState } from 'react'
import type { SessionEvent } from '@/types/managed'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { X, Copy, Check } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useTranslation } from '@/lib/i18n'
import { eventIdTimestamp, shortEntityId } from '@/lib/managed/entity-id-display'
import { parseEventId } from '@/types/entity-id'
import { RoleBadge } from './role-badge'

interface EventDetailProps {
  event: SessionEvent
  mode: 'transcript' | 'debug'
  sessionStart?: string
  onClose: () => void
}

export function EventDetail({ event, mode, sessionStart, onClose }: EventDetailProps) {
  const { t } = useTranslation()
  const contentRef = useRef<HTMLDivElement>(null)
  const copiedResetTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [copied, setCopied] = useState(false)
  const eventType = event.type
  const typeLabel = getTypeLabel(eventType, t)
  const elapsed = sessionStart
    ? getElapsedTime(sessionStart, event.created_at || event.id || '')
    : null
  const shortId = event.id ? shortEntityId(event.id, 'event', 12) : ''

  useEffect(
    () => () => {
      if (copiedResetTimerRef.current) {
        clearTimeout(copiedResetTimerRef.current)
      }
    },
    [],
  )

  const showCopiedFeedback = useCallback(() => {
    if (copiedResetTimerRef.current) {
      clearTimeout(copiedResetTimerRef.current)
    }
    setCopied(true)
    copiedResetTimerRef.current = setTimeout(() => {
      setCopied(false)
      copiedResetTimerRef.current = null
    }, 2000)
  }, [])

  const handleCopyRichText = useCallback(async () => {
    if (!contentRef.current) return
    try {
      // Get the rendered HTML for rich text copy
      const html = contentRef.current.innerHTML
      // Also get plain text fallback
      const plainText = contentRef.current.innerText || contentRef.current.textContent || ''

      // Use Clipboard API with both HTML and plain text MIME types
      const blob = new Blob([html], { type: 'text/html' })
      const textBlob = new Blob([plainText], { type: 'text/plain' })
      await navigator.clipboard.write([
        new ClipboardItem({
          'text/html': blob,
          'text/plain': textBlob,
        }),
      ])
      showCopiedFeedback()
    } catch {
      // Fallback: copy plain text
      const text = contentRef.current.innerText || contentRef.current.textContent || ''
      await navigator.clipboard.writeText(text)
      showCopiedFeedback()
    }
  }, [showCopiedFeedback])

  return (
    <div className="flex h-full flex-col border-l border-border bg-card">
      {/* Header */}
      <div className="flex shrink-0 items-center justify-between border-b border-border px-4 py-3">
        <div>
          <div className="flex items-center gap-2">
            <RoleBadge eventType={eventType} />
            <span className="text-sm font-medium text-foreground">{typeLabel}</span>
          </div>
          <div className="mt-1.5 space-y-0.5 text-xs text-muted-foreground">
            {elapsed && <div>{elapsed}</div>}
            {mode === 'debug' && shortId && <div className="font-mono">{shortId}</div>}
          </div>
        </div>
        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onClose}>
          <X className="h-4 w-4 text-muted-foreground" />
        </Button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4">
        {mode === 'debug' ? (
          <div>
            <div className="mb-3 font-mono text-xs text-muted-foreground">{eventType}</div>
            <pre className="overflow-x-auto whitespace-pre-wrap break-all rounded-lg bg-muted p-3 font-mono text-xs leading-relaxed">
              <JsonHighlight json={event} />
            </pre>
          </div>
        ) : (
          <div>
            <div className="mb-3 flex items-center justify-between">
              <h4 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                {t('managed.sessions.events.content')}
              </h4>
              <Button
                variant="ghost"
                size="sm"
                className="h-7 gap-1.5 text-xs text-muted-foreground hover:text-foreground"
                onClick={handleCopyRichText}
              >
                {copied ? (
                  <>
                    <Check className="h-3.5 w-3.5 text-green-500" />
                    <span className="text-green-500">{t('common.copied')}</span>
                  </>
                ) : (
                  <>
                    <Copy className="h-3.5 w-3.5" />
                    <span>{t('common.copy')}</span>
                  </>
                )}
              </Button>
            </div>
            <div ref={contentRef} className="prose prose-sm max-w-none dark:prose-invert">
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
        <span key={i} className="text-blue-400">
          {parts[i]}
        </span>,
      )
      elements.push(':')
    } else {
      // Value part — highlight string values
      const valuePart = parts[i].replace(/"(?:[^"\\]|\\.)*"/g, (match) => {
        return `\x00STR_START\x00${match}\x00STR_END\x00`
      })
      const subParts = valuePart.split(/\x00STR_START\x00|\x00STR_END\x00/)
      for (let j = 0; j < subParts.length; j++) {
        if (j % 2 === 1) {
          elements.push(
            <span key={`${i}-${j}`} className="text-green-400">
              {subParts[j]}
            </span>,
          )
        } else {
          // numbers, booleans, null
          const highlighted = subParts[j]
            .replace(/\b(true|false|null)\b/g, '\x00BOOL\x00$1\x00ENDBOOL\x00')
            .replace(/:\s*(\d+(?:\.\d+)?)/g, ': \x00NUM\x00$1\x00ENDNUM\x00')
          const boolParts = highlighted.split(
            /\x00BOOL\x00|\x00ENDBOOL\x00|\x00NUM\x00|\x00ENDNUM\x00/,
          )
          for (let k = 0; k < boolParts.length; k++) {
            if (k % 2 === 1) {
              elements.push(
                <span key={`${i}-${j}-${k}`} className="text-amber-400">
                  {boolParts[k]}
                </span>,
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

function getTypeLabel(
  eventType: string,
  t: (key: string, options?: Record<string, unknown>) => string,
): string {
  const key = eventType.replace(/\./g, '_')
  const translated = t(`managed.sessions.eventTypes.${key}`)
  if (translated !== `managed.sessions.eventTypes.${key}`) return translated

  return eventType
}

function TranscriptContent({ event }: { event: SessionEvent }) {
  const text = extractText(event)

  if (!text) {
    return (
      <pre className="overflow-x-auto rounded-lg bg-muted p-3 font-mono text-xs">
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
          <code
            className={
              className
                ? 'font-mono text-foreground'
                : 'rounded bg-muted px-1 py-0.5 font-mono text-foreground'
            }
          >
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
  const eventTypeForBg = event.type
  if (
    eventTypeForBg === 'agent.bg_task_started' ||
    eventTypeForBg === 'agent.bg_task_progress' ||
    eventTypeForBg === 'agent.bg_task_finished'
  ) {
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
    lines.push('')
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
      lines.push('')
      lines.push('### Result')
      lines.push('')
      lines.push(ev.result)
    }
    return lines.join('\n')
  }

  if (event.content && Array.isArray(event.content)) {
    return event.content
      .filter((c) => c.type === 'text')
      .map((c) => c.text)
      .join('\n')
  }
  if (typeof event.content === 'string') {
    return event.content
  }
  const eventType = event.type
  if (eventType.includes('tool') && event.input) {
    return renderToolInputMarkdown(event)
  }
  if (eventType.includes('tool') && event.output) {
    return '```json\n' + JSON.stringify(event.output, null, 2) + '\n```'
  }
  return null
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
 */
function renderToolInputMarkdown(event: SessionEvent): string {
  if (!event.input || typeof event.input !== 'object') {
    return '```json\n' + JSON.stringify(event.input, null, 2) + '\n```'
  }
  const input = event.input as Record<string, unknown>
  const toolName = String(event.tool || event.tool_name || event.name || '')

  // Bash — claude-code shows the command text plain. Use a bash fence
  // for monospaced syntax highlighting; description (if present, e.g.
  // from a `# label` comment) goes underneath as italic.
  if (toolName === 'Bash' && typeof input.command === 'string') {
    const command = input.command as string
    const out = ['```bash', command, '```']
    if (typeof input.description === 'string' && input.description) {
      out.push('', `_${input.description}_`)
    }
    return out.join('\n')
  }

  // Grep — cc renders: pattern: "...", path: "..."
  if (toolName === 'Grep') {
    const parts: string[] = []
    if (input.pattern) parts.push(`pattern: "${String(input.pattern)}"`)
    if (input.path) parts.push(`path: "${String(input.path)}"`)
    if (input.glob) parts.push(`glob: "${String(input.glob)}"`)
    if (input.output_mode) parts.push(`mode: ${String(input.output_mode)}`)
    if (input.type) parts.push(`type: ${String(input.type)}`)
    return parts.length > 0
      ? parts.join(', ')
      : '```json\n' + JSON.stringify(input, null, 2) + '\n```'
  }

  // Read — cc renders: path  · lines X-Y  · pages 1-3
  if (toolName === 'Read' && typeof input.file_path === 'string') {
    const segs: string[] = [`\`${input.file_path as string}\``]
    if (input.pages) segs.push(`pages ${String(input.pages)}`)
    if (input.offset != null || input.limit != null) {
      const start = (input.offset as number) ?? 1
      const end = input.limit != null ? start + (input.limit as number) - 1 : null
      segs.push(end ? `lines ${start}-${end}` : `from line ${start}`)
    }
    return segs.join(' · ')
  }

  // Write — file path + content fence
  if (toolName === 'Write' && typeof input.file_path === 'string') {
    const lang = guessFenceLang(input.file_path as string)
    return [
      `\`${input.file_path as string}\``,
      '',
      '```' + lang,
      String(input.content ?? ''),
      '```',
    ].join('\n')
  }

  // Edit — file path + old/new fences (cc shows them as a colored diff in TUI)
  if (toolName === 'Edit' && typeof input.file_path === 'string') {
    const lang = guessFenceLang(input.file_path as string)
    const out: string[] = [`\`${input.file_path as string}\``]
    if (input.old_string) {
      out.push('', '_— old —_', '```' + lang, String(input.old_string), '```')
    }
    if (input.new_string) {
      out.push('', '_+ new +_', '```' + lang, String(input.new_string), '```')
    }
    if (input.replace_all) out.push('', '_replace_all_')
    return out.join('\n')
  }

  // Glob — pattern: "...", path: "..."
  if (toolName === 'Glob') {
    const parts: string[] = []
    if (input.pattern) parts.push(`pattern: "${String(input.pattern)}"`)
    if (input.path) parts.push(`path: "${String(input.path)}"`)
    return parts.length > 0
      ? parts.join(', ')
      : '```json\n' + JSON.stringify(input, null, 2) + '\n```'
  }

  // WebFetch — url + prompt
  if (toolName === 'WebFetch') {
    const parts: string[] = []
    if (input.url) parts.push(`${String(input.url)}`)
    if (input.prompt) parts.push('', `_${String(input.prompt)}_`)
    return parts.join('\n')
  }
  if (toolName === 'WebSearch' && input.query) {
    return `"${String(input.query)}"`
  }

  // Task / Agent — sub-agent dispatch
  if (toolName === 'Task' || toolName === 'Agent') {
    const out: string[] = []
    if (input.description) out.push(String(input.description))
    const meta: string[] = []
    if (input.subagent_type) meta.push(`subagent: \`${String(input.subagent_type)}\``)
    if (input.model) meta.push(`model: \`${String(input.model)}\``)
    if (input.run_in_background) meta.push('background')
    if (meta.length) out.push(meta.join(' · '))
    if (input.prompt) out.push('', String(input.prompt))
    return out.join('\n')
  }

  // TodoWrite — list
  if (toolName === 'TodoWrite' && Array.isArray(input.todos)) {
    return (input.todos as Array<Record<string, unknown>>)
      .map((t) => {
        const status = String(t.status || '')
        const icon = status === 'completed' ? '✅' : status === 'in_progress' ? '🔵' : '⏳'
        return `${icon} ${String(t.content || t.subject || '')}`
      })
      .join('\n')
  }

  return '```json\n' + JSON.stringify(input, null, 2) + '\n```'
}

function guessFenceLang(filePath: string): string {
  const ext = filePath.split('.').pop()?.toLowerCase() ?? ''
  const map: Record<string, string> = {
    ts: 'ts',
    tsx: 'tsx',
    js: 'js',
    jsx: 'jsx',
    py: 'python',
    go: 'go',
    rs: 'rust',
    java: 'java',
    c: 'c',
    cpp: 'cpp',
    h: 'c',
    hpp: 'cpp',
    sh: 'bash',
    bash: 'bash',
    zsh: 'bash',
    yml: 'yaml',
    yaml: 'yaml',
    json: 'json',
    md: 'markdown',
    toml: 'toml',
    sql: 'sql',
    html: 'html',
    css: 'css',
    scss: 'scss',
    rb: 'ruby',
    php: 'php',
    kt: 'kotlin',
    swift: 'swift',
  }
  return map[ext] || ''
}

function getElapsedTime(start: string, current: string): string | null {
  const startMs = parseEventTime(start)
  const currentMs = parseEventTime(current)
  if (isNaN(startMs) || isNaN(currentMs)) return null
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
  try {
    return eventIdTimestamp(parseEventId(value)) ?? NaN
  } catch {
    return NaN
  }
}
