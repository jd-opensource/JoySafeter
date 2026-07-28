'use client'

import { useQueryClient } from '@tanstack/react-query'
import { Play, Pencil, Trash2, ExternalLink, Zap, AlertTriangle } from 'lucide-react'
import { useRouter } from 'next/navigation'
import React, { useState } from 'react'

import {
  PageHeader,
  ResourceErrorState,
  StatusBadge,
  MonoId,
  RelativeTime,
  DataTable,
  type Column,
  ConfirmDialog,
  CopyButton,
} from '@/components/managed/shared'
import { CreateTriggerDialog } from '@/components/managed/triggers/create-trigger-dialog'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Switch } from '@/components/ui/switch'
import { currentProjectAllowsWrite } from '@/hooks/managed/use-current-project-read-only'
import { useScopedActions } from '@/hooks/managed/use-scoped-actions'
import { useTranslation } from '@/lib/i18n'
import { describeCron } from '@/lib/managed/cron'
import { toastOperationError } from '@/lib/managed/errors'
import { stripIdPrefix } from '@/lib/managed/id'
import {
  fireResultToastMessage,
  formatRunOnce,
  triggerLifecycleStatus,
} from '@/lib/managed/trigger-format'
import {
  useAgentTrigger,
  useTriggerRuns,
  useToggleAgentTrigger,
  useRunTrigger,
  useTestFireWebhook,
  useDeleteAgentTrigger,
  useWebhookSample,
  type TriggerRun,
} from '@/lib/managed/triggers'
import { toastSuccess } from '@/lib/utils/toast'

export default function TriggerDetailPage({
  params,
}: {
  params: Promise<{ triggerId: string }>
}) {
  const { triggerId: rawId } = React.use(params)
  const triggerId = stripIdPrefix(rawId || '')
  const { t } = useTranslation()
  const locale = (t('_locale') === 'zh' ? 'zh' : 'en') as 'en' | 'zh'
  const router = useRouter()
  const queryClient = useQueryClient()
  const { scope, readOnly, scopeIsActive } = useScopedActions({
    onReset: () => {
      setEditOpen(false)
      setDeleteOpen(false)
    },
  })

  const [editOpen, setEditOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)

  const triggerQuery = useAgentTrigger(triggerId)
  const runsQuery = useTriggerRuns(triggerId)
  const toggleMut = useToggleAgentTrigger()
  const runMut = useRunTrigger(triggerId)
  const testMut = useTestFireWebhook(triggerId)
  const deleteMut = useDeleteAgentTrigger()

  const trigger = triggerQuery.data
  const runs = runsQuery.data ?? []
  const isWebhook = trigger?.type === 'webhook'

  const webhookSample = useWebhookSample(triggerId, !!isWebhook)

  const handleRun = async () => {
    if (!currentProjectAllowsWrite() || !scopeIsActive()) return
    try {
      const res = await runMut.mutateAsync({})
      toastSuccess(fireResultToastMessage(t, res.status, trigger?.name ?? '', res.reason))
    } catch (err) {
      toastOperationError(t, err, 'managed.triggers.fireFailed')
    }
  }

  const handleTestFire = async () => {
    if (!currentProjectAllowsWrite() || !scopeIsActive()) return
    try {
      const res = await testMut.mutateAsync()
      toastSuccess(fireResultToastMessage(t, res.status, trigger?.name ?? '', res.reason))
    } catch (err) {
      toastOperationError(t, err, 'managed.triggers.fireFailed')
    }
  }

  const handleToggle = async (enabled: boolean) => {
    if (!currentProjectAllowsWrite() || !scopeIsActive()) return
    try {
      await toggleMut.mutateAsync({ id: triggerId, enabled })
    } catch (err) {
      toastOperationError(t, err, 'managed.triggers.toggleFailed')
    }
  }

  const handleDelete = async () => {
    if (!currentProjectAllowsWrite() || !scopeIsActive()) {
      setDeleteOpen(false)
      return
    }
    try {
      await deleteMut.mutateAsync(triggerId)
      router.push('/managed/triggers')
    } catch (err) {
      toastOperationError(t, err, 'managed.triggers.deleteFailed')
      setDeleteOpen(false)
    }
  }

  if (triggerQuery.isError) {
    return (
      <ResourceErrorState
        error={triggerQuery.error}
        resource="trigger"
        backLabel={t('managed.triggers.backToTriggers')}
        onBack={() => router.push('/managed/triggers')}
      />
    )
  }

  if (triggerQuery.isLoading || !trigger) {
    return <div className="text-muted-foreground">{t('common.loading')}</div>
  }

  const canWrite = !readOnly

  const runColumns: Column<TriggerRun>[] = [
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
              title={t('managed.triggers.runs.retries', { count: r.retry_count })}
            >
              ↻{r.retry_count}
            </span>
          )}
        </div>
      ),
    },
    {
      key: 'created_at',
      header: t('managed.triggers.runs.firedAt'),
      render: (r) => (
        <span className="text-xs text-muted-foreground">
          <RelativeTime date={r.created_at} />
        </span>
      ),
    },
    {
      key: 'started_at',
      header: t('managed.triggers.runs.startedAt'),
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
      header: t('managed.triggers.runs.completedAt'),
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
      header: t('managed.triggers.runs.error'),
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
      header: t('managed.triggers.runs.session'),
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
            {t('managed.triggers.runs.open')}
            <ExternalLink className="h-3 w-3" />
          </button>
        ) : (
          <span className="text-xs text-muted-foreground">—</span>
        ),
    },
  ]

  const scheduleValue = () => {
    if (trigger.run_at) return formatRunOnce(t, trigger.run_at)
    if (trigger.cron_expr) {
      return (
        <div>
          <div>{describeCron(trigger.cron_expr, locale)}</div>
          <div className="font-mono text-xs text-muted-foreground">
            {trigger.cron_expr} · {trigger.timezone}
          </div>
        </div>
      )
    }
    return '—'
  }

  const sessionModeValue = () => {
    const label = t(`managed.triggers.sessionModeOption.${trigger.session_mode || 'fresh'}`)
    if (trigger.session_mode === 'keyed' && trigger.session_key) {
      return (
        <div>
          <div>{label}</div>
          <div className="font-mono text-xs text-muted-foreground">{trigger.session_key}</div>
        </div>
      )
    }
    return label
  }

  const summary: { label: string; value: React.ReactNode }[] = [
    {
      label: t('managed.triggers.type'),
      value: t(`managed.triggers.typeOption.${trigger.type}`),
    },
  ]

  if (trigger.type === 'cron') {
    summary.push(
      { label: t('managed.triggers.schedule'), value: scheduleValue() },
      {
        label: t('managed.triggers.nextRun'),
        value:
          trigger.enabled && trigger.next_run_at ? (
            <RelativeTime date={trigger.next_run_at} />
          ) : (
            '—'
          ),
      },
      {
        label: t('managed.triggers.concurrency'),
        value: t(`managed.triggers.policy.${trigger.concurrency_policy ?? 'allow'}`),
      },
    )
  }

  if (trigger.type === 'webhook') {
    summary.push({
      label: t('managed.triggers.signing'),
      value: trigger.secret_ref
        ? t('managed.triggers.signedVia', { secret: trigger.secret_ref })
        : t('managed.triggers.unsigned'),
    })
  }

  summary.push(
    { label: t('managed.triggers.sessionMode'), value: sessionModeValue() },
    { label: t('managed.triggers.agent'), value: <MonoId id={trigger.agent_id} /> },
    { label: t('managed.triggers.timeoutSec'), value: `${trigger.timeout_sec}s` },
    { label: t('managed.triggers.maxRetries'), value: trigger.max_retries },
    {
      label: t('managed.triggers.lastFired'),
      value: trigger.last_fired_slot ? (
        <RelativeTime date={trigger.last_fired_slot} />
      ) : (
        t('managed.triggers.never')
      ),
    },
  )

  const lifecycleStatus = triggerLifecycleStatus(trigger)

  return (
    <div>
      <PageHeader
        title={trigger.name}
        titleExtra={
          lifecycleStatus === 'auto_disabled' ? (
            <StatusBadge status="auto_disabled" />
          ) : (
            <StatusBadge status={lifecycleStatus} />
          )
        }
        breadcrumb={[
          { label: t('managed.triggers.title'), to: '/managed/triggers' },
          { label: trigger.name },
        ]}
        action={
          canWrite ? (
            <div className="flex items-center gap-2">
              <div className="flex items-center gap-1.5 rounded-md border px-2.5 py-1">
                <span className="text-xs text-muted-foreground">
                  {t('managed.triggers.enabled')}
                </span>
                <Switch
                  checked={trigger.enabled}
                  disabled={toggleMut.isPending}
                  onCheckedChange={handleToggle}
                  aria-label={t('managed.triggers.enabled')}
                />
              </div>
              <Button variant="outline" size="sm" onClick={handleRun} disabled={runMut.isPending}>
                <Play className="mr-1.5 h-3.5 w-3.5" />
                {t('managed.triggers.runNow')}
              </Button>
              {isWebhook && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleTestFire}
                  disabled={testMut.isPending}
                >
                  <Zap className="mr-1.5 h-3.5 w-3.5" />
                  {t('managed.triggers.testFire')}
                </Button>
              )}
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  if (!currentProjectAllowsWrite() || !scopeIsActive()) return
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
                  if (!currentProjectAllowsWrite() || !scopeIsActive()) return
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
        <MonoId id={trigger.id} truncate={false} />
        <span>·</span>
        <RelativeTime date={trigger.created_at} />
      </div>

      {trigger.auto_disabled_at && (
        <div className="mb-6 flex items-start gap-3 rounded-md border border-amber-500/50 bg-amber-500/10 p-4">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-600 dark:text-amber-400" />
          <div className="min-w-0 space-y-1">
            <p className="text-sm font-medium text-foreground">
              {t('managed.triggers.autoDisabledTitle')}
            </p>
            <p className="text-sm text-muted-foreground">{t('managed.triggers.autoDisabledBody')}</p>
            {trigger.disabled_reason && (
              <p className="text-xs text-muted-foreground">
                {t('managed.triggers.autoDisabledReason', { reason: trigger.disabled_reason })}
              </p>
            )}
          </div>
        </div>
      )}

      <Card className="mb-6">
        <CardHeader>
          <CardTitle className="text-base">{t('managed.triggers.configuration')}</CardTitle>
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
          {trigger.prompt_template && (
            <div className="mt-5">
              <dt className="text-xs uppercase tracking-wider text-muted-foreground">
                {t('managed.triggers.prompt')}
              </dt>
              <dd className="mt-1 whitespace-pre-wrap rounded-md bg-muted/40 p-3 text-sm text-foreground">
                {trigger.prompt_template}
              </dd>
            </div>
          )}
        </CardContent>
      </Card>

      {isWebhook && (
        <Card className="mb-6">
          <CardHeader>
            <CardTitle className="text-base">{t('managed.triggers.endpoint')}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {trigger.webhook_url && (
              <div className="space-y-1.5">
                <dt className="text-xs uppercase tracking-wider text-muted-foreground">
                  {t('managed.triggers.endpoint')}
                </dt>
                <div className="flex items-center gap-2">
                  <code className="min-w-0 flex-1 truncate rounded bg-muted px-2 py-1.5 text-xs">
                    {trigger.webhook_url}
                  </code>
                  <CopyButton value={trigger.webhook_url} title={t('managed.triggers.copyUrl')} />
                </div>
                <p className="text-xs text-muted-foreground">
                  {t('managed.triggers.endpointHint')}
                </p>
              </div>
            )}

            {canWrite && webhookSample.data && (
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <dt className="text-xs uppercase tracking-wider text-muted-foreground">
                    {t('managed.triggers.curlSample')}
                  </dt>
                  <CopyButton
                    value={webhookSample.data.curl}
                    title={t('managed.triggers.copyCurl')}
                  />
                </div>
                <pre className="overflow-x-auto rounded-md bg-muted/40 p-3 text-xs leading-relaxed text-foreground">
                  {webhookSample.data.curl}
                </pre>
                <p className="text-xs text-muted-foreground">
                  {t('managed.triggers.curlSampleHint')}
                </p>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      <h2 className="mb-4 text-lg font-semibold">{t('managed.triggers.runHistory')}</h2>
      <DataTable
        columns={runColumns}
        data={runs}
        loading={runsQuery.isLoading}
        fetching={runsQuery.isFetching}
        emptyMessage={t('managed.triggers.runs.empty')}
      />

      <CreateTriggerDialog
        open={canWrite && editOpen}
        trigger={trigger}
        onOpenChange={(open) => {
          if (open && (!currentProjectAllowsWrite() || !scopeIsActive())) return
          setEditOpen(open)
          if (!open) {
            queryClient.invalidateQueries({ queryKey: ['trigger', scope.key, triggerId] })
          }
        }}
      />

      <ConfirmDialog
        open={canWrite && deleteOpen}
        title={t('managed.triggers.deleteTitle')}
        description={t('managed.triggers.deleteDescription', { name: trigger.name })}
        confirmLabel={t('common.delete')}
        destructive
        onConfirm={handleDelete}
        onCancel={() => setDeleteOpen(false)}
      />
    </div>
  )
}
