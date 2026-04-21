'use client'

import { cn } from '@/lib/utils'

type AgentStatus = 'draft' | 'active' | 'archived'

const statusConfig: Record<AgentStatus, { color: string; label: string }> = {
  draft: { color: 'bg-[var(--status-warning)]', label: 'Draft' },
  active: { color: 'bg-[var(--status-success)]', label: 'Active' },
  archived: { color: 'bg-[var(--surface-muted)]', label: 'Archived' },
}

interface AgentStatusIndicatorProps {
  status: AgentStatus
  className?: string
}

export function AgentStatusIndicator({ status, className }: AgentStatusIndicatorProps) {
  const config = statusConfig[status]

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 text-xs text-[var(--text-secondary)]',
        className,
      )}
    >
      <span className={cn('inline-flex h-2 w-2 rounded-full', config.color)} />
      {config.label}
    </span>
  )
}
