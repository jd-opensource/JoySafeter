'use client'

/**
 * Instance and device management (combined logic)
 *
 * Order: instance first, then devices
 * - Instance: one OpenClaw container per user; must be started before using WebUI or device pairing
 * - Devices: only available when instance is running; listed/approved via openclaw CLI inside the container
 * - Dependency: device list and approval both depend on a running instance, so instance status is fetched first
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Check,
  CheckCheck,
  Copy,
  Loader2,
  Play,
  Power,
  RefreshCw,
  Server,
  Smartphone,
  Trash2,
} from 'lucide-react'
import { useState } from 'react'

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useToast } from '@/hooks/use-toast'
import { apiDelete, apiGet, apiPost } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'

interface InstanceStatus {
  exists: boolean
  id?: string
  status?: string
  gatewayPort?: number
  gatewayToken?: string
  containerId?: string
  alive?: boolean
  lastActiveAt?: string | null
  errorMessage?: string | null
}

interface DeviceInfo {
  deviceId: string
  platform?: string
  clientId?: string
  createdAtMs?: number
  approvedAtMs?: number
}

interface DeviceResponse {
  pending?: DeviceInfo[]
  paired?: DeviceInfo[]
}

const instanceStatusStyles: Record<string, string> = {
  running: 'bg-green-500/15 text-green-700 border-green-200',
  starting: 'bg-blue-500/15 text-blue-700 border-blue-200',
  pending: 'bg-[var(--text-tertiary)] text-[var(--text-secondary)] border-[var(--border)]',
  stopped: 'bg-[var(--text-tertiary)] text-[var(--text-secondary)] border-[var(--border)]',
  failed: 'bg-red-500/15 text-red-700 border-red-200',
}

export function OpenClawManagement() {
  const { t } = useTranslation()
  const { toast } = useToast()
  const queryClient = useQueryClient()
  const [copiedToken, setCopiedToken] = useState(false)

  const handleCopyToken = (token: string) => {
    navigator.clipboard.writeText(token)
    setCopiedToken(true)
    setTimeout(() => setCopiedToken(false), 2000)
  }

  const { data: instance, isLoading: instanceLoading } = useQuery<InstanceStatus>({
    queryKey: ['openclaw-instance'],
    queryFn: () => apiGet<InstanceStatus>('openclaw/instances'),
    refetchInterval: 8_000,
  })

  const instanceRunning =
    instance?.exists && (instance.status === 'running' || instance.status === 'starting')

  const { data: deviceData, isLoading: devicesLoading } = useQuery<DeviceResponse>({
    queryKey: ['openclaw-devices'],
    queryFn: () => apiGet<DeviceResponse>('openclaw/devices'),
    refetchInterval: 10_000,
    enabled: !!instanceRunning,
  })

  const startMutation = useMutation({
    mutationFn: () => apiPost('openclaw/instances'),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['openclaw-instance'] }),
    onError: (err: unknown) => {
      toast({
        title: t('common.error'),
        description: err instanceof Error ? err.message : t('common.operationFailed'),
        variant: 'destructive',
      })
    },
  })
  const stopMutation = useMutation({
    mutationFn: () => apiPost('openclaw/instances/stop'),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['openclaw-instance'] }),
    onError: (err: unknown) => {
      toast({
        title: t('common.error'),
        description: err instanceof Error ? err.message : t('common.operationFailed'),
        variant: 'destructive',
      })
    },
  })
  const restartMutation = useMutation({
    mutationFn: () => apiPost('openclaw/instances/restart'),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['openclaw-instance'] })
      queryClient.invalidateQueries({ queryKey: ['openclaw-devices'] })
    },
    onError: (err: unknown) => {
      toast({
        title: t('common.error'),
        description: err instanceof Error ? err.message : t('common.operationFailed'),
        variant: 'destructive',
      })
    },
  })
  const deleteMutation = useMutation({
    mutationFn: () => apiDelete('openclaw/instances'),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['openclaw-instance'] }),
    onError: (err: unknown) => {
      toast({
        title: t('common.error'),
        description: err instanceof Error ? err.message : t('common.operationFailed'),
        variant: 'destructive',
      })
    },
  })
  const approveMutation = useMutation({
    mutationFn: (id: string) => apiPost(`openclaw/devices/${id}/approve`),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['openclaw-devices'] }),
    onError: (err: unknown) => {
      toast({
        title: t('common.error'),
        description: err instanceof Error ? err.message : t('common.operationFailed'),
        variant: 'destructive',
      })
    },
  })
  const approveAllMutation = useMutation({
    mutationFn: () => apiPost('openclaw/devices/approve-all'),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['openclaw-devices'] }),
    onError: (err: unknown) => {
      toast({
        title: t('common.error'),
        description: err instanceof Error ? err.message : t('common.operationFailed'),
        variant: 'destructive',
      })
    },
  })

  const syncSkillsMutation = useMutation({
    mutationFn: () => apiPost<{ syncedCount: number }>('openclaw/instances/sync-skills'),
    onSuccess: (data) => {
      toast({
        title: t('common.success'),
        description: t('openclaw.syncSkillsSuccess', { count: data.syncedCount }),
      })
    },
    onError: (err: unknown) => {
      toast({
        title: t('common.error'),
        description: err instanceof Error ? err.message : t('openclaw.syncSkillsFailed'),
        variant: 'destructive',
      })
    },
  })

  const pending = deviceData?.pending ?? []
  const paired = deviceData?.paired ?? []
  const hasPending = pending.length > 0
  const isInstanceBusy =
    startMutation.isPending ||
    stopMutation.isPending ||
    restartMutation.isPending ||
    deleteMutation.isPending ||
    syncSkillsMutation.isPending

  if (instanceLoading) {
    return (
      <div className="flex items-center justify-center py-12 text-sm text-[var(--text-secondary)]">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        {t('common.loading')}
      </div>
    )
  }

  if (!instance?.exists) {
    return (
      <div className="flex flex-col items-center py-8">
        <Server className="mb-3 h-8 w-8 text-[var(--text-tertiary)]" />
        <p className="mb-4 text-sm text-[var(--text-secondary)]">
          {t('openclaw.instanceNotRunning')}
        </p>
        <Button onClick={() => startMutation.mutate()} disabled={isInstanceBusy}>
          {startMutation.isPending ? (
            <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
          ) : (
            <Play className="mr-1.5 h-4 w-4" />
          )}
          {t('openclaw.start')}
        </Button>
      </div>
    )
  }

  const status = instance.status ?? 'unknown'

  return (
    <div className="space-y-6">
      {/* instance info card */}
      <div className="flex flex-col overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--bg)] shadow-sm">
        {/* upper section: status and actions */}
        <div className="relative p-4 sm:p-5">
          <div className="flex flex-col gap-4">
            <div className="flex min-w-0 items-start gap-3.5">
              <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full border border-blue-500/20 bg-blue-500/10">
                <Server className="h-6 w-6 text-blue-600 dark:text-blue-400" />
              </div>
              <div className="flex min-w-0 flex-col gap-1.5">
                <h3 className="truncate text-base font-semibold leading-none tracking-tight text-[var(--text-primary)]">
                  {t('openclaw.instance')}
                </h3>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge
                    className={cn(
                      'truncate rounded border px-1.5 py-0 text-[10px] font-bold uppercase tracking-wider',
                      instanceStatusStyles[status] ?? instanceStatusStyles.failed,
                    )}
                  >
                    {status}
                  </Badge>
                  {instance.alive !== undefined && (
                    <div className="flex items-center gap-1.5 text-xs font-medium text-[var(--text-secondary)]">
                      <span
                        className={cn(
                          'inline-block h-2 w-2 shrink-0 rounded-full',
                          instance.alive
                            ? 'bg-green-500 shadow-[0_0_6px_rgba(34,197,94,0.5)]'
                            : 'bg-red-500',
                        )}
                      />
                      <span className="truncate">
                        {instance.alive ? t('openclaw.online') : t('openclaw.offline')}
                      </span>
                    </div>
                  )}
                </div>
              </div>
            </div>

            <div className="mt-4 grid grid-cols-2 gap-2">
              {status !== 'running' && status !== 'starting' && (
                <Button
                  size="sm"
                  onClick={() => startMutation.mutate()}
                  disabled={isInstanceBusy}
                  className="col-span-2 h-8 shadow-sm"
                >
                  {startMutation.isPending ? (
                    <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Play className="mr-1.5 h-3.5 w-3.5" />
                  )}
                  {t('openclaw.start')}
                </Button>
              )}
              {status === 'running' && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => stopMutation.mutate()}
                  disabled={isInstanceBusy}
                  className="h-8 border-red-200 text-red-600 shadow-sm transition-colors hover:bg-red-50 hover:text-red-700 dark:border-red-900/50 dark:hover:bg-red-900/20"
                >
                  {stopMutation.isPending ? (
                    <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Power className="mr-1.5 h-3.5 w-3.5" />
                  )}
                  <span className="truncate">{t('openclaw.stop')}</span>
                </Button>
              )}
              <Button
                size="sm"
                variant="outline"
                onClick={() => restartMutation.mutate()}
                disabled={isInstanceBusy}
                className="h-8 shadow-sm transition-colors"
              >
                {restartMutation.isPending ? (
                  <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                ) : (
                  <RefreshCw className="mr-1.5 h-3.5 w-3.5" />
                )}
                <span className="truncate">{t('openclaw.restart')}</span>
              </Button>

              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={isInstanceBusy}
                    className="h-8 text-[var(--text-tertiary)] shadow-sm transition-colors hover:border-red-200 hover:bg-red-50 hover:text-red-600 dark:hover:border-red-900/50 dark:hover:bg-red-900/20"
                    title={t('openclaw.deleteInstanceTitle')}
                  >
                    {deleteMutation.isPending ? (
                      <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                    ) : (
                      <Trash2 className="mr-1.5 h-4 w-4" />
                    )}
                    <span className="truncate">{t('common.delete', 'Delete')}</span>
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>
                      {t('openclaw.confirmDeleteInstance', 'Delete Instance?')}
                    </AlertDialogTitle>
                    <AlertDialogDescription>
                      {t(
                        'openclaw.confirmDeleteInstanceDesc',
                        'Are you sure you want to delete this OpenClaw instance?',
                      )}
                    </AlertDialogDescription>
                    <div className="mt-2 rounded-md border border-amber-200 bg-amber-50 p-3 dark:border-amber-900/30 dark:bg-amber-900/10">
                      <p className="text-sm font-medium text-amber-800 dark:text-amber-500">
                        {t(
                          'openclaw.deleteInstanceWarning',
                          'Warning: Deleting the instance will clear all of its execution history.',
                        )}
                      </p>
                    </div>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>{t('common.cancel', 'Cancel')}</AlertDialogCancel>
                    <AlertDialogAction
                      onClick={() => deleteMutation.mutate()}
                      className="border-0 bg-red-600 text-white hover:bg-red-700"
                    >
                      {t('common.confirm', 'Confirm')}
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            </div>
          </div>
        </div>

        {/* lower section: detailed info */}
        <div className="border-t border-[var(--border)] bg-[var(--bg)] p-4 sm:p-5">
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-tertiary)]">
                {t('openclaw.gatewayPort')}
              </span>
              <span className="font-mono text-sm font-medium text-[var(--text-primary)]">
                {instance.gatewayPort ?? '--'}
              </span>
            </div>
            <div className="flex flex-col gap-1.5">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-tertiary)]">
                {t('openclaw.containerId')}
              </span>
              <span className="font-mono text-sm font-medium text-[var(--text-primary)]">
                {instance.containerId ? instance.containerId.substring(0, 12) : '--'}
              </span>
            </div>
            <div className="flex flex-col gap-1.5">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-tertiary)]">
                {t('openclaw.token')}
              </span>
              {instance.gatewayToken ? (
                <div className="group flex min-w-0 items-center justify-between rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-1.5 shadow-sm">
                  <span
                    className="block min-w-0 flex-1 truncate font-mono text-sm text-[var(--text-secondary)]"
                    title={instance.gatewayToken}
                  >
                    {instance.gatewayToken}
                  </span>
                  <button
                    onClick={() => handleCopyToken(instance.gatewayToken!)}
                    className="-mr-1 ml-2 shrink-0 rounded-md p-1 text-[var(--text-tertiary)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--text-primary)]"
                    title={t('openclaw.copyToken')}
                  >
                    {copiedToken ? (
                      <Check className="h-4 w-4 text-green-500" />
                    ) : (
                      <Copy className="h-4 w-4" />
                    )}
                  </button>
                </div>
              ) : (
                <span className="font-mono text-sm font-medium text-[var(--text-tertiary)]">
                  --
                </span>
              )}
            </div>
          </div>

          {instance.errorMessage && (
            <div className="mt-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-600 dark:border-red-900/30 dark:bg-red-900/10">
              <span className="mb-1 block font-semibold">{t('openclaw.errorMessage')}</span>
              {instance.errorMessage}
            </div>
          )}
        </div>
      </div>

      {/* skill sync */}
      <div className="space-y-3">
        <div className="flex items-center justify-between px-1">
          <div className="flex items-center gap-2">
            <RefreshCw className="h-4 w-4 text-[var(--text-primary)]" />
            <h3 className="text-sm font-semibold text-[var(--text-primary)]">
              {t('openclaw.syncSkills')}
            </h3>
          </div>
        </div>
        <div className="overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--bg)] shadow-sm">
          {!instanceRunning ? (
            <div className="flex flex-col items-center justify-center p-8 text-center">
              <Server className="mb-3 h-8 w-8 text-[var(--text-tertiary)] opacity-60" />
              <p className="text-sm font-medium text-[var(--text-secondary)]">
                {t('openclaw.instanceNotRunning')}
              </p>
              <p className="mt-1 text-xs text-[var(--text-tertiary)]">
                {t('openclaw.startInstanceFirst')}
              </p>
            </div>
          ) : (
            <div className="flex flex-col justify-between gap-3 p-4 sm:flex-row sm:items-center">
              <div className="flex min-w-0 flex-col">
                <span className="text-sm font-medium text-[var(--text-primary)]">
                  {t(
                    'openclaw.syncSkillsDesc',
                    'Manually synchronize your configured skills to the OpenClaw container.',
                  )}
                </span>
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={() => syncSkillsMutation.mutate()}
                disabled={isInstanceBusy || syncSkillsMutation.isPending}
                className="h-8 w-full shrink-0 border-blue-200 text-blue-600 shadow-sm hover:bg-blue-50 hover:text-blue-700 dark:border-blue-900/50 dark:hover:bg-blue-900/20 sm:w-auto"
              >
                {syncSkillsMutation.isPending ? (
                  <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                ) : (
                  <RefreshCw className="mr-1.5 h-3.5 w-3.5" />
                )}
                {t('openclaw.syncSkills')}
              </Button>
            </div>
          )}
        </div>
      </div>

      {/* device pairing */}
      <div className="space-y-3">
        <div className="flex items-center justify-between px-1">
          <div className="flex items-center gap-2">
            <Smartphone className="h-4 w-4 text-[var(--text-primary)]" />
            <h3 className="text-sm font-semibold text-[var(--text-primary)]">
              {t('openclaw.devicePairing')}
            </h3>
          </div>
          {hasPending && (
            <Button
              variant="default"
              size="sm"
              onClick={() => approveAllMutation.mutate()}
              disabled={approveAllMutation.isPending}
              className="h-7 px-3 text-xs"
            >
              {approveAllMutation.isPending ? (
                <Loader2 className="mr-1.5 h-3 w-3 animate-spin" />
              ) : (
                <CheckCheck className="mr-1.5 h-3 w-3" />
              )}
              {t('openclaw.approveAll')}
            </Button>
          )}
        </div>

        <div className="overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--bg)] shadow-sm">
          {!instanceRunning ? (
            <div className="flex flex-col items-center justify-center p-8 text-center">
              <Server className="mb-3 h-8 w-8 text-[var(--text-tertiary)] opacity-60" />
              <p className="text-sm font-medium text-[var(--text-secondary)]">
                {t('openclaw.instanceNotRunning')}
              </p>
              <p className="mt-1 text-xs text-[var(--text-tertiary)]">
                {t('openclaw.startInstanceFirst')}
              </p>
            </div>
          ) : devicesLoading ? (
            <div className="flex items-center justify-center p-8 text-sm text-[var(--text-secondary)]">
              <Loader2 className="mr-2 h-5 w-5 animate-spin" />
              {t('openclaw.loadingDevices')}
            </div>
          ) : pending.length === 0 && paired.length === 0 ? (
            <div className="flex flex-col items-center justify-center p-8 text-center">
              <div className="bg-[var(--muted)] mb-3 flex h-12 w-12 items-center justify-center rounded-full">
                <Smartphone className="h-5 w-5 text-[var(--text-tertiary)]" />
              </div>
              <p className="text-sm font-medium text-[var(--text-secondary)]">
                {t('openclaw.noPairedDevices')}
              </p>
              <p className="mt-1 text-xs text-[var(--text-tertiary)]">
                {t('openclaw.operateOnClientToConnect')}
              </p>
            </div>
          ) : (
            <ul className="divide-y divide-[var(--border)]">
              {pending.map((d) => (
                <li
                  key={d.deviceId}
                  className="hover:bg-[var(--muted)] flex flex-col justify-between gap-3 p-3 transition-colors sm:flex-row sm:items-center sm:px-4"
                >
                  <div className="flex min-w-0 items-start gap-3">
                    <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-amber-500/10 text-amber-600 dark:bg-amber-500/20 dark:text-amber-400">
                      <Smartphone className="h-4 w-4" />
                    </div>
                    <div className="flex min-w-0 flex-col">
                      <span className="truncate text-sm font-medium text-[var(--text-primary)]">
                        {d.clientId || d.deviceId}
                      </span>
                      <span className="truncate text-xs text-[var(--text-tertiary)]">
                        {d.platform || t('openclaw.platformUnknown')} ·{' '}
                        {t('openclaw.statusPending')}
                      </span>
                    </div>
                  </div>
                  <Button
                    size="sm"
                    className="h-8 w-full sm:w-auto"
                    onClick={() => approveMutation.mutate(d.deviceId)}
                    disabled={approveMutation.isPending}
                  >
                    {approveMutation.isPending ? (
                      <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Check className="mr-1.5 h-3.5 w-3.5" />
                    )}
                    {t('openclaw.approveAccess')}
                  </Button>
                </li>
              ))}
              {paired.map((d) => (
                <li
                  key={d.deviceId}
                  className="hover:bg-[var(--muted)] flex items-center justify-between p-3 transition-colors sm:px-4"
                >
                  <div className="flex min-w-0 items-start gap-3">
                    <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-green-500/10 text-green-600 dark:bg-green-500/20 dark:text-green-400">
                      <CheckCheck className="h-4 w-4" />
                    </div>
                    <div className="flex min-w-0 flex-col">
                      <span className="truncate text-sm font-medium text-[var(--text-primary)]">
                        {d.clientId || d.deviceId}
                      </span>
                      <span className="truncate text-xs text-[var(--text-tertiary)]">
                        {d.platform || t('openclaw.platformUnknown')} · {t('openclaw.statusPaired')}
                      </span>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}
