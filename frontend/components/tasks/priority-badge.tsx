'use client'

import { cn } from '@/lib/utils'
import type { TaskPriority } from '@/types/missions'
import { TASK_PRIORITY_LABELS } from '@/types/missions'

const PRIORITY_STYLES: Record<TaskPriority, string> = {
  urgent:
    'bg-[var(--status-error-bg)] text-[var(--status-error)] border-[var(--status-error-border)]',
  high: 'bg-[var(--status-warning-bg)] text-[var(--status-warning)] border-[var(--status-warning-border)]',
  medium:
    'bg-[var(--status-warning-bg)] text-[var(--status-warning)] border-[var(--status-warning-border)]',
  low: 'bg-[var(--surface-3)] text-[var(--brand-400)] border-[var(--border)]',
  none: 'bg-[var(--surface-3)] text-[var(--text-muted)] border-[var(--border)]',
}

interface PriorityBadgeProps {
  priority: TaskPriority
  className?: string
}

export function PriorityBadge({ priority, className }: PriorityBadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium',
        PRIORITY_STYLES[priority],
        className,
      )}
    >
      {TASK_PRIORITY_LABELS[priority]}
    </span>
  )
}
