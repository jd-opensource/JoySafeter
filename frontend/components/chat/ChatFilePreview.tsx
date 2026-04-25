'use client'

import { FileIcon, Download } from 'lucide-react'
import { API_BASE } from '@/lib/api-client'

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
    ['application/javascript', 'application/typescript', 'application/xml'].includes(
      mime,
    )
  )
}

export function ChatFilePreview({
  filename,
  storageRef,
  mimeType,
  sizeBytes,
}: ChatFilePreviewProps) {
  // Use the basename from storage_ref or filename — the backend's read endpoint
  // resolves files relative to the user's sandbox upload directory.
  const basename = filename.split('/').pop() || filename
  const rawUrl = `${API_BASE}/files/read/${encodeURIComponent(basename)}?mode=raw`
  const sizeLabel =
    sizeBytes < 1024 * 1024
      ? `${(sizeBytes / 1024).toFixed(0)} KB`
      : `${(sizeBytes / (1024 * 1024)).toFixed(1)} MB`

  if (isImage(mimeType)) {
    return (
      <div className="mt-2 max-w-sm">
        <img
          src={rawUrl}
          alt={filename}
          className="max-h-64 rounded-md border border-[var(--border)] object-contain"
          loading="lazy"
        />
        <p className="mt-1 text-xs text-[var(--text-muted)]">
          {filename} ({sizeLabel})
        </p>
      </div>
    )
  }

  if (isText(mimeType)) {
    return (
      <div className="mt-2 max-w-md">
        <div className="flex items-center justify-between rounded-t-md border border-[var(--border)] bg-[var(--surface-3)] px-3 py-1.5">
          <span className="text-xs font-medium text-[var(--text-primary)]">
            {filename}
          </span>
          <span className="text-xs text-[var(--text-muted)]">{sizeLabel}</span>
        </div>
        <a
          href={rawUrl}
          target="_blank"
          rel="noreferrer"
          className="block rounded-b-md border border-t-0 border-[var(--border)] bg-[var(--surface-2)] p-3 text-xs text-[var(--text-muted)] hover:text-[var(--text-primary)]"
        >
          Click to view content
        </a>
      </div>
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
