'use client'

import { AlertTriangle, CheckCircle2, ChevronRight } from 'lucide-react'
import { useRouter } from 'next/navigation'

import { Card } from '@/components/ui/card'
import { useAgentRuns } from '@/hooks/queries/agentRuns'
import { useTasks } from '@/hooks/queries/tasks'
import { useTranslation } from '@/lib/i18n'
import type { Task } from '@/types/tasks'
import type { AgentRun } from '@/types/agent-run'

interface NeedsAttentionProps {
  workspaceId: string
}

export function NeedsAttention({ workspaceId }: NeedsAttentionProps) {
  const { t } = useTranslation()
  const router = useRouter()

  const { data: tasks = [] } = useTasks(workspaceId)
  const { data: runs = [] } = useAgentRuns(
    { workspace_id: workspaceId },
    { enabled: Boolean(workspaceId) },
  )

  const reviewTasks = tasks.filter((task: Task) => task.status === 'in_review')
  const failedRuns = runs.filter((run: AgentRun) => run.status === 'failed')

  const hasItems = reviewTasks.length > 0 || failedRuns.length > 0

  return (
    <Card className="border-[var(--border)] bg-[var(--surface-elevated)] p-5">
      <div className="mb-4 flex items-center gap-2">
        <AlertTriangle className="h-4 w-4 text-[var(--status-warning)]" />
        <h2 className="text-sm font-semibold text-[var(--text-primary)]">
          {t('dashboard.needsAttention')}
        </h2>
      </div>

      {hasItems ? (
        <div className="space-y-2">
          {reviewTasks.length > 0 && (
            <button
              type="button"
              className="flex w-full items-center justify-between rounded-lg border border-[var(--border)] bg-[var(--surface-1)] p-3 text-left transition-colors hover:bg-[var(--surface-3)]"
              onClick={() => router.push('/tasks')}
            >
              <div className="flex items-center gap-2">
                <div className="h-2 w-2 rounded-full bg-[var(--status-warning)]" />
                <span className="text-sm text-[var(--text-primary)]">
                  {t('dashboard.awaitingApproval')}
                </span>
                <span className="text-xs font-medium text-[var(--text-secondary)]">
                  x{reviewTasks.length}
                </span>
              </div>
              <ChevronRight className="h-4 w-4 text-[var(--text-muted)]" />
            </button>
          )}

          {failedRuns.length > 0 && (
            <button
              type="button"
              className="flex w-full items-center justify-between rounded-lg border border-[var(--border)] bg-[var(--surface-1)] p-3 text-left transition-colors hover:bg-[var(--surface-3)]"
              onClick={() => router.push('/tasks')}
            >
              <div className="flex items-center gap-2">
                <div className="h-2 w-2 rounded-full bg-[var(--status-error)]" />
                <span className="text-sm text-[var(--text-primary)]">
                  {t('dashboard.failedCount')}
                </span>
                <span className="text-xs font-medium text-[var(--text-secondary)]">
                  x{failedRuns.length}
                </span>
              </div>
              <ChevronRight className="h-4 w-4 text-[var(--text-muted)]" />
            </button>
          )}
        </div>
      ) : (
        <div className="flex items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--surface-1)] p-4">
          <CheckCircle2 className="h-4 w-4 text-[var(--status-success)]" />
          <span className="text-sm text-[var(--text-secondary)]">
            {t('dashboard.allClear')}
          </span>
        </div>
      )}
    </Card>
  )
}
