'use client'

import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'

type AgentStatus = 'draft' | 'active' | 'archived'

const statusColors: Record<AgentStatus, string> = {
  draft: 'bg-[var(--status-warning)]',
  active: 'bg-[var(--status-success)]',
  archived: 'bg-[var(--surface-muted)]',
}

const statusI18nKeys: Record<AgentStatus, string> = {
  draft: 'agents.status.draft',
  active: 'agents.status.active',
  archived: 'agents.status.archived',
}

interface AgentStatusIndicatorProps {
  status: AgentStatus
  className?: string
}

export function AgentStatusIndicator({ status, className }: AgentStatusIndicatorProps) {
  const { t } = useTranslation()

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 text-xs text-[var(--text-secondary)]',
        className,
      )}
    >
      <span className={cn('inline-flex h-2 w-2 rounded-full', statusColors[status])} />
      {t(statusI18nKeys[status])}
    </span>
  )
}
