'use client'

import { Bot, Clock3, Loader2, Square } from 'lucide-react'
import Link from 'next/link'
import { useMemo } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import { formatDuration, formatRelativeTime } from '@/lib/utils/dateHelpers'
import type { AgentRun } from '@/types/agent-run'
import { ACTIVE_RUN_STATUSES, RUN_STATUS_STYLES, RUN_STATUS_I18N } from '@/types/agent-run'

interface RunRowProps {
  run: AgentRun
  taskTitle?: string
  agentName?: string
  onSelect: (runId: string) => void
  onCancel: (runId: string) => void
  isCancelling: boolean
  isSelected: boolean
}

export function ExecutionRow({
  run,
  taskTitle,
  agentName,
  onSelect,
  onCancel,
  isCancelling,
  isSelected,
}: RunRowProps) {
  const { t } = useTranslation()
  const isActive = ACTIVE_RUN_STATUSES.includes(run.status)

  const duration = useMemo(
    () => formatDuration(run.started_at, run.ended_at),
    [run.started_at, run.ended_at],
  )

  return (
    <Card
      className={cn(
        'cursor-pointer border-[var(--border)] bg-[var(--surface-1)] p-4 transition-colors hover:bg-[var(--surface-2)]',
        isSelected && 'ring-2 ring-[var(--brand-400)]',
      )}
      onClick={() => onSelect(run.id)}
    >
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0 flex-1">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <Badge
              variant="outline"
              className={cn('text-xs', RUN_STATUS_STYLES[run.status])}
            >
              {t(RUN_STATUS_I18N[run.status])}
            </Badge>
            {taskTitle && run.task_id && (
              <Link
                href={`/tasks?task=${run.task_id}`}
                onClick={(e) => e.stopPropagation()}
                className="truncate text-sm font-medium text-[var(--text-primary)] hover:underline"
              >
                {taskTitle}
              </Link>
            )}
            {!taskTitle && (
              <span className="truncate text-sm font-medium text-[var(--text-primary)]">
                {run.goal || `Run ${run.id.slice(0, 8)}`}
              </span>
            )}
            {agentName && (
              <Badge
                variant="outline"
                className="border-[var(--border)] bg-[var(--surface-2)] text-xs text-[var(--text-secondary)]"
              >
                <Bot className="mr-1 h-3 w-3" />
                {agentName}
              </Badge>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-4 text-xs text-[var(--text-muted)]">
            {run.started_at && (
              <span className="flex items-center gap-1">
                <Clock3 className="h-3.5 w-3.5" />
                {t('execution.startedAt')} {formatRelativeTime(run.started_at, t)}
              </span>
            )}
            {duration && (
              <span className="flex items-center gap-1">
                <Clock3 className="h-3.5 w-3.5" />
                {duration}
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          {isActive && (
            <Button
              variant="outline"
              size="sm"
              onClick={(e) => {
                e.stopPropagation()
                onCancel(run.id)
              }}
              disabled={isCancelling}
              className="gap-1.5"
            >
              {isCancelling ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Square className="h-3.5 w-3.5" />
              )}
              {t('execution.cancel')}
            </Button>
          )}
        </div>
      </div>
    </Card>
  )
}
