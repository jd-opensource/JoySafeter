'use client'

import { Activity, Bot, Clock3, Loader2, Search, Sparkles, Square } from 'lucide-react'
import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import { useEffect, useMemo, useRef, useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { useAgents, useCancelRun, useRuns } from '@/hooks/queries/runs'
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
  const href = buildRunHref(run)
  const resumable = href !== '#'
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
              {run.title || t('runs.untitled')}
            </span>
            <Badge
              variant="outline"
              className={cn(
                'text-2xs',
                isActive
                  ? 'border-[var(--skill-brand-200)] bg-[var(--skill-brand-50)] text-[var(--skill-brand-700)]'
                  : 'border-[var(--border)] bg-[var(--surface-2)] text-[var(--text-secondary)]',
              )}
            >
              {formatRunStatus(run.status, t)}
            </Badge>
            <Badge
              variant="outline"
              className="border-[var(--border)] bg-[var(--surface-2)] text-2xs text-[var(--text-secondary)]"
            >
              {run.agent_display_name || run.agent_name}
            </Badge>
          </div>

          <div className="flex flex-wrap items-center gap-4 text-xs text-[var(--text-muted)]">
            <span className="flex items-center gap-1">
              <Clock3 className="h-3.5 w-3.5" />
              {t('runs.startedAt')} {formatRelativeTime(run.started_at, t)}
            </span>
            <span className="flex items-center gap-1">
              <Sparkles className="h-3.5 w-3.5" />
              seq {run.last_seq}
            </span>
            {run.last_heartbeat_at && (
              <span className="flex items-center gap-1">
                <Activity className="h-3.5 w-3.5" />
                {t('runs.lastHeartbeat')} {formatRelativeTime(run.last_heartbeat_at, t)}
              </span>
            )}
            {run.error_message && (
              <span className="truncate text-red-500">{run.error_message}</span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button asChild variant="outline" size="sm">
            <Link href={`/runs/${encodeURIComponent(run.run_id)}`}>{t('runs.details')}</Link>
          </Button>
          {resumable && (
            <Button asChild variant="outline" size="sm">
              <Link href={href}>{t('runs.open')}</Link>
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
              {t('runs.cancel')}
            </Button>
          )}
        </div>
      </div>
    </Card>
  )
}

export default function RunsPage() {
  const { t } = useTranslation()
  const router = useRouter()
  const searchParams = useSearchParams()
  const selectedAgent = searchParams.get('agent') || 'all'
  const statusFilter = searchParams.get('status') || 'all'
  const querySearch = searchParams.get('q') || ''
  const [searchInput, setSearchInput] = useState(querySearch)
  const { data: agentData } = useAgents()
  const { data, isLoading } = useRuns({
    agentName: selectedAgent !== 'all' ? selectedAgent : undefined,
    status: statusFilter !== 'all' ? statusFilter : undefined,
    search: querySearch || undefined,
    limit: 100,
  })
  const cancelRunMutation = useCancelRun()
  const runWsClientRef = useRef(getRunWsClient())
  const [liveRuns, setLiveRuns] = useState<RunSummary[]>([])
  const statusOptions = ['all', 'queued', 'running', 'interrupt_wait', 'completed', 'failed', 'cancelled']

  useEffect(() => {
    setSearchInput(querySearch)
  }, [querySearch])

  useEffect(() => {
    const handle = window.setTimeout(() => {
      if (searchInput === querySearch) {
        return
      }
      const nextParams = new URLSearchParams(searchParams.toString())
      if (searchInput.trim()) {
        nextParams.set('q', searchInput.trim())
      } else {
        nextParams.delete('q')
      }
      const nextQuery = nextParams.toString()
      router.replace(nextQuery ? `/runs?${nextQuery}` : '/runs')
    }, 250)
    return () => window.clearTimeout(handle)
  }, [querySearch, router, searchInput, searchParams])

  function updateFilter(key: 'agent' | 'status', value: string) {
    const nextParams = new URLSearchParams(searchParams.toString())
    if (value === 'all') {
      nextParams.delete(key)
    } else {
      nextParams.set(key, value)
    }
    const nextQuery = nextParams.toString()
    router.replace(nextQuery ? `/runs?${nextQuery}` : '/runs')
  }

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
        const wsIsFresher = existing.last_seq > run.last_seq
        return {
          ...run,
          status: wsIsFresher ? existing.status : run.status,
          last_seq: Math.max(existing.last_seq, run.last_seq),
          error_code: wsIsFresher ? (existing.error_code ?? run.error_code) : run.error_code,
          error_message: wsIsFresher ? (existing.error_message ?? run.error_message) : run.error_message,
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

  const runs = useMemo(() => liveRuns, [liveRuns])

  return (
    <div className="flex h-full flex-col bg-[var(--bg)]">
      <div className="border-b border-[var(--border)] bg-[var(--surface-elevated)] px-6 py-4">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <Activity className="h-5 w-5 text-[var(--skill-brand-600)]" />
              <h1 className="text-lg font-semibold text-[var(--text-primary)]">
                {t('runs.title')}
              </h1>
            </div>
            <p className="mt-1 text-sm text-[var(--text-muted)]">
              {t('runs.description')}
            </p>
          </div>

          <div className="w-full max-w-xl">
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--text-muted)]" />
              <Input
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
                placeholder={t('runs.searchPlaceholder')}
                className="pl-9"
              />
            </div>
          </div>
        </div>
        <div className="mt-4 flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant={selectedAgent === 'all' ? 'default' : 'outline'}
              size="sm"
              onClick={() => updateFilter('agent', 'all')}
            >
              {t('runs.filterAllAgents')}
            </Button>
            {(agentData?.items || []).map((agent) => (
              <Button
                key={agent.agent_name}
                variant={selectedAgent === agent.agent_name ? 'default' : 'outline'}
                size="sm"
                onClick={() => updateFilter('agent', agent.agent_name)}
              >
                {agent.display_name}
              </Button>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {statusOptions.map((status) => (
              <Button
                key={status}
                variant={statusFilter === status ? 'default' : 'outline'}
                size="sm"
                onClick={() => updateFilter('status', status)}
              >
                {status === 'all' ? t('runs.filterAll') : formatRunStatus(status, t)}
              </Button>
            ))}
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-6">
        {isLoading ? (
          <div className="flex items-center gap-2 text-sm text-[var(--text-muted)]">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t('runs.loading')}
          </div>
        ) : runs.length === 0 ? (
          <Card className="border-dashed border-[var(--border)] bg-[var(--surface-1)] p-8 text-center">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-[var(--surface-3)] text-[var(--text-muted)]">
              <Activity className="h-5 w-5" />
            </div>
            <h2 className="mt-4 text-sm font-semibold text-[var(--text-primary)]">
              {t('runs.emptyTitle')}
            </h2>
            <p className="mt-1 text-sm text-[var(--text-muted)]">
              {t('runs.emptyDescription')}
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
