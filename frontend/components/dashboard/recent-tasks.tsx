'use client'

import { ChevronRight, Clock } from 'lucide-react'
import { useRouter } from 'next/navigation'

import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { useAgentNameMap } from '@/hooks/queries/agents'
import { useTasks } from '@/hooks/queries/tasks'
import { useTranslation } from '@/lib/i18n'
import type { Task } from '@/types/tasks'
import { TASK_STATUS_LABELS, TASK_STATUS_STYLES } from '@/types/tasks'

interface RecentTasksProps {
  workspaceId: string
}

function formatRelativeTime(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime()
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

export function RecentTasks({ workspaceId }: RecentTasksProps) {
  const { t } = useTranslation()
  const router = useRouter()

  const { data: tasks = [] } = useTasks(workspaceId, { limit: 10 })
  const agentsMap = useAgentNameMap(workspaceId)

  const recentTasks = [...tasks]
    .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
    .slice(0, 10)

  return (
    <Card className="border-[var(--border)] bg-[var(--surface-elevated)] p-5">
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Clock className="h-4 w-4 text-[var(--text-muted)]" />
          <h2 className="text-sm font-semibold text-[var(--text-primary)]">
            {t('dashboard.recentTasks')}
          </h2>
        </div>
        <button
          type="button"
          className="flex items-center gap-1 text-xs text-[var(--brand-500)] hover:underline"
          onClick={() => router.push('/tasks')}
        >
          {t('dashboard.viewAll')}
          <ChevronRight className="h-3 w-3" />
        </button>
      </div>

      {recentTasks.length === 0 ? (
        <p className="text-sm text-[var(--text-muted)]">{t('tasks.noTasks')}</p>
      ) : (
        <div className="space-y-1">
          {recentTasks.map((task: Task) => {
            const agentId = task.agent_id ?? task.assignee_id
            const agentName = agentId ? agentsMap[agentId] : undefined

            return (
              <button
                key={task.id}
                type="button"
                className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left transition-colors hover:bg-[var(--surface-3)]"
                onClick={() => router.push(`/tasks?task=${task.id}`)}
              >
                <span className="min-w-0 flex-1 truncate text-sm text-[var(--text-primary)]">
                  {task.title}
                </span>
                {agentName && (
                  <span className="shrink-0 text-xs text-[var(--text-muted)]">
                    {agentName}
                  </span>
                )}
                <Badge
                  variant="outline"
                  className={`shrink-0 text-[10px] ${TASK_STATUS_STYLES[task.status] || ''}`}
                >
                  {TASK_STATUS_LABELS[task.status] || task.status}
                </Badge>
                <span className="shrink-0 text-xs text-[var(--text-tertiary)]">
                  {formatRelativeTime(task.updated_at)}
                </span>
              </button>
            )
          })}
        </div>
      )}
    </Card>
  )
}
