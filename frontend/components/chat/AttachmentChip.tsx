'use client'

import { X, FileIcon } from 'lucide-react'
import { cn } from '@/lib/utils'

interface AttachmentChipProps {
  filename: string
  mimeType: string
  sizeBytes: number
  uploading?: boolean
  onRemove?: () => void
}

export function AttachmentChip({
  filename,
  mimeType,
  sizeBytes,
  uploading,
  onRemove,
}: AttachmentChipProps) {
  const sizeLabel =
    sizeBytes < 1024 * 1024
      ? `${(sizeBytes / 1024).toFixed(0)} KB`
      : `${(sizeBytes / (1024 * 1024)).toFixed(1)} MB`

  return (
    <div
      className={cn(
        'inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--surface-2)] px-2 py-1 text-xs',
        uploading && 'opacity-60',
      )}
    >
      <FileIcon className="h-3 w-3 text-[var(--text-muted)]" />
      <span className="max-w-[120px] truncate text-[var(--text-primary)]">{filename}</span>
      <span className="text-[var(--text-muted)]">{sizeLabel}</span>
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          className="ml-0.5 rounded p-0.5 hover:bg-[var(--surface-3)]"
        >
          <X className="h-3 w-3" />
        </button>
      )}
    </div>
  )
}
