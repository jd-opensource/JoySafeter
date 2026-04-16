'use client'

import { Bot, User } from 'lucide-react'

import { cn } from '@/lib/utils'
import type { Mission } from '@/types/missions'

import { PriorityBadge } from './priority-badge'

interface MissionCardProps {
  mission: Mission
  onSelect?: (id: string) => void
}

export function MissionCard({ mission, onSelect }: MissionCardProps) {
  const hasActiveExecution = Boolean(mission.current_execution_id)
  const isAssignedToAgent = mission.assignee_type === 'agent'

  return (
    <button
      type="button"
      onClick={() => onSelect?.(mission.id)}
      className={cn(
        'w-full rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)] p-3 text-left',
        'transition-shadow hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand-400)]',
      )}
    >
      <p className="line-clamp-2 text-sm font-medium text-[var(--text-primary)]">
        {mission.title}
      </p>

      <div className="mt-2 flex flex-wrap items-center gap-2">
        <PriorityBadge priority={mission.priority} />

        <span className="inline-flex items-center gap-1 text-xs text-[var(--text-muted)]">
          {isAssignedToAgent ? (
            <>
              <Bot className="h-3 w-3" />
              <span>{mission.assignee_id ? 'Agent' : 'Unassigned'}</span>
            </>
          ) : (
            <>
              <User className="h-3 w-3" />
              <span>{mission.assignee_id ? 'Assigned' : 'Unassigned'}</span>
            </>
          )}
        </span>

        {hasActiveExecution && (
          <span className="inline-flex items-center gap-1 text-xs text-[var(--text-muted)]">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-green-400 opacity-75" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-green-500" />
            </span>
            Running
          </span>
        )}
      </div>
    </button>
  )
}
