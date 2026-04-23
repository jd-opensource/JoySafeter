'use client'

import { AlertTriangle, ExternalLink, RefreshCw } from 'lucide-react'
import Link from 'next/link'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { useTranslation } from '@/lib/i18n'
import type { Task } from '@/types/tasks'

interface TaskAttentionPanelProps {
  tasks: Task[]
  agentsMap: Record<string, string>
  onSelectTask?: (id: string) => void
  onRetry?: (taskId: string) => void
}

export function TaskAttentionPanel({ tasks, agentsMap, onSelectTask, onRetry }: TaskAttentionPanelProps) {
  const { t } = useTranslation()

  if (tasks.length === 0) return null

  return (
    <Card className="border-[var(--status-warning-border)] bg-[var(--status-warning-bg)]/30 p-5">
      <div className="mb-3 flex items-center gap-2">
        <AlertTriangle className="h-4 w-4 text-[var(--status-warning)]" />
        <h2 className="text-sm font-semibold text-[var(--text-primary)]">
          {t('tasks.needsAttention')}
        </h2>
        <Badge variant="outline" className="text-xs">{tasks.length}</Badge>
      </div>

      <div className="space-y-2">
        {tasks.slice(0, 5).map((task) => {
          const agentId = task.agent_id ?? task.assignee_id
          const agentName = agentId ? agentsMap[agentId] : undefined
          const isFailed = task.status === 'in_review'

          return (
            <div
              key={task.id}
              className="flex items-center justify-between rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)] p-3"
            >
              <div className="flex items-center gap-3 min-w-0">
                <div
                  className={`h-2 w-2 flex-shrink-0 rounded-full ${
                    isFailed ? 'bg-[var(--status-error)]' : 'bg-[var(--status-warning)]'
                  }`}
                />
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    {agentName && (
                      <Link
                        href={`/agents/${agentId}`}
                        onClick={(e) => e.stopPropagation()}
                        className="text-xs font-medium text-[var(--brand-500)] hover:underline"
                      >
                        {agentName}
                      </Link>
                    )}
                    <span className="text-xs text-[var(--text-muted)]">›</span>
                    <span className="truncate text-sm font-medium text-[var(--text-primary)]">
                      {task.title}
                    </span>
                  </div>
                  <p className="mt-0.5 text-xs text-[var(--text-muted)]">
                    {isFailed ? t('tasks.executionFailed') : t('tasks.awaitingReview')}
                    {task.updated_at && ` · ${formatRelativeTime(task.updated_at, t)}`}
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-2 flex-shrink-0">
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 text-xs"
                  onClick={() => onSelectTask?.(task.id)}
                >
                  <ExternalLink className="mr-1 h-3 w-3" />
                  {t('tasks.details')}
                </Button>
                {isFailed && onRetry && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-7 text-xs"
                    onClick={() => onRetry(task.id)}
                  >
                    <RefreshCw className="mr-1 h-3 w-3" />
                    {t('tasks.retry')}
                  </Button>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </Card>
  )
}

function formatRelativeTime(dateStr: string, t: (key: string) => string): string {
  const diff = Date.now() - new Date(dateStr).getTime()
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return t('execution.justNow')
  if (minutes < 60) return `${minutes}${t('execution.minutesSuffix')}`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}${t('execution.hoursSuffix')}`
  const days = Math.floor(hours / 24)
  return `${days}${t('execution.daysSuffix')}`
}
