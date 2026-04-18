'use client'

import { useDroppable } from '@dnd-kit/core'
import { SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'

import { cn } from '@/lib/utils'
import type { Mission, MissionStatus } from '@/types/missions'
import { MISSION_STATUS_LABELS } from '@/types/missions'

import { MissionCard } from './mission-card'

const STATUS_COLUMN_STYLES: Record<string, string> = {
  backlog: 'bg-[var(--surface-1)]',
  todo: 'bg-[var(--surface-2)]',
  in_progress: 'bg-[var(--surface-2)]',
  in_review: 'bg-[var(--surface-2)]',
  done: 'bg-[var(--surface-2)]',
}

interface SortableMissionCardProps {
  mission: Mission
  agentName?: string
  onSelectMission?: (id: string) => void
}

function SortableMissionCard({ mission, agentName, onSelectMission }: SortableMissionCardProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: mission.id,
    data: { type: 'mission', mission },
  })

  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.4 : undefined,
  }

  return (
    <MissionCard
      ref={setNodeRef}
      mission={mission}
      agentName={agentName}
      onSelectMission={onSelectMission}
      style={style}
      {...attributes}
      {...listeners}
    />
  )
}

interface MissionColumnProps {
  status: MissionStatus
  missions: Mission[]
  agentsMap?: Record<string, string>
  onSelectMission?: (id: string) => void
}

export function MissionColumn({ status, missions, agentsMap, onSelectMission }: MissionColumnProps) {
  const { setNodeRef, isOver } = useDroppable({
    id: `column-${status}`,
    data: { type: 'column', status },
  })

  const missionIds = missions.map((m) => m.id)

  return (
    <div
      className={cn(
        'flex h-full w-[230px] flex-shrink-0 flex-col rounded-lg border border-[var(--border)] transition-all',
        STATUS_COLUMN_STYLES[status] ?? 'bg-[var(--surface-1)]',
        isOver && 'ring-2 ring-[var(--brand-400)]/30',
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

      <div ref={setNodeRef} className="flex-1 space-y-2 overflow-y-auto p-2">
        <SortableContext items={missionIds} strategy={verticalListSortingStrategy}>
          {missions.map((mission) => (
            <SortableMissionCard
              key={mission.id}
              mission={mission}
              agentName={agentsMap?.[mission.assignee_id ?? '']}
              onSelectMission={onSelectMission}
            />
          ))}
        </SortableContext>
        {missions.length === 0 && (
          <p className="py-8 text-center text-xs text-[var(--text-muted)]">No missions</p>
        )}
      </div>
    </div>
  )
}
