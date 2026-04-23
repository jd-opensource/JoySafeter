'use client'

import { Bot, Calendar, ExternalLink, User } from 'lucide-react'
import Link from 'next/link'
import { forwardRef } from 'react'

import { cn } from '@/lib/utils'
import { useTranslation } from '@/lib/i18n'
import { PulsingDot } from '@/components/ui/pulsing-dot'
import type { Task, TaskPriority } from '@/types/tasks'
import { TASK_STATUS_STYLES } from '@/types/tasks'

import { PriorityBadge } from './priority-badge'

const PRIORITY_LEFT_BORDER: Record<TaskPriority, string> = {
  urgent: 'border-l-[var(--status-error)]',
  high: 'border-l-[var(--status-warning)]',
  medium: 'border-l-[var(--brand-400)]',
  low: 'border-l-[var(--text-muted)]',
  none: 'border-l-transparent',
}

interface TaskCardProps {
  task: Task
  agentName?: string
  onSelectTask?: (id: string) => void
  isDragOverlay?: boolean
  style?: React.CSSProperties
}

export const TaskCard = forwardRef<
  HTMLButtonElement,
  TaskCardProps & React.HTMLAttributes<HTMLButtonElement>
>(function TaskCard(
  { task, agentName, onSelectTask, isDragOverlay, style, className, ...props },
  ref,
) {
  const { t } = useTranslation()
  // Support both new agent_id (backend) and legacy assignee_id fields
  const effectiveAgentId = task.agent_id ?? task.assignee_id
  const hasActiveExecution = Boolean(task.current_execution_id)
  const isAssignedToAgent = task.assignee_type === 'agent' || Boolean(task.agent_id)
  // Show run status badge when there's a linked run but no active execution
  const hasLinkedRun = Boolean(task.latest_run_id) && !hasActiveExecution

  const isOverdue = task.due_date ? Date.parse(task.due_date) < Date.now() : false

  return (
    <button
      ref={ref}
      type="button"
      onClick={() => onSelectTask?.(task.id)}
      style={style}
      className={cn(
        'w-full rounded-lg border border-l-[3px] border-[var(--border)] bg-[var(--surface-elevated)] p-3 text-left',
        PRIORITY_LEFT_BORDER[task.priority],
        'transition-shadow hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand-400)]',
        isDragOverlay && 'ring-[var(--brand-400)]/40 shadow-lg ring-2',
        className,
      )}
      {...props}
    >
      <p className="line-clamp-2 text-sm font-medium text-[var(--text-primary)]">{task.title}</p>

      <div className="mt-2 flex flex-wrap items-center gap-2">
        <PriorityBadge priority={task.priority} />

        <span className="inline-flex items-center gap-1 text-xs text-[var(--text-muted)]">
          {isAssignedToAgent ? (
            <>
              <Bot className="h-3 w-3" />
              {effectiveAgentId ? (
                <Link
                  href={`/agents/${effectiveAgentId}`}
                  onClick={(e) => e.stopPropagation()}
                  className="max-w-[80px] truncate text-[var(--brand-500)] hover:underline"
                >
                  {agentName || 'Agent'}
                </Link>
              ) : (
                <span>未分配</span>
              )}
            </>
          ) : (
            <>
              <User className="h-3 w-3" />
              <span>{effectiveAgentId ? 'Assigned' : '未分配'}</span>
            </>
          )}
        </span>

        {/* Latest run status badge — shown when a prior run exists but is no longer active */}
        {hasLinkedRun && (
          <Link
            href={`/runs?task=${task.id}`}
            onClick={(e) => e.stopPropagation()}
            className={cn(
              'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium',
              TASK_STATUS_STYLES[task.status] ??
                'border-[var(--border)] bg-[var(--surface-3)] text-[var(--text-muted)]',
            )}
          >
            <ExternalLink className="h-2.5 w-2.5" />
            {t('tasks.lastRun')}
          </Link>
        )}
      </div>

      {(task.tags?.length || task.due_date) && (
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
          {task.tags?.slice(0, 2).map((tag) => (
            <span
              key={tag}
              className="inline-block max-w-[80px] truncate rounded bg-[var(--surface-3)] px-1.5 py-0.5 text-[10px] text-[var(--text-secondary)]"
            >
              {tag}
            </span>
          ))}
          {(task.tags?.length ?? 0) > 2 && (
            <span className="text-[10px] text-[var(--text-muted)]">
              +{(task.tags?.length ?? 0) - 2}
            </span>
          )}
          {task.due_date && (
            <span
              className={cn(
                'inline-flex items-center gap-0.5 text-[10px]',
                isOverdue ? 'text-[var(--status-error)]' : 'text-[var(--text-muted)]',
              )}
            >
              <Calendar className="h-2.5 w-2.5" />
              {new Date(task.due_date).toLocaleDateString()}
            </span>
          )}
        </div>
      )}

      {hasActiveExecution && (
        <Link
          href={`/runs?tab=executions&task=${task.id}`}
          onClick={(e) => e.stopPropagation()}
          className="bg-[var(--surface-3)]/50 -mx-3 -mb-3 mt-2 flex items-center gap-1.5 rounded-b-lg border-t border-[var(--border)] px-3 py-1.5 text-xs text-[var(--status-success)] hover:bg-[var(--surface-3)]"
        >
          <PulsingDot />
          {t('tasks.running')}
          <ExternalLink className="ml-auto h-3 w-3" />
        </Link>
      )}
    </button>
  )
})
