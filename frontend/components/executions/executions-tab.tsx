'use client'

import { Activity, Loader2, X } from 'lucide-react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useMemo, useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { useAgentRuns, useCancelAgentRun } from '@/hooks/queries/agentRuns'
import { useTasks } from '@/hooks/queries/tasks'
import { useReleaseAgentNameMap } from '@/hooks/queries/agents'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import { useProjectContext } from '@/hooks/managed/use-project-context'
import type { AgentRunStatus } from '@/types/agent-run'
import { RUN_STATUS_I18N } from '@/types/agent-run'

import { ExecutionRow } from './execution-row'
import { ExecutionTimeline } from './execution-timeline'

const STATUS_OPTIONS: Array<AgentRunStatus | 'all'> = [
  'all',
  'pending',
  'running',
  'succeeded',
  'failed',
  'cancelled',
]

export function ExecutionsTab() {
  const { t } = useTranslation()
  const router = useRouter()
  const searchParams = useSearchParams()
  const taskFilter = searchParams.get('task') || undefined

  const { projectId } = useProjectContext()

  const [statusFilter, setStatusFilter] = useState<AgentRunStatus | 'all'>('all')
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)

  const { data: runs = [], isLoading } = useAgentRuns(
    {
      task_id: taskFilter,
    },
    { enabled: Boolean(projectId) },
  )

  const { data: tasks = [] } = useTasks(projectId, undefined, {
    enabled: Boolean(projectId),
  })
  const agentNameMap = useReleaseAgentNameMap(projectId)

  const taskTitleMap = useMemo(() => Object.fromEntries(tasks.map((m) => [m.id, m.title])), [tasks])

  const cancelMutation = useCancelAgentRun()

  const filteredRuns = useMemo(
    () => (statusFilter === 'all' ? runs : runs.filter((r) => r.status === statusFilter)),
    [runs, statusFilter],
  )

  function clearTaskFilter() {
    const next = new URLSearchParams(searchParams.toString())
    next.delete('task')
    const qs = next.toString()
    router.replace(qs ? `/tasks?${qs}` : '/tasks')
  }

  const selectedRun = useMemo(() => runs.find((r) => r.id === selectedRunId), [runs, selectedRunId])

  return (
    <div className="flex h-full">
      <div
        className={cn(
          'flex flex-1 flex-col overflow-hidden',
          selectedRunId && 'border-r border-[var(--border)]',
        )}
      >
        <div className="flex flex-wrap items-center gap-2 border-b border-[var(--border)] px-6 py-3">
          {STATUS_OPTIONS.map((status) => (
            <Button
              key={status}
              variant={statusFilter === status ? 'default' : 'outline'}
              size="sm"
              onClick={() => setStatusFilter(status)}
            >
              {t(status === 'all' ? 'execution.filterAll' : RUN_STATUS_I18N[status])}
            </Button>
          ))}
        </div>

        {taskFilter && (
          <div className="flex items-center gap-2 border-b border-[var(--border)] px-6 py-2">
            <span className="text-xs text-[var(--text-muted)]">
              {t('execution.filteredByTask')}:
            </span>
            <Badge variant="secondary" className="gap-1 pr-1">
              {taskTitleMap[taskFilter] || taskFilter.slice(0, 8)}
              <button
                type="button"
                onClick={clearTaskFilter}
                className="ml-0.5 rounded-full p-0.5 hover:bg-[var(--surface-5)]"
              >
                <X className="h-2.5 w-2.5" />
              </button>
            </Badge>
          </div>
        )}

        <div className="flex-1 overflow-y-auto px-6 py-4">
          {isLoading ? (
            <div className="flex items-center gap-2 text-sm text-[var(--text-muted)]">
              <Loader2 className="h-4 w-4 animate-spin" />
              {t('execution.loading')}
            </div>
          ) : filteredRuns.length === 0 ? (
            <Card className="border-dashed border-[var(--border)] bg-[var(--surface-1)] p-8 text-center">
              <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-[var(--surface-3)] text-[var(--text-muted)]">
                <Activity className="h-5 w-5" />
              </div>
              <h2 className="mt-4 text-sm font-semibold text-[var(--text-primary)]">
                {t('execution.executionEmpty')}
              </h2>
              <p className="mt-1 text-sm text-[var(--text-muted)]">
                {t('execution.executionEmptyDesc')}
              </p>
            </Card>
          ) : (
            <div className="space-y-3">
              {filteredRuns.map((run) => (
                <ExecutionRow
                  key={run.id}
                  run={run}
                  taskTitle={run.task_id ? taskTitleMap[run.task_id] : undefined}
                  agentName={run.release_id ? agentNameMap[run.release_id] : undefined}
                  onSelect={setSelectedRunId}
                  onCancel={(id) => cancelMutation.mutate(id)}
                  isCancelling={cancelMutation.isPending && cancelMutation.variables === run.id}
                  isSelected={run.id === selectedRunId}
                />
              ))}
            </div>
          )}
        </div>
      </div>

      {selectedRunId && projectId && selectedRun?.current_execution_id && (
        <div className="w-[480px] flex-shrink-0 overflow-hidden">
          <ExecutionTimeline
            executionId={selectedRun.current_execution_id}
            projectId={projectId}
            taskId={selectedRun.task_id ?? undefined}
          />
        </div>
      )}
    </div>
  )
}
