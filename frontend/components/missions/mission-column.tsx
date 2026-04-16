'use client'

import { cn } from '@/lib/utils'
import type { Mission, MissionStatus } from '@/types/missions'
import { MISSION_STATUS_LABELS } from '@/types/missions'

import { MissionCard } from './mission-card'

const STATUS_COLUMN_STYLES: Record<string, string> = {
  backlog: 'bg-gray-50/50',
  todo: 'bg-blue-50/30',
  in_progress: 'bg-amber-50/30',
  in_review: 'bg-purple-50/30',
  done: 'bg-green-50/30',
}

interface MissionColumnProps {
  status: MissionStatus
  missions: Mission[]
}

export function MissionColumn({ status, missions }: MissionColumnProps) {
  return (
    <div
      className={cn(
        'flex h-full w-72 flex-shrink-0 flex-col rounded-lg border border-[var(--border)]',
        STATUS_COLUMN_STYLES[status] ?? 'bg-[var(--surface-1)]',
      )}
    >
      <div className="flex items-center gap-2 border-b border-[var(--border)] px-3 py-2.5">
        <span className="text-sm font-semibold text-[var(--text-primary)]">
          {MISSION_STATUS_LABELS[status]}
        </span>
        <span className="inline-flex h-5 min-w-[20px] items-center justify-center rounded-full bg-[var(--surface-5)] px-1.5 text-xs font-medium text-[var(--text-secondary)]">
          {missions.length}
        </span>
      </div>

      <div className="flex-1 space-y-2 overflow-y-auto p-2">
        {missions.map((mission) => (
          <MissionCard key={mission.id} mission={mission} />
        ))}
        {missions.length === 0 && (
          <p className="py-8 text-center text-xs text-[var(--text-muted)]">No missions</p>
        )}
      </div>
    </div>
  )
}
