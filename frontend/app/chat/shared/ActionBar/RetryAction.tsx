'use client'

import { RotateCcw } from 'lucide-react'

interface RetryActionProps {
  onRetry: () => void
}

export function RetryAction({ onRetry }: RetryActionProps) {
  return (
    <button
      onClick={onRetry}
      className="rounded-md p-1 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600"
      aria-label="Retry message"
    >
      <RotateCcw size={14} />
    </button>
  )
}
