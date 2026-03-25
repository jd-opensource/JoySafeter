'use client'

import { Activity, Bot, Clock3, Loader2, Sparkles, Square } from 'lucide-react'
import Link from 'next/link'
import { useEffect, useMemo, useRef, useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { useCancelRun, useRuns } from '@/hooks/queries/runs'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import {
  ACTIVE_RUN_STATUSES,
  applyRunEvent,
  applyRunSnapshot,
  applyRunStatus,
  buildRunHref,
  formatRelativeTime,
  formatRunStatus,
} from '@/lib/utils/runHelpers'
import { getRunWsClient } from '@/lib/ws/runs/runWsClient'
import type { RunEventFrame, RunSnapshotFrame, RunStatusFrame } from '@/lib/ws/runs/types'
import type { RunSummary } from '@/services/runService'

function RunRow({
  run,
  onCancel,
  isCancelling,
}: {
  run: RunSummary
  onCancel: (runId: string) => void
  isCancelling: boolean
}) {
  const { t } = useTranslation()
  const resumable = run.run_type === 'skill_creator'
  const href = buildRunHref(run)
  const isActive = ACTIVE_RUN_STATUSES.has(run.status)

  return (
    <Card className="border-[var(--border)] bg-[var(--surface-1)] p-4">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0 flex-1">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--skill-brand-50)] text-[var(--skill-brand-600)]">
              <Bot className="h-4 w-4" />
            </div>
            <span className="truncate text-sm font-semibold text-[var(--text-primary)]">
              {run.title || t('runs.untitled', 'Untitled Run')}
            </span>
            <Badge
              variant="outline"
              className={cn(
                'text-[10px]',
                isActive
                  ? 'border-[var(--skill-brand-200)] bg-[var(--skill-brand-50)] text-[var(--skill-brand-700)]'
                  : 'border-[var(--border)] bg-[var(--surface-2)] text-[var(--text-secondary)]',
              )}
            >
              {formatRunStatus(run.status, t)}
            </Badge>
            <Badge variant="outline" className="border-[var(--border)] bg-[var(--surface-2)] text-[10px] text-[var(--text-secondary)]">
              {run.run_type}
            </Badge>
          </div>

          <div className="flex flex-wrap items-center gap-4 text-xs text-[var(--text-muted)]">
            <span className="flex items-center gap-1">
              <Clock3 className="h-3.5 w-3.5" />
              {t('runs.startedAt', 'Started')} {formatRelativeTime(run.started_at, t)}
            </span>
            <span className="flex items-center gap-1">
              <Sparkles className="h-3.5 w-3.5" />
              seq {run.last_seq}
            </span>
            {run.last_heartbeat_at && (
              <span className="flex items-center gap-1">
                <Activity className="h-3.5 w-3.5" />
                {t('runs.lastHeartbeat', 'Heartbeat')} {formatRelativeTime(run.last_heartbeat_at, t)}
              </span>
            )}
            {run.error_message && (
              <span className="truncate text-red-500">{run.error_message}</span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button asChild variant="outline" size="sm">
            <Link href={`/runs/${encodeURIComponent(run.run_id)}`}>{t('runs.details', 'Details')}</Link>
          </Button>
          {resumable && (
            <Button asChild variant="outline" size="sm">
              <Link href={href}>{t('runs.open', 'Open')}</Link>
            </Button>
          )}
          {isActive && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => onCancel(run.run_id)}
              disabled={isCancelling}
              className="gap-1.5"
            >
              {isCancelling ? <Loader2 className="h-4 w-4 animate-spin" /> : <Square className="h-3.5 w-3.5" />}
              {t('runs.cancel', 'Cancel')}
            </Button>
          )}
        </div>
      </div>
    </Card>
  )
}

export default function RunsPage() {
  const { t } = useTranslation()
  const [statusFilter, setStatusFilter] = useState<'all' | 'active' | 'finished'>('all')
  const { data, isLoading } = useRuns({ limit: 100 })
  const cancelRunMutation = useCancelRun()
  const runWsClientRef = useRef(getRunWsClient())
  const [liveRuns, setLiveRuns] = useState<RunSummary[]>([])

  const runIds = useMemo(() => (data?.items || []).map((r) => r.run_id).join(','), [data?.items])
  useEffect(() => {
    const incoming = data?.items || []
    setLiveRuns((current) => {
      const currentMap = new Map(current.map((run) => [run.run_id, run]))
      return incoming.map((run) => {
        const existing = currentMap.get(run.run_id)
        if (!existing) {
          return run
        }
        return {
          ...run,
          status: existing.status || run.status,
          last_seq: Math.max(existing.last_seq, run.last_seq),
          error_code: existing.error_code ?? run.error_code,
          error_message: existing.error_message ?? run.error_message,
          updated_at:
            new Date(existing.updated_at).getTime() > new Date(run.updated_at).getTime()
              ? existing.updated_at
              : run.updated_at,
        }
      })
    })
  }, [data?.items])

  useEffect(() => {
    const targets = data?.items || []
    if (!targets.length) {
      return
    }

    targets.forEach((run) => {
      void runWsClientRef.current.subscribe(run.run_id, run.last_seq, {
        onSnapshot: (frame) => {
          setLiveRuns((current) =>
            current.map((item) => (item.run_id === frame.run_id ? applyRunSnapshot(item, frame) : item)),
          )
        },
        onEvent: (frame) => {
          setLiveRuns((current) =>
            current.map((item) => (item.run_id === frame.run_id ? applyRunEvent(item, frame) : item)),
          )
        },
        onStatus: (frame) => {
          setLiveRuns((current) =>
            current.map((item) => (item.run_id === frame.run_id ? applyRunStatus(item, frame) : item)),
          )
        },
      })
    })

    return () => {
      targets.forEach((run) => {
        runWsClientRef.current.unsubscribe(run.run_id)
      })
    }
  }, [runIds])

  const runs = useMemo(() => {
    const items = liveRuns
    if (statusFilter === 'active') {
      return items.filter((run) => ACTIVE_RUN_STATUSES.has(run.status))
    }
    if (statusFilter === 'finished') {
      return items.filter((run) => !ACTIVE_RUN_STATUSES.has(run.status))
    }
    return items
  }, [liveRuns, statusFilter])

  return (
    <div className="flex h-full flex-col bg-[var(--bg)]">
      <div className="border-b border-[var(--border)] bg-[var(--surface-elevated)] px-6 py-4">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <Activity className="h-5 w-5 text-[var(--skill-brand-600)]" />
              <h1 className="text-lg font-semibold text-[var(--text-primary)]">
                {t('runs.title', 'Run Center')}
              </h1>
            </div>
            <p className="mt-1 text-sm text-[var(--text-muted)]">
              {t('runs.description', 'Track active and recent long-running agent tasks in one place.')}
            </p>
          </div>

          <div className="flex items-center gap-2">
            <Button
              variant={statusFilter === 'all' ? 'default' : 'outline'}
              size="sm"
              onClick={() => setStatusFilter('all')}
            >
              {t('runs.filterAll', 'All')}
            </Button>
            <Button
              variant={statusFilter === 'active' ? 'default' : 'outline'}
              size="sm"
              onClick={() => setStatusFilter('active')}
            >
              {t('runs.filterActive', 'Active')}
            </Button>
            <Button
              variant={statusFilter === 'finished' ? 'default' : 'outline'}
              size="sm"
              onClick={() => setStatusFilter('finished')}
            >
              {t('runs.filterFinished', 'Finished')}
            </Button>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-6">
        {isLoading ? (
          <div className="flex items-center gap-2 text-sm text-[var(--text-muted)]">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t('runs.loading', 'Loading runs...')}
          </div>
        ) : runs.length === 0 ? (
          <Card className="border-dashed border-[var(--border)] bg-[var(--surface-1)] p-8 text-center">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-[var(--surface-3)] text-[var(--text-muted)]">
              <Activity className="h-5 w-5" />
            </div>
            <h2 className="mt-4 text-sm font-semibold text-[var(--text-primary)]">
              {t('runs.emptyTitle', 'No runs yet')}
            </h2>
            <p className="mt-1 text-sm text-[var(--text-muted)]">
              {t('runs.emptyDescription', 'Long-running agent tasks will appear here once they start.')}
            </p>
          </Card>
        ) : (
          <div className="space-y-3">
            {runs.map((run) => (
              <RunRow
                key={run.run_id}
                run={run}
                onCancel={(runId) => cancelRunMutation.mutate(runId)}
                isCancelling={cancelRunMutation.isPending && cancelRunMutation.variables === run.run_id}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
