'use client'

import {
  DndContext,
  DragOverlay,
  PointerSensor,
  useSensor,
  useSensors,
  closestCorners,
  type DragEndEvent,
  type DragStartEvent,
} from '@dnd-kit/core'
import { useCallback, useMemo, useState } from 'react'

import { useUpdateMission, useMissionTransitions } from '@/hooks/queries/missions'
import { toastError } from '@/lib/utils/toast'
import type { Mission, MissionStatus } from '@/types/missions'
import { DEFAULT_MANUAL_TRANSITIONS, MISSION_STATUS_ORDER, TERMINAL_MISSION_STATUSES } from '@/types/missions'

import { MissionCard } from './mission-card'
import { MissionColumn } from './mission-column'

interface MissionBoardProps {
  missions: Mission[]
  workspaceId: string
  agentsMap: Record<string, string>
  onSelectMission?: (id: string) => void
}

export function MissionBoard({ missions, workspaceId, agentsMap, onSelectMission }: MissionBoardProps) {
  const [activeId, setActiveId] = useState<string | null>(null)
  const updateMission = useUpdateMission()
  const { data: transitions } = useMissionTransitions(workspaceId)
  const effectiveTransitions = transitions ?? DEFAULT_MANUAL_TRANSITIONS

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
  )

  const grouped = useMemo(() => {
    const map: Record<MissionStatus, Mission[]> = {
      backlog: [],
      todo: [],
      in_progress: [],
      in_review: [],
      done: [],
      cancelled: [],
    }
    for (const m of missions) {
      if (map[m.status]) {
        map[m.status].push(m)
      }
    }
    for (const key of Object.keys(map) as MissionStatus[]) {
      map[key].sort((a, b) => a.position - b.position)
    }
    return map
  }, [missions])

  const activeMission = useMemo(
    () => (activeId ? missions.find((m) => m.id === activeId) : undefined),
    [activeId, missions],
  )

  const handleDragStart = useCallback((event: DragStartEvent) => {
    setActiveId(event.active.id as string)
  }, [])

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      setActiveId(null)
      const { active, over } = event
      if (!over) return

      const draggedMission = missions.find((m) => m.id === active.id)
      if (!draggedMission) return

      // Determine target column
      const overData = over.data.current
      let targetStatus: MissionStatus
      if (overData?.type === 'column') {
        targetStatus = overData.status as MissionStatus
      } else if (overData?.type === 'mission') {
        targetStatus = (overData.mission as Mission).status
      } else {
        // over.id is `column-<status>` format
        const colPrefix = 'column-'
        const overId = over.id as string
        if (overId.startsWith(colPrefix)) {
          targetStatus = overId.slice(colPrefix.length) as MissionStatus
        } else {
          // Dropped on a card — find its status
          const targetMission = missions.find((m) => m.id === over.id)
          if (!targetMission) return
          targetStatus = targetMission.status
        }
      }

      // Calculate new position
      const targetColumn = grouped[targetStatus] || []
      let newPosition: number

      if (overData?.type === 'mission' && over.id !== active.id) {
        // Dropped on a specific card
        const overIndex = targetColumn.findIndex((m) => m.id === over.id)
        if (overIndex <= 0) {
          newPosition = (targetColumn[0]?.position ?? 0) - 1
        } else {
          const prev = targetColumn[overIndex - 1]
          const curr = targetColumn[overIndex]
          newPosition = (prev.position + curr.position) / 2
        }
      } else {
        // Dropped on column — place at end
        const last = targetColumn[targetColumn.length - 1]
        newPosition = last ? last.position + 1 : 0
      }

      const statusChanged = draggedMission.status !== targetStatus
      const positionChanged = draggedMission.position !== newPosition

      if (!statusChanged && !positionChanged) return

      if (statusChanged) {
        const from = draggedMission.status
        const allowed = effectiveTransitions[from] ?? []
        if (!allowed.includes(targetStatus)) {
          toastError(`Cannot move from ${from} to ${targetStatus}`)
          return
        }
        const toTerminal = (TERMINAL_MISSION_STATUSES as readonly string[]).includes(targetStatus)
        if (draggedMission.current_execution_id && toTerminal) {
          toastError('Cancel the running execution before moving to this status')
          return
        }
      }

      const updates: Record<string, unknown> = {}
      if (statusChanged) updates.status = targetStatus
      if (positionChanged) updates.position = newPosition

      updateMission.mutate({
        missionId: draggedMission.id,
        workspaceId,
        ...updates,
      })
    },
    [missions, grouped, workspaceId, updateMission],
  )

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCorners}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
    >
      <div className="flex h-full gap-3 p-4">
        {MISSION_STATUS_ORDER.map((status) => (
          <MissionColumn
            key={status}
            status={status}
            missions={grouped[status]}
            agentsMap={agentsMap}
            onSelectMission={onSelectMission}
          />
        ))}
      </div>

      <DragOverlay>
        {activeMission ? (
          <MissionCard
            mission={activeMission}
            agentName={agentsMap[activeMission.assignee_id ?? '']}
            isDragOverlay
          />
        ) : null}
      </DragOverlay>
    </DndContext>
  )
}
