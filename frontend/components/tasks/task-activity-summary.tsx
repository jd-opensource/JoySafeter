'use client'

import { Bot, CheckCircle2, Play } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { PulsingDot } from '@/components/ui/pulsing-dot'
import { useTranslation } from '@/lib/i18n'
import { formatRelativeTime } from '@/lib/utils/runHelpers'
import type { Task } from '@/types/tasks'

interface TaskActivitySummaryProps {
  inProgressTasks: Task[]
  recentlyDoneTasks: Task[]
  agentsMap: Record<string, string>
  onSelectTask?: (id: string) => void
}

export function TaskActivitySummary({
  inProgressTasks,
  recentlyDoneTasks,
  agentsMap,
  onSelectTask,
}: TaskActivitySummaryProps) {
  const { t } = useTranslation()

  if (inProgressTasks.length === 0 && recentlyDoneTasks.length === 0) return null

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
      {/* In Progress */}
      <Card className="border-[var(--border)] bg-[var(--surface-1)] p-5">
        <div className="mb-3 flex items-center gap-2">
          <Play className="h-3.5 w-3.5 text-[var(--brand-500)]" />
          <h3 className="text-sm font-semibold text-[var(--text-primary)]">{t('tasks.inProgress')}</h3>
          {inProgressTasks.length > 0 && (
            <Badge variant="outline" className="text-xs">{inProgressTasks.length}</Badge>
          )}
        </div>
        {inProgressTasks.length === 0 ? (
          <p className="text-xs text-[var(--text-muted)]">{t('tasks.noInProgress')}</p>
        ) : (
          <div className="space-y-2">
            {inProgressTasks.slice(0, 5).map((task) => {
              const agentId = task.agent_id ?? task.assignee_id
              const agentName = agentId ? agentsMap[agentId] : undefined
              return (
                <button
                  key={task.id}
                  type="button"
                  onClick={() => onSelectTask?.(task.id)}
                  className="flex w-full items-center gap-3 rounded-md p-2 text-left transition-colors hover:bg-[var(--surface-3)]"
                >
                  <PulsingDot />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-[var(--text-primary)]">{task.title}</p>
                    {agentName && (
                      <div className="mt-0.5 flex items-center gap-1 text-xs text-[var(--text-muted)]">
                        <Bot className="h-3 w-3" />
                        <span>{agentName}</span>
                      </div>
                    )}
                  </div>
                  {task.updated_at && (
                    <span className="flex-shrink-0 text-xs text-[var(--text-muted)]">
                      {formatElapsed(task.updated_at)}
                    </span>
                  )}
                </button>
              )
            })}
          </div>
        )}
      </Card>

      {/* Recently Done */}
      <Card className="border-[var(--border)] bg-[var(--surface-1)] p-5">
        <div className="mb-3 flex items-center gap-2">
          <CheckCircle2 className="h-3.5 w-3.5 text-[var(--status-success)]" />
          <h3 className="text-sm font-semibold text-[var(--text-primary)]">{t('tasks.recentlyDone')}</h3>
        </div>
        {recentlyDoneTasks.length === 0 ? (
          <p className="text-xs text-[var(--text-muted)]">{t('tasks.noRecentlyDone')}</p>
        ) : (
          <div className="space-y-2">
            {recentlyDoneTasks.slice(0, 5).map((task) => {
              const agentId = task.agent_id ?? task.assignee_id
              const agentName = agentId ? agentsMap[agentId] : undefined
              return (
                <button
                  key={task.id}
                  type="button"
                  onClick={() => onSelectTask?.(task.id)}
                  className="flex w-full items-center gap-3 rounded-md p-2 text-left transition-colors hover:bg-[var(--surface-3)]"
                >
                  <CheckCircle2 className="h-3.5 w-3.5 flex-shrink-0 text-[var(--status-success)]" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm text-[var(--text-secondary)]">{task.title}</p>
                    {agentName && (
                      <div className="mt-0.5 flex items-center gap-1 text-xs text-[var(--text-muted)]">
                        <Bot className="h-3 w-3" />
                        <span>{agentName}</span>
                      </div>
                    )}
                  </div>
                  {task.updated_at && (
                    <span className="flex-shrink-0 text-xs text-[var(--text-muted)]">
                      {formatRelativeTime(task.updated_at, t)}
                    </span>
                  )}
                </button>
              )
            })}
          </div>
        )}
      </Card>
    </div>
  )
}

function formatElapsed(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime()
  const seconds = Math.floor(diff / 1000)
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m${String(seconds % 60).padStart(2, '0')}s`
  const hours = Math.floor(minutes / 60)
  return `${hours}h${String(minutes % 60).padStart(2, '0')}m`
}

