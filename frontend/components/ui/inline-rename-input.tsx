'use client'

import { Check, X } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { cn } from '@/lib/utils'

interface InlineRenameInputProps {
  value: string
  onChange: (value: string) => void
  onSave: () => void
  onCancel: () => void
  size?: 'sm' | 'default'
  placeholder?: string
  className?: string
  autoFocus?: boolean
}

export function InlineRenameInput({
  value,
  onChange,
  onSave,
  onCancel,
  size = 'default',
  placeholder = '',
  className,
  autoFocus = true,
}: InlineRenameInputProps) {
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (autoFocus) {
      // Small delay to ensure DOM is ready
      const timer = setTimeout(() => {
        inputRef.current?.focus()
        inputRef.current?.select()
      }, 50)
      return () => clearTimeout(timer)
    }
  }, [autoFocus])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      onSave()
    } else if (e.key === 'Escape') {
      e.preventDefault()
      onCancel()
    }
  }

  const isSmall = size === 'sm'

  return (
    <div
      className={cn(
        'flex flex-1 items-center duration-150 animate-in fade-in',
        isSmall ? 'gap-1' : 'gap-1.5',
        className,
      )}
      onClick={(e) => e.stopPropagation()}
    >
      <input
        ref={inputRef}
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onBlur={onSave}
        onKeyDown={handleKeyDown}
        onClick={(e) => e.stopPropagation()}
        placeholder={placeholder}
        className={cn(
          'flex-1 border border-[var(--brand-500)] bg-[var(--surface-1)] font-medium text-[var(--text-primary)] shadow-sm outline-none ring-2 ring-[var(--brand-500)] transition-all placeholder:text-[var(--text-subtle)] focus:border-[var(--brand-500)] focus:ring-[var(--brand-500)]',
          isSmall
            ? 'rounded-sm px-1.5 py-[2px] text-xs-plus'
            : 'rounded-md px-2 py-1 text-xs-plus',
        )}
      />
      <div className={cn('flex items-center', isSmall ? 'gap-0.5' : 'gap-[2px]')}>
        <button
          type="button"
          className={cn(
            'flex items-center justify-center bg-[var(--brand-500)] text-white shadow-sm transition-all hover:bg-[var(--brand-500)] active:scale-95',
            isSmall ? 'h-5 w-5 rounded-sm' : 'h-6 w-6 rounded-md',
          )}
          onClick={(e) => {
            e.stopPropagation()
            onSave()
          }}
        >
          <Check className={isSmall ? 'h-2.5 w-2.5' : 'h-3 w-3'} strokeWidth={2.5} />
        </button>
        <button
          type="button"
          className={cn(
            'flex items-center justify-center bg-[var(--surface-5)] text-[var(--text-tertiary)] transition-all hover:bg-[var(--surface-9)] active:scale-95',
            isSmall ? 'h-5 w-5 rounded-sm' : 'h-6 w-6 rounded-md',
            !isSmall && 'hover:text-[var(--text-secondary)]',
          )}
          onClick={(e) => {
            e.stopPropagation()
            onCancel()
          }}
        >
          <X className={isSmall ? 'h-2.5 w-2.5' : 'h-3 w-3'} strokeWidth={2.5} />
        </button>
      </div>
    </div>
  )
}
