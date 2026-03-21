'use client'

import { CopyAction } from './CopyAction'
import { RetryAction } from './RetryAction'

interface ActionBarProps {
  content: string
  onRetry?: () => void
}

export function ActionBar({ content, onRetry }: ActionBarProps) {
  if (!content) return null

  return (
    <div className="mt-1 flex items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
      <CopyAction text={content} />
      {onRetry && <RetryAction onRetry={onRetry} />}
    </div>
  )
}
