'use client'

import { Bot, Clock3, Loader2, Square, Zap } from 'lucide-react'
import Link from 'next/link'
import { useMemo } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import { formatRelativeTime } from '@/lib/utils/runHelpers'
import type { Execution } from '@/types/executions'
import {
  ACTIVE_EXECUTION_STATUSES,
  EXECUTION_STATUS_STYLES,
  EXECUTION_STATUS_I18N,
} from '@/types/executions'

interface ExecutionRowProps {
  execution: Execution
  missionTitle?: string
  agentName?: string
  onSelect: (executionId: string) => void
  onCancel: (executionId: string) => void
  isCancelling: boolean
  isSelected: boolean
}

export function ExecutionRow({
  execution,
  missionTitle,
  agentName,
  onSelect,
  onCancel,
  isCancelling,
  isSelected,
}: ExecutionRowProps) {
  const { t } = useTranslation()
  const isActive = ACTIVE_EXECUTION_STATUSES.includes(execution.status)

  const duration = useMemo(() => {
    if (!execution.started_at) return null
    const start = new Date(execution.started_at).getTime()
    const end = execution.finished_at ? new Date(execution.finished_at).getTime() : Date.now()
    const secs = Math.floor((end - start) / 1000)
    const m = Math.floor(secs / 60)
    const s = secs % 60
    return `${m}m ${s.toString().padStart(2, '0')}s`
  }, [execution.started_at, execution.finished_at])

  const tokenDisplay = useMemo(() => {
    const summary = execution.result_summary as Record<string, number> | undefined
    if (!summary) return null
    const input = summary.input_tokens ?? 0
    const output = summary.output_tokens ?? 0
    if (!input && !output) return null
    const fmt = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n))
    return `${fmt(input)} in / ${fmt(output)} out`
  }, [execution.result_summary])

  return (
    <Card
      className={cn(
        'cursor-pointer border-[var(--border)] bg-[var(--surface-1)] p-4 transition-colors hover:bg-[var(--surface-2)]',
        isSelected && 'ring-2 ring-[var(--brand-400)]',
      )}
      onClick={() => onSelect(execution.id)}
    >
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0 flex-1">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <Badge
              variant="outline"
              className={cn('text-xs', EXECUTION_STATUS_STYLES[execution.status])}
            >
              {t(EXECUTION_STATUS_I18N[execution.status])}
            </Badge>
            {missionTitle && execution.mission_id && (
              <Link
                href={`/missions?mission=${execution.mission_id}`}
                onClick={(e) => e.stopPropagation()}
                className="truncate text-sm font-medium text-[var(--text-primary)] hover:underline"
              >
                {missionTitle}
              </Link>
            )}
            {!missionTitle && (
              <span className="truncate text-sm font-medium text-[var(--text-primary)]">
                {execution.title || `Execution ${execution.id.slice(0, 8)}`}
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
            {execution.started_at && (
              <span className="flex items-center gap-1">
                <Clock3 className="h-3.5 w-3.5" />
                {t('runs.startedAt')} {formatRelativeTime(execution.started_at, t)}
              </span>
            )}
            {duration && (
              <span className="flex items-center gap-1">
                <Clock3 className="h-3.5 w-3.5" />
                {duration}
              </span>
            )}
            {tokenDisplay && (
              <span className="flex items-center gap-1">
                <Zap className="h-3.5 w-3.5" />
                {tokenDisplay}
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
                onCancel(execution.id)
              }}
              disabled={isCancelling}
              className="gap-1.5"
            >
              {isCancelling ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Square className="h-3.5 w-3.5" />
              )}
              {t('runs.cancel')}
            </Button>
          )}
        </div>
      </div>
    </Card>
  )
}
