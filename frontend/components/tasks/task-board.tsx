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

import { useUpdateTask, useTaskTransitions } from '@/hooks/queries/tasks'
import { useTranslation } from '@/lib/i18n'
import { toastError } from '@/lib/utils/toast'
import type { Task, TaskStatus } from '@/types/tasks'
import {
  DEFAULT_MANUAL_TRANSITIONS,
  TASK_STATUS_ORDER,
  INACTIVE_TASK_STATUSES,
} from '@/types/tasks'

import { TaskCard } from './task-card'
import { TaskColumn } from './task-column'

interface TaskBoardProps {
  tasks: Task[]
  projectId: string
  agentsMap: Record<string, string>
  onSelectTask?: (id: string) => void
}

export function TaskBoard({ tasks, projectId, agentsMap, onSelectTask }: TaskBoardProps) {
  const { t } = useTranslation()
  const [activeId, setActiveId] = useState<string | null>(null)
  const updateTask = useUpdateTask()
  const { data: transitions } = useTaskTransitions(projectId)
  const effectiveTransitions = transitions ?? DEFAULT_MANUAL_TRANSITIONS

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }))

  const grouped = useMemo(() => {
    const map: Record<TaskStatus, Task[]> = {
      backlog: [],
      todo: [],
      in_progress: [],
      in_review: [],
      done: [],
      cancelled: [],
    }
    for (const m of tasks) {
      if (map[m.status]) {
        map[m.status].push(m)
      }
    }
    for (const key of Object.keys(map) as TaskStatus[]) {
      map[key].sort((a, b) => a.position - b.position)
    }
    return map
  }, [tasks])

  const activeTask = useMemo(
    () => (activeId ? tasks.find((m) => m.id === activeId) : undefined),
    [activeId, tasks],
  )

  const handleDragStart = useCallback((event: DragStartEvent) => {
    setActiveId(event.active.id as string)
  }, [])

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      setActiveId(null)
      const { active, over } = event
      if (!over) return

      const draggedTask = tasks.find((m) => m.id === active.id)
      if (!draggedTask) return

      // Determine target column
      const overData = over.data.current
      let targetStatus: TaskStatus
      if (overData?.type === 'column') {
        targetStatus = overData.status as TaskStatus
      } else if (overData?.type === 'task') {
        targetStatus = (overData.task as Task).status
      } else {
        // over.id is `column-<status>` format
        const colPrefix = 'column-'
        const overId = over.id as string
        if (overId.startsWith(colPrefix)) {
          targetStatus = overId.slice(colPrefix.length) as TaskStatus
        } else {
          // Dropped on a card — find its status
          const targetTask = tasks.find((m) => m.id === over.id)
          if (!targetTask) return
          targetStatus = targetTask.status
        }
      }

      // Calculate new position
      const targetColumn = grouped[targetStatus] || []
      let newPosition: number

      if (overData?.type === 'task' && over.id !== active.id) {
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

      const statusChanged = draggedTask.status !== targetStatus
      const positionChanged = draggedTask.position !== newPosition

      if (!statusChanged && !positionChanged) return

      if (statusChanged) {
        const from = draggedTask.status
        const allowed = effectiveTransitions[from] ?? []
        if (!allowed.includes(targetStatus)) {
          toastError(t('tasks.invalidTransition', { from, to: targetStatus }))
          return
        }
        const toTerminal = (INACTIVE_TASK_STATUSES as readonly string[]).includes(targetStatus)
        if (draggedTask.current_execution_id && toTerminal) {
          toastError(t('tasks.cancelRunningBeforeMove'))
          return
        }
      }

      const updates: Record<string, unknown> = {}
      if (statusChanged) updates.status = targetStatus
      if (positionChanged) updates.position = newPosition

      updateTask.mutate({
        taskId: draggedTask.id,
        projectId,
        ...updates,
      })
    },
    [tasks, grouped, projectId, updateTask, effectiveTransitions, t],
  )

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCorners}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
    >
      <div className="flex h-full gap-3 p-4">
        {TASK_STATUS_ORDER.map((status) => (
          <TaskColumn
            key={status}
            status={status}
            tasks={grouped[status]}
            agentsMap={agentsMap}
            onSelectTask={onSelectTask}
          />
        ))}
      </div>

      <DragOverlay>
        {activeTask ? (
          <TaskCard
            task={activeTask}
            agentName={agentsMap[activeTask.agent_id ?? '']}
            isDragOverlay
          />
        ) : null}
      </DragOverlay>
    </DndContext>
  )
}
