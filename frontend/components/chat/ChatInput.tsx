'use client'

import { Paperclip, Send, Loader2, Upload } from 'lucide-react'
import { useCallback, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { AttachmentChip } from './AttachmentChip'
import { useTranslation } from '@/lib/i18n'
import { UPLOAD_LIMITS, ALLOWED_MIME_TYPES } from '@/lib/core/constants/upload-limits'
import { cn } from '@/lib/utils'

interface ChatInputProps {
  onSend: (message: string, files: File[]) => void
  disabled?: boolean
}

export function ChatInput({ onSend, disabled }: ChatInputProps) {
  const { t } = useTranslation()
  const [text, setText] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [isDragOver, setIsDragOver] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const handleSend = useCallback(() => {
    if (!text.trim() && files.length === 0) return
    onSend(text.trim(), files)
    setText('')
    setFiles([])
  }, [text, files, onSend])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const addFiles = (newFiles: FileList | File[]) => {
    const incoming = Array.from(newFiles)
    const valid: File[] = []
    const rejected: string[] = []

    for (const f of incoming) {
      if (f.size > UPLOAD_LIMITS.MAX_FILE_SIZE_BYTES) {
        rejected.push(`${f.name}: exceeds ${UPLOAD_LIMITS.MAX_FILE_SIZE_MB}MB`)
        continue
      }
      if (f.type && !(ALLOWED_MIME_TYPES as readonly string[]).includes(f.type)) {
        rejected.push(`${f.name}: unsupported type (${f.type})`)
        continue
      }
      valid.push(f)
    }

    if (rejected.length > 0) {
      console.warn('Rejected files:', rejected)
    }

    setFiles((prev) => [...prev, ...valid].slice(0, UPLOAD_LIMITS.MAX_FILES_PER_UPLOAD))
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(false)
    if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files)
  }

  const handleDragEnter = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(true)
  }

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault()
    if (e.currentTarget === e.target) setIsDragOver(false)
  }

  // Auto-resize textarea
  const handleTextChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setText(e.target.value)
    const el = e.target
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`
  }

  return (
    <div
      className={cn(
        'relative border-t border-[var(--border)] bg-[var(--surface-elevated)] px-4 py-3 transition-colors',
        isDragOver &&
          'bg-[var(--skill-brand-600)]/5 ring-[var(--skill-brand-600)]/30 ring-2 ring-inset',
      )}
      onDrop={handleDrop}
      onDragOver={(e) => e.preventDefault()}
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
    >
      {isDragOver && (
        <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center">
          <div className="flex items-center gap-2 rounded-lg bg-[var(--skill-brand-600)] px-4 py-2 text-sm text-white shadow-lg">
            <Upload className="h-4 w-4" />
            Drop files here
          </div>
        </div>
      )}
      {files.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-1.5">
          {files.map((f, i) => (
            <AttachmentChip
              key={`${f.name}-${i}`}
              filename={f.name}
              mimeType={f.type}
              sizeBytes={f.size}
              onRemove={() => setFiles((prev) => prev.filter((_, j) => j !== i))}
            />
          ))}
          {files.length >= UPLOAD_LIMITS.MAX_FILES_PER_UPLOAD && (
            <span className="self-center text-[10px] text-[var(--text-muted)]">
              Max {UPLOAD_LIMITS.MAX_FILES_PER_UPLOAD} files
            </span>
          )}
        </div>
      )}
      <div className="flex gap-2">
        <textarea
          ref={textareaRef}
          value={text}
          onChange={handleTextChange}
          onKeyDown={handleKeyDown}
          placeholder={t('chat.describeHelpNeeded')}
          disabled={disabled}
          rows={1}
          className="flex-1 resize-none rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-1 focus:ring-[var(--skill-brand-600)]"
        />
        <input
          ref={fileInputRef}
          type="file"
          multiple
          className="hidden"
          onChange={(e) => {
            if (e.target.files) addFiles(e.target.files)
            e.target.value = ''
          }}
        />
        <Button
          variant="ghost"
          size="sm"
          onClick={() => fileInputRef.current?.click()}
          disabled={disabled}
          className="h-9 w-9 p-0"
          title="Attach files"
        >
          <Paperclip className="h-4 w-4" />
        </Button>
        <Button
          onClick={handleSend}
          disabled={disabled || (!text.trim() && files.length === 0)}
          className="h-9 gap-1.5"
        >
          {disabled ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
        </Button>
      </div>
    </div>
  )
}
