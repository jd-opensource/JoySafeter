'use client'

import { FileIcon, Download, Loader2, ChevronDown } from 'lucide-react'
import { useEffect, useState } from 'react'
import { API_BASE, createApiError } from '@/lib/api-client'
import { cn } from '@/lib/utils'

interface ChatFilePreviewProps {
  filename: string
  storageRef: string
  mimeType: string
  sizeBytes: number
}

function isImage(mime: string) {
  return mime.startsWith('image/')
}

function isText(mime: string) {
  return (
    mime.startsWith('text/') ||
    mime === 'application/json' ||
    mime === 'application/xml' ||
    mime === 'application/javascript' ||
    mime === 'application/typescript' ||
    mime === 'application/x-yaml' ||
    mime === 'application/x-sh'
  )
}

function isPdf(mime: string) {
  return mime === 'application/pdf'
}

const MAX_PREVIEW_LINES = 50

export function ChatFilePreview({
  filename,
  storageRef,
  mimeType,
  sizeBytes,
}: ChatFilePreviewProps) {
  const basename = filename.split('/').pop() || filename
  const rawUrl = `${API_BASE}/files/read/${encodeURIComponent(basename)}?mode=raw`
  const sizeLabel =
    sizeBytes < 1024 * 1024
      ? `${(sizeBytes / 1024).toFixed(0)} KB`
      : `${(sizeBytes / (1024 * 1024)).toFixed(1)} MB`

  if (isImage(mimeType)) {
    return <ImagePreview rawUrl={rawUrl} filename={filename} sizeLabel={sizeLabel} />
  }

  if (isPdf(mimeType)) {
    return <PdfPreview rawUrl={rawUrl} filename={filename} sizeLabel={sizeLabel} />
  }

  if (isText(mimeType)) {
    return (
      <TextPreview
        rawUrl={rawUrl}
        filename={filename}
        sizeLabel={sizeLabel}
        sizeBytes={sizeBytes}
      />
    )
  }

  return (
    <a
      href={rawUrl}
      download={filename}
      className="mt-2 inline-flex items-center gap-2 rounded-md border border-[var(--border)] bg-[var(--surface-2)] px-3 py-2 text-xs hover:bg-[var(--surface-3)]"
    >
      <FileIcon className="h-4 w-4 text-[var(--text-muted)]" />
      <span className="text-[var(--text-primary)]">{filename}</span>
      <span className="text-[var(--text-muted)]">{sizeLabel}</span>
      <Download className="h-3 w-3 text-[var(--text-muted)]" />
    </a>
  )
}

function ImagePreview({
  rawUrl,
  filename,
  sizeLabel,
}: {
  rawUrl: string
  filename: string
  sizeLabel: string
}) {
  const [fullscreen, setFullscreen] = useState(false)

  return (
    <>
      <div className="mt-2 max-w-sm">
        <button
          type="button"
          onClick={() => setFullscreen(true)}
          className="block w-full overflow-hidden rounded-md border border-[var(--border)] hover:opacity-90"
        >
          <img
            src={rawUrl}
            alt={filename}
            className="max-h-64 w-full object-contain"
            loading="lazy"
          />
        </button>
        <p className="mt-1 text-xs text-[var(--text-muted)]">
          {filename} ({sizeLabel})
        </p>
      </div>
      {fullscreen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80"
          onClick={() => setFullscreen(false)}
        >
          <img
            src={rawUrl}
            alt={filename}
            className="max-h-[90vh] max-w-[90vw] object-contain"
          />
        </div>
      )}
    </>
  )
}

function PdfPreview({
  rawUrl,
  filename,
  sizeLabel,
}: {
  rawUrl: string
  filename: string
  sizeLabel: string
}) {
  const [open, setOpen] = useState(false)

  return (
    <div className="mt-2 max-w-md">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between rounded-md border border-[var(--border)] bg-[var(--surface-2)] px-3 py-2 text-xs hover:bg-[var(--surface-3)]"
      >
        <span className="flex items-center gap-2">
          <FileIcon className="h-4 w-4 text-red-400" />
          <span className="text-[var(--text-primary)]">{filename}</span>
          <span className="text-[var(--text-muted)]">{sizeLabel}</span>
        </span>
        <ChevronDown
          className={cn('h-3 w-3 transition-transform', open && 'rotate-180')}
        />
      </button>
      {open && (
        <iframe
          src={rawUrl}
          title={filename}
          className="mt-1 h-96 w-full rounded-md border border-[var(--border)]"
        />
      )}
    </div>
  )
}

function TextPreview({
  rawUrl,
  filename,
  sizeLabel,
  sizeBytes,
}: {
  rawUrl: string
  filename: string
  sizeLabel: string
  sizeBytes: number
}) {
  const [content, setContent] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState(false)
  const [open, setOpen] = useState(sizeBytes < 50 * 1024) // Auto-open small files

  useEffect(() => {
    if (!open || content !== null) return
    setLoading(true)
    fetch(rawUrl, { credentials: 'include' })
      .then((r) => {
        if (!r.ok) {
          throw createApiError(r.status, r.statusText, {
            code: 'FILE_PREVIEW_LOAD_FAILED',
            message: 'Failed to load file preview',
            data: { filename },
          })
        }
        return r.text()
      })
      .then((text) => {
        setContent(text)
        setError(null)
      })
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load'))
      .finally(() => setLoading(false))
  }, [open, rawUrl, content])

  const lines = content?.split('\n') ?? []
  const displayed =
    expanded || lines.length <= MAX_PREVIEW_LINES
      ? lines
      : lines.slice(0, MAX_PREVIEW_LINES)
  const hasMore = lines.length > MAX_PREVIEW_LINES

  return (
    <div className="mt-2 max-w-md">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between rounded-t-md border border-[var(--border)] bg-[var(--surface-3)] px-3 py-1.5 hover:bg-[var(--surface-4)]"
      >
        <span className="flex items-center gap-2 text-xs">
          <FileIcon className="h-3 w-3 text-[var(--text-muted)]" />
          <span className="font-medium text-[var(--text-primary)]">
            {filename}
          </span>
          <span className="text-[var(--text-muted)]">{sizeLabel}</span>
        </span>
        <ChevronDown
          className={cn(
            'h-3 w-3 text-[var(--text-muted)] transition-transform',
            open && 'rotate-180',
          )}
        />
      </button>
      {open && (
        <div className="rounded-b-md border border-t-0 border-[var(--border)] bg-[var(--surface-2)]">
          {loading && (
            <div className="flex items-center gap-2 px-3 py-3 text-xs text-[var(--text-muted)]">
              <Loader2 className="h-3 w-3 animate-spin" /> Loading…
            </div>
          )}
          {error && (
            <div className="px-3 py-3 text-xs text-red-400">
              Failed: {error}
            </div>
          )}
          {content !== null && (
            <>
              <pre className="max-h-96 overflow-auto p-3 text-xs text-[var(--text-primary)]">
                {displayed.join('\n')}
              </pre>
              {hasMore && (
                <button
                  type="button"
                  onClick={() => setExpanded(!expanded)}
                  className="block w-full border-t border-[var(--border)] px-3 py-1.5 text-center text-xs text-[var(--text-muted)] hover:bg-[var(--surface-3)]"
                >
                  {expanded
                    ? `Show less (showing ${lines.length} lines)`
                    : `Show all ${lines.length} lines (${lines.length - MAX_PREVIEW_LINES} more)`}
                </button>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}
