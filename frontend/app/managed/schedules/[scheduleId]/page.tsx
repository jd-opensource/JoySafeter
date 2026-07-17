'use client'

import { useQueryClient } from '@tanstack/react-query'
import { Play, Pencil, Trash2, ExternalLink } from 'lucide-react'
import { useRouter } from 'next/navigation'
import React, { useEffect, useRef, useState } from 'react'

import { CreateScheduleDialog } from '@/components/managed/schedules/create-schedule-dialog'
import {
  PageHeader,
  ResourceErrorState,
  StatusBadge,
  MonoId,
  RelativeTime,
  DataTable,
  type Column,
  ConfirmDialog,
} from '@/components/managed/shared'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Switch } from '@/components/ui/switch'
import {
  currentProjectAllowsWrite,
  useCurrentProjectReadOnly,
} from '@/hooks/managed/use-current-project-read-only'
import { useTranslation } from '@/lib/i18n'
import { describeCron } from '@/lib/managed/cron'
import { toastOperationError } from '@/lib/managed/errors'
import { stripIdPrefix } from '@/lib/managed/id'
import { toastSuccess } from '@/lib/utils/toast'
import {
  useSchedule,
  useScheduleRuns,
  useToggleSchedule,
  useTriggerSchedule,
  useDeleteSchedule,
  type ScheduleRun,
} from '@/lib/managed/schedules'
import {
  managedScopeKey,
  type ManagedRequestScope,
  useManagedRequestScope,
} from '@/lib/managed/request-scope'
import { useProjectStore } from '@/stores/managed/project-store'

export default function ScheduleDetailPage({
  params,
}: {
  params: Promise<{ scheduleId: string }>
}) {
  const { scheduleId: rawId } = React.use(params)
  const scheduleId = stripIdPrefix(rawId || '')
  const { t } = useTranslation()
  const locale = (t('_locale') === 'zh' ? 'zh' : 'en') as 'en' | 'zh'
  const router = useRouter()
  const queryClient = useQueryClient()
  const projectReadOnly = useCurrentProjectReadOnly()
  const managedScope = useManagedRequestScope()
  const managedScopeRef = useRef(managedScope.key)
  const managedRequestScopeRef = useRef<ManagedRequestScope>(managedScope)

  const [editOpen, setEditOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)

  const scheduleQuery = useSchedule(scheduleId)
  const runsQuery = useScheduleRuns(scheduleId)
  const toggleMut = useToggleSchedule()
  const triggerMut = useTriggerSchedule()
  const deleteMut = useDeleteSchedule()

  const schedule = scheduleQuery.data
  const runs = runsQuery.data ?? []

  useEffect(() => {
    if (managedScopeRef.current !== managedScope.key) {
      setEditOpen(false)
      setDeleteOpen(false)
    }
    managedScopeRef.current = managedScope.key
    managedRequestScopeRef.current = managedScope
  }, [managedScope.key])

  useEffect(() => {
    if (projectReadOnly) {
      setEditOpen(false)
      setDeleteOpen(false)
    }
  }, [projectReadOnly])

  const currentManagedScopeAllowsWrite = () => {
    const { currentOrgId: orgId, currentProjectId: projectId } = useProjectStore.getState()
    return (
      managedScopeRef.current === managedScopeKey(orgId, projectId) && currentProjectAllowsWrite()
    )
  }

  const handleTrigger = async () => {
    if (!currentManagedScopeAllowsWrite()) return
    const requestScope = managedRequestScopeRef.current
    try {
      await triggerMut.mutateAsync({ id: scheduleId, requestScope })
      toastSuccess(t('managed.schedules.triggered', { name: schedule?.name ?? '' }))
    } catch (err) {
      toastOperationError(t, err, 'managed.schedules.triggerFailed')
    }
  }

  const handleToggle = async (enabled: boolean) => {
    if (!currentManagedScopeAllowsWrite()) return
    const requestScope = managedRequestScopeRef.current
    try {
      await toggleMut.mutateAsync({ id: scheduleId, enabled, requestScope })
      // The toggle hook only patches the list caches; refresh this detail view.
      queryClient.invalidateQueries({ queryKey: ['schedule', requestScope.key, scheduleId] })
    } catch (err) {
      toastOperationError(t, err, 'managed.schedules.toggleFailed')
    }
  }

  const handleDelete = async () => {
    if (!currentManagedScopeAllowsWrite()) {
      setDeleteOpen(false)
      return
    }
    const requestScope = managedRequestScopeRef.current
    try {
      await deleteMut.mutateAsync({ id: scheduleId, requestScope })
      router.push('/managed/schedules')
    } catch (err) {
      toastOperationError(t, err, 'managed.schedules.deleteFailed')
      setDeleteOpen(false)
    }
  }

  if (scheduleQuery.isError) {
    return (
      <ResourceErrorState
        error={scheduleQuery.error}
        resource="schedule"
        backLabel={t('managed.schedules.backToSchedules')}
        onBack={() => router.push('/managed/schedules')}
      />
    )
  }

  if (scheduleQuery.isLoading || !schedule) {
    return <div className="text-muted-foreground">{t('common.loading')}</div>
  }

  const canWrite = !projectReadOnly

  const runColumns: Column<ScheduleRun>[] = [
    {
      key: 'status',
      header: t('managed.table.status'),
      width: '14%',
      render: (r) => (
        <div className="flex items-center gap-1.5">
          <StatusBadge status={r.status} />
          {r.retry_count > 0 && (
            <span
              className="text-[10px] text-muted-foreground"
              title={t('managed.schedules.runs.retries', { count: r.retry_count })}
            >
              ↻{r.retry_count}
            </span>
          )}
        </div>
      ),
    },
    {
      key: 'created_at',
      header: t('managed.schedules.runs.firedAt'),
      render: (r) => (
        <span className="text-xs text-muted-foreground">
          <RelativeTime date={r.created_at} />
        </span>
      ),
    },
    {
      key: 'started_at',
      header: t('managed.schedules.runs.startedAt'),
      render: (r) =>
        r.started_at ? (
          <span className="text-xs text-muted-foreground">
            <RelativeTime date={r.started_at} />
          </span>
        ) : (
          <span className="text-xs text-muted-foreground">—</span>
        ),
    },
    {
      key: 'completed_at',
      header: t('managed.schedules.runs.completedAt'),
      render: (r) =>
        r.completed_at ? (
          <span className="text-xs text-muted-foreground">
            <RelativeTime date={r.completed_at} />
          </span>
        ) : (
          <span className="text-xs text-muted-foreground">—</span>
        ),
    },
    {
      key: 'error',
      header: t('managed.schedules.runs.error'),
      render: (r) =>
        r.error ? (
          <span className="block max-w-[280px] truncate text-xs text-destructive" title={r.error}>
            {r.error}
          </span>
        ) : (
          <span className="text-xs text-muted-foreground">—</span>
        ),
    },
    {
      key: 'session',
      header: t('managed.schedules.runs.session'),
      width: '10%',
      render: (r) =>
        r.chat_session_id ? (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              router.push(`/managed/sessions/${r.chat_session_id}`)
            }}
            className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
          >
            {t('managed.schedules.runs.open')}
            <ExternalLink className="h-3 w-3" />
          </button>
        ) : (
          <span className="text-xs text-muted-foreground">—</span>
        ),
    },
  ]

  const summary: { label: string; value: React.ReactNode }[] = [
    {
      label: t('managed.schedules.schedule'),
      value: (
        <div>
          <div>{describeCron(schedule.cron_expr, locale)}</div>
          <div className="font-mono text-xs text-muted-foreground">
            {schedule.cron_expr} · {schedule.timezone}
          </div>
        </div>
      ),
    },
    {
      label: t('managed.schedules.nextRun'),
      value:
        schedule.enabled && schedule.next_run_at ? (
          <RelativeTime date={schedule.next_run_at} />
        ) : (
          '—'
        ),
    },
    {
      label: t('managed.schedules.lastFired'),
      value: schedule.last_fired_slot ? <RelativeTime date={schedule.last_fired_slot} /> : '—',
    },
    {
      label: t('managed.schedules.agent'),
      value: <MonoId id={schedule.agent_id} />,
    },
    {
      label: t('managed.schedules.concurrency'),
      value: t(`managed.schedules.policy.${schedule.concurrency_policy}`),
    },
    {
      label: t('managed.schedules.timeoutSec'),
      value: `${schedule.timeout_sec}s`,
    },
    {
      label: t('managed.schedules.maxRetries'),
      value: schedule.max_retries,
    },
  ]

  return (
    <div>
      <PageHeader
        title={schedule.name}
        titleExtra={<StatusBadge status={schedule.enabled ? 'active' : 'idle'} />}
        breadcrumb={[
          { label: t('managed.schedules.title'), to: '/managed/schedules' },
          { label: schedule.name },
        ]}
        action={
          canWrite ? (
            <div className="flex items-center gap-2">
              <div className="flex items-center gap-1.5 rounded-md border px-2.5 py-1">
                <span className="text-xs text-muted-foreground">
                  {t('managed.schedules.enabled')}
                </span>
                <Switch
                  checked={schedule.enabled}
                  disabled={toggleMut.isPending}
                  onCheckedChange={handleToggle}
                  aria-label={t('managed.schedules.enabled')}
                />
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={handleTrigger}
                disabled={triggerMut.isPending}
              >
                <Play className="mr-1.5 h-3.5 w-3.5" />
                {t('managed.schedules.runNow')}
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  if (!currentManagedScopeAllowsWrite()) return
                  setEditOpen(true)
                }}
              >
                <Pencil className="mr-1.5 h-3.5 w-3.5" />
                {t('common.edit')}
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  if (!currentManagedScopeAllowsWrite()) return
                  setDeleteOpen(true)
                }}
              >
                <Trash2 className="mr-1.5 h-3.5 w-3.5" />
                {t('common.delete')}
              </Button>
            </div>
          ) : null
        }
      />

      <div className="mb-6 flex items-center gap-1.5 text-sm text-muted-foreground">
        <MonoId id={schedule.id} truncate={false} />
        <span>·</span>
        <RelativeTime date={schedule.created_at} />
      </div>

      <Card className="mb-6">
        <CardHeader>
          <CardTitle className="text-base">{t('managed.schedules.configuration')}</CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3">
            {summary.map((item) => (
              <div key={item.label}>
                <dt className="text-xs uppercase tracking-wider text-muted-foreground">
                  {item.label}
                </dt>
                <dd className="mt-1 text-sm text-foreground">{item.value}</dd>
              </div>
            ))}
          </dl>
          {schedule.prompt && (
            <div className="mt-5">
              <dt className="text-xs uppercase tracking-wider text-muted-foreground">
                {t('managed.schedules.prompt')}
              </dt>
              <dd className="mt-1 whitespace-pre-wrap rounded-md bg-muted/40 p-3 text-sm text-foreground">
                {schedule.prompt}
              </dd>
            </div>
          )}
        </CardContent>
      </Card>

      <h2 className="mb-4 text-lg font-semibold">{t('managed.schedules.runHistory')}</h2>
      <DataTable
        columns={runColumns}
        data={runs}
        loading={runsQuery.isLoading}
        fetching={runsQuery.isFetching}
        emptyMessage={t('managed.schedules.runs.empty')}
      />

      <CreateScheduleDialog
        open={canWrite && editOpen}
        schedule={schedule}
        onOpenChange={(open) => {
          if (open && !currentManagedScopeAllowsWrite()) return
          setEditOpen(open)
          if (!open) {
            queryClient.invalidateQueries({
              queryKey: ['schedule', managedRequestScopeRef.current.key, scheduleId],
            })
          }
        }}
      />

      <ConfirmDialog
        open={canWrite && deleteOpen}
        title={t('managed.schedules.deleteTitle')}
        description={t('managed.schedules.deleteDescription', { name: schedule.name })}
        confirmLabel={t('common.delete')}
        destructive
        onConfirm={handleDelete}
        onCancel={() => setDeleteOpen(false)}
      />
    </div>
  )
}
