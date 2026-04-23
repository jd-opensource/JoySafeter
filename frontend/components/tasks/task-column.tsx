'use client'

import { useDroppable } from '@dnd-kit/core'
import { SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'

import { cn } from '@/lib/utils'
import { useTranslation } from '@/lib/i18n'
import type { Task, TaskStatus } from '@/types/tasks'
import { TASK_STATUS_LABELS } from '@/types/tasks'

import { TaskCard } from './task-card'

const STATUS_COLUMN_STYLES: Record<TaskStatus, { bg: string; indicator: string }> = {
  backlog: { bg: 'bg-[var(--surface-1)]', indicator: 'bg-[var(--text-muted)]' },
  todo: { bg: 'bg-[var(--surface-1)]', indicator: 'bg-[var(--brand-400)]' },
  in_progress: { bg: 'bg-[var(--surface-1)]', indicator: 'bg-[var(--status-warning)]' },
  in_review: { bg: 'bg-[var(--surface-1)]', indicator: 'bg-[var(--brand-400)]' },
  done: { bg: 'bg-[var(--surface-1)]', indicator: 'bg-[var(--status-success)]' },
  cancelled: { bg: 'bg-[var(--surface-1)]', indicator: 'bg-[var(--text-muted)]' },
}

interface SortableTaskCardProps {
  task: Task
  agentName?: string
  onSelectTask?: (id: string) => void
}

function SortableTaskCard({ task, agentName, onSelectTask }: SortableTaskCardProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: task.id,
    data: { type: 'task', task },
  })

  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.4 : undefined,
  }

  return (
    <TaskCard
      ref={setNodeRef}
      task={task}
      agentName={agentName}
      onSelectTask={onSelectTask}
      style={style}
      {...attributes}
      {...listeners}
    />
  )
}

interface TaskColumnProps {
  status: TaskStatus
  tasks: Task[]
  agentsMap?: Record<string, string>
  onSelectTask?: (id: string) => void
}

export function TaskColumn({
  status,
  tasks,
  agentsMap,
  onSelectTask,
}: TaskColumnProps) {
  const { t } = useTranslation()
  const { setNodeRef, isOver } = useDroppable({
    id: `column-${status}`,
    data: { type: 'column', status },
  })

  const taskIds = tasks.map((m) => m.id)
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
          {TASK_STATUS_LABELS[status]}
        </span>
        <span className="inline-flex h-5 min-w-[20px] items-center justify-center rounded-full bg-[var(--surface-5)] px-1.5 text-xs font-medium text-[var(--text-secondary)]">
          {tasks.length}
        </span>
      </div>

      <div ref={setNodeRef} className="flex-1 space-y-2 overflow-y-auto p-2">
        <SortableContext items={taskIds} strategy={verticalListSortingStrategy}>
          {tasks.map((task) => (
            <SortableTaskCard
              key={task.id}
              task={task}
              agentName={agentsMap?.[task.agent_id ?? task.assignee_id ?? '']}
              onSelectTask={onSelectTask}
            />
          ))}
        </SortableContext>
        {tasks.length === 0 && (
          <div className="flex flex-col items-center justify-center py-8 text-[var(--text-muted)]">
            <div className="mb-1.5 h-8 w-8 rounded-full border-2 border-dashed border-[var(--border)]" />
            <p className="text-xs">{t('tasks.noTasks')}</p>
          </div>
        )}
      </div>
    </div>
  )
}
