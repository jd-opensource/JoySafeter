'use client'

import { Paperclip, Send, Loader2 } from 'lucide-react'
import { useCallback, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { AttachmentChip } from './AttachmentChip'
import { useTranslation } from '@/lib/i18n'
import { UPLOAD_LIMITS, ALLOWED_MIME_TYPES } from '@/lib/core/constants/upload-limits'

interface ChatInputProps {
  onSend: (message: string, files: File[]) => void
  disabled?: boolean
}

export function ChatInput({ onSend, disabled }: ChatInputProps) {
  const { t } = useTranslation()
  const [text, setText] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const fileInputRef = useRef<HTMLInputElement>(null)

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
    const valid = Array.from(newFiles).filter(
      (f) =>
        f.size <= UPLOAD_LIMITS.MAX_FILE_SIZE_BYTES &&
        ALLOWED_MIME_TYPES.includes(f.type),
    )
    setFiles((prev) => [...prev, ...valid].slice(0, 10))
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files)
  }

  return (
    <div
      className="border-t border-[var(--border)] bg-[var(--surface-elevated)] px-4 py-3"
      onDrop={handleDrop}
      onDragOver={(e) => e.preventDefault()}
    >
      {files.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-1.5">
          {files.map((f, i) => (
            <AttachmentChip
              key={`${f.name}-${i}`}
              filename={f.name}
              mimeType={f.type}
              sizeBytes={f.size}
              onRemove={() =>
                setFiles((prev) => prev.filter((_, j) => j !== i))
              }
            />
          ))}
        </div>
      )}
      <div className="flex gap-2">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
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
        >
          <Paperclip className="h-4 w-4" />
        </Button>
        <Button
          onClick={handleSend}
          disabled={disabled || (!text.trim() && files.length === 0)}
          className="h-9 gap-1.5"
        >
          {disabled ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Send className="h-4 w-4" />
          )}
        </Button>
      </div>
    </div>
  )
}
