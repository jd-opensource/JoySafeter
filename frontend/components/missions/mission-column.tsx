'use client'

import { useDroppable } from '@dnd-kit/core'
import { SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'

import { cn } from '@/lib/utils'
import { useTranslation } from '@/lib/i18n'
import type { Mission, MissionStatus } from '@/types/missions'
import { MISSION_STATUS_LABELS } from '@/types/missions'

import { MissionCard } from './mission-card'

const STATUS_COLUMN_STYLES: Record<MissionStatus, { bg: string; indicator: string }> = {
  backlog: { bg: 'bg-[var(--surface-1)]', indicator: 'bg-[var(--text-muted)]' },
  todo: { bg: 'bg-[var(--surface-1)]', indicator: 'bg-[var(--brand-400)]' },
  in_progress: { bg: 'bg-[var(--surface-1)]', indicator: 'bg-[var(--status-warning)]' },
  in_review: { bg: 'bg-[var(--surface-1)]', indicator: 'bg-[var(--brand-400)]' },
  done: { bg: 'bg-[var(--surface-1)]', indicator: 'bg-[var(--status-success)]' },
  cancelled: { bg: 'bg-[var(--surface-1)]', indicator: 'bg-[var(--text-muted)]' },
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

export function MissionColumn({
  status,
  missions,
  agentsMap,
  onSelectMission,
}: MissionColumnProps) {
  const { t } = useTranslation()
  const { setNodeRef, isOver } = useDroppable({
    id: `column-${status}`,
    data: { type: 'column', status },
  })

  const missionIds = missions.map((m) => m.id)
  const colStyle = STATUS_COLUMN_STYLES[status]

  return (
    <div
      className={cn(
        'flex min-w-[200px] flex-1 flex-col rounded-lg border border-[var(--border)] transition-all',
        colStyle.bg,
        isOver && 'ring-[var(--brand-400)]/30 ring-2',
      )}
    >
      <div className="flex items-center gap-2 px-3 py-2.5">
        <span className={cn('h-2.5 w-2.5 rounded-full', colStyle.indicator)} />
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
          <div className="flex flex-col items-center justify-center py-8 text-[var(--text-muted)]">
            <div className="mb-1.5 h-8 w-8 rounded-full border-2 border-dashed border-[var(--border)]" />
            <p className="text-xs">{t('missions.noMissions')}</p>
          </div>
        )}
      </div>
    </div>
  )
}
