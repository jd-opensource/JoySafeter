'use client'

import { RotateCcw } from 'lucide-react'

interface RetryActionProps {
  onRetry: () => void
}

export function RetryAction({ onRetry }: RetryActionProps) {
  return (
    <button
      onClick={onRetry}
      className="rounded-md p-1 text-[var(--text-muted)] transition-colors hover:bg-[var(--surface-3)] hover:text-[var(--text-secondary)]"
      aria-label="Retry message"
    >
      <RotateCcw size={14} />
    </button>
  )
}
