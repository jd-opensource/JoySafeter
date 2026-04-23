'use client'

import { Activity, Loader2, X } from 'lucide-react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useMemo, useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { useExecutions, useCancelExecution } from '@/hooks/queries/executions'
import { useTasks } from '@/hooks/queries/tasks'
import { useAgentNameMap } from '@/hooks/queries/agents'
import { useWorkspaces } from '@/hooks/queries/workspaces'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import type { ExecutionStatus } from '@/types/executions'
import { EXECUTION_STATUS_I18N } from '@/types/executions'

import { ExecutionRow } from './execution-row'
import { ExecutionTimeline } from './execution-timeline'

const STATUS_OPTIONS: Array<ExecutionStatus | 'all'> = [
  'all',
  'pending',
  'dispatched',
  'running',
  'approval_wait',
  'succeeded',
  'failed',
  'cancelled',
]

export function ExecutionsTab() {
  const { t } = useTranslation()
  const router = useRouter()
  const searchParams = useSearchParams()
  const taskFilter = searchParams.get('task') || undefined

  const { data: workspaces = [] } = useWorkspaces()
  const workspaceId = workspaces[0]?.id ?? ''

  const [statusFilter, setStatusFilter] = useState<ExecutionStatus | 'all'>('all')
  const [selectedExecutionId, setSelectedExecutionId] = useState<string | null>(null)

  const { data: executions = [], isLoading } = useExecutions(
    workspaceId,
    {
      task_id: taskFilter,
      status: statusFilter !== 'all' ? statusFilter : undefined,
      limit: 100,
    },
    { enabled: Boolean(workspaceId) },
  )

  const { data: tasks = [] } = useTasks(workspaceId, undefined, {
    enabled: Boolean(workspaceId),
  })
  const agentNameMap = useAgentNameMap(workspaceId)

  const taskTitleMap = useMemo(
    () => Object.fromEntries(tasks.map((m) => [m.id, m.title])),
    [tasks],
  )

  const cancelMutation = useCancelExecution()

  function clearTaskFilter() {
    const next = new URLSearchParams(searchParams.toString())
    next.delete('task')
    const qs = next.toString()
    router.replace(qs ? `/runs?${qs}` : '/runs')
  }

  const selectedExecution = useMemo(
    () => executions.find((e) => e.id === selectedExecutionId),
    [executions, selectedExecutionId],
  )

  return (
    <div className="flex h-full">
      <div
        className={cn(
          'flex flex-1 flex-col overflow-hidden',
          selectedExecutionId && 'border-r border-[var(--border)]',
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
              {t(status === 'all' ? 'execution.filterAll' : EXECUTION_STATUS_I18N[status])}
            </Button>
          ))}
        </div>

        {taskFilter && (
          <div className="flex items-center gap-2 border-b border-[var(--border)] px-6 py-2">
            <span className="text-xs text-[var(--text-muted)]">{t('execution.filteredByTask')}:</span>
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
          ) : executions.length === 0 ? (
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
              {executions.map((exec) => (
                <ExecutionRow
                  key={exec.id}
                  execution={exec}
                  taskTitle={exec.task_id ? taskTitleMap[exec.task_id] : undefined}
                  agentName={
                    exec.agent_profile_id ? agentNameMap[exec.agent_profile_id] : undefined
                  }
                  onSelect={setSelectedExecutionId}
                  onCancel={(id) => cancelMutation.mutate({ executionId: id, workspaceId })}
                  isCancelling={
                    cancelMutation.isPending && cancelMutation.variables?.executionId === exec.id
                  }
                  isSelected={exec.id === selectedExecutionId}
                />
              ))}
            </div>
          )}
        </div>
      </div>

      {selectedExecutionId && workspaceId && (
        <div className="w-[480px] flex-shrink-0 overflow-hidden">
          <ExecutionTimeline
            executionId={selectedExecutionId}
            workspaceId={workspaceId}
            taskId={selectedExecution?.task_id ?? undefined}
          />
        </div>
      )}
    </div>
  )
}
