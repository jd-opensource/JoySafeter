'use client'

import { Bot, Calendar, User } from 'lucide-react'
import { forwardRef } from 'react'

import { cn } from '@/lib/utils'
import type { Mission } from '@/types/missions'

import { PriorityBadge } from './priority-badge'

interface MissionCardProps {
  mission: Mission
  agentName?: string
  onSelectMission?: (id: string) => void
  isDragOverlay?: boolean
  style?: React.CSSProperties
}

export const MissionCard = forwardRef<HTMLButtonElement, MissionCardProps & React.HTMLAttributes<HTMLButtonElement>>(
  function MissionCard({ mission, agentName, onSelectMission, isDragOverlay, style, className, ...props }, ref) {
    const hasActiveExecution = Boolean(mission.current_execution_id)
    const isAssignedToAgent = mission.assignee_type === 'agent'

    const isOverdue = mission.due_date ? new Date(mission.due_date) < new Date() : false

    return (
      <button
        ref={ref}
        type="button"
        onClick={() => onSelectMission?.(mission.id)}
        style={style}
        className={cn(
          'w-full rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)] p-3 text-left',
          'transition-shadow hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand-400)]',
          isDragOverlay && 'shadow-lg ring-2 ring-[var(--brand-400)]/40',
          className,
        )}
        {...props}
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
                <span className="max-w-[80px] truncate">{agentName || (mission.assignee_id ? 'Agent' : 'Unassigned')}</span>
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
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[var(--status-success)] opacity-75" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-[var(--status-success)]" />
              </span>
              Running
            </span>
          )}
        </div>

        {/* Tags + Due Date row */}
        {(mission.tags?.length || mission.due_date) && (
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            {mission.tags?.slice(0, 2).map((tag) => (
              <span
                key={tag}
                className="inline-block max-w-[80px] truncate rounded bg-[var(--surface-3)] px-1.5 py-0.5 text-[10px] text-[var(--text-secondary)]"
              >
                {tag}
              </span>
            ))}
            {(mission.tags?.length ?? 0) > 2 && (
              <span className="text-[10px] text-[var(--text-muted)]">
                +{(mission.tags?.length ?? 0) - 2}
              </span>
            )}
            {mission.due_date && (
              <span
                className={cn(
                  'inline-flex items-center gap-0.5 text-[10px]',
                  isOverdue ? 'text-[var(--status-error)]' : 'text-[var(--text-muted)]',
                )}
              >
                <Calendar className="h-2.5 w-2.5" />
                {new Date(mission.due_date).toLocaleDateString()}
              </span>
            )}
          </div>
        )}
      </button>
    )
  },
)
