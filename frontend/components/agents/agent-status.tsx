'use client'

import { cn } from '@/lib/utils'
import type { AgentStatus } from '@/types/agents'
import { AGENT_STATUS_LABELS } from '@/types/agents'

const statusConfig: Record<AgentStatus, { color: string; pulse?: boolean }> = {
  idle: { color: 'bg-[var(--status-success)]' },
  working: { color: 'bg-[var(--brand-400)]', pulse: true },
  blocked: { color: 'bg-[var(--status-warning)]' },
  error: { color: 'bg-[var(--status-error)]' },
  offline: { color: 'bg-[var(--surface-muted)]' },
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
      <span className="relative flex h-2 w-2">
        {config.pulse && (
          <span
            className={cn(
              'absolute inline-flex h-full w-full animate-ping rounded-full opacity-75',
              config.color,
            )}
          />
        )}
        <span className={cn('relative inline-flex h-2 w-2 rounded-full', config.color)} />
      </span>
      {AGENT_STATUS_LABELS[status]}
    </span>
  )
}
