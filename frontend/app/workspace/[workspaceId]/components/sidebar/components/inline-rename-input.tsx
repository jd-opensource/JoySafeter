'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { Check, X } from 'lucide-react'

interface InlineRenameInputProps {
  initialName: string
  onSave: (newName: string) => void
  onCancel: () => void
  className?: string
  inputClassName?: string
}

export function useInlineRename(initialName: string, onRename?: (newName: string) => void) {
  const [isEditing, setIsEditing] = useState(false)
  const [editName, setEditName] = useState(initialName)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (isEditing && inputRef.current) {
      inputRef.current.focus()
      inputRef.current.select()
    }
  }, [isEditing])

  // Sync editName when initialName changes while not editing
  useEffect(() => {
    if (!isEditing) setEditName(initialName)
  }, [initialName, isEditing])

  const startEditing = useCallback(() => {
    setEditName(initialName)
    setIsEditing(true)
  }, [initialName])

  const handleSave = useCallback(() => {
    const trimmed = editName.trim()
    if (trimmed && trimmed !== initialName && onRename) {
      onRename(trimmed)
    }
    setIsEditing(false)
  }, [editName, initialName, onRename])

  const handleCancel = useCallback(() => {
    setEditName(initialName)
    setIsEditing(false)
  }, [initialName])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter') { e.preventDefault(); handleSave() }
    if (e.key === 'Escape') { e.preventDefault(); handleCancel() }
  }, [handleSave, handleCancel])

  return { isEditing, editName, setEditName, inputRef, startEditing, handleSave, handleCancel, handleKeyDown }
}

export function InlineRenameInput({ initialName, onSave, onCancel, className, inputClassName }: InlineRenameInputProps) {
  const { editName, setEditName, inputRef, handleSave, handleCancel, handleKeyDown } = useInlineRename(
    initialName,
    onSave,
  )

  // Override cancel to also call parent onCancel
  const cancel = useCallback(() => {
    handleCancel()
    onCancel()
  }, [handleCancel, onCancel])

  return (
    <div className={className || 'flex items-center gap-0.5'}>
      <input
        ref={inputRef}
        value={editName}
        onChange={(e) => setEditName(e.target.value)}
        onBlur={handleSave}
        onKeyDown={handleKeyDown}
        className={inputClassName || 'h-6 flex-1 rounded-sm border border-[var(--border)] bg-[var(--surface-elevated)] px-1.5 text-app-xs outline-none focus:border-primary'}
        autoFocus
      />
      <button type="button" onMouseDown={(e) => { e.preventDefault(); handleSave() }} className="rounded-xs p-0.5 text-[var(--status-success)] hover:bg-[var(--surface-3)]">
        <Check className="h-3 w-3" />
      </button>
      <button type="button" onMouseDown={(e) => { e.preventDefault(); cancel() }} className="rounded-xs p-0.5 text-[var(--text-muted)] hover:bg-[var(--surface-3)]">
        <X className="h-3 w-3" />
      </button>
    </div>
  )
}
