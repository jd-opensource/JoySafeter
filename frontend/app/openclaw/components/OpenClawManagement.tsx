'use client'

/**
 * 实例与设备管理（合并逻辑）
 *
 * 逻辑顺序：先实例、后设备
 * - 实例：每用户一个 OpenClaw 容器，需先启动才能使用 WebUI 与设备配对
 * - 设备：仅在实例 running 时，在容器内通过 openclaw CLI 列出/批准设备
 * - 依赖：设备列表与批准都依赖「运行中的实例」，故先拉实例状态，再按需拉设备
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
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
import { useTranslation } from 'react-i18next'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { apiDelete, apiGet, apiPost } from '@/lib/api-client'
import { cn } from '@/lib/core/utils/cn'

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
  pending: 'bg-gray-500/15 text-gray-600 border-gray-200',
  stopped: 'bg-gray-500/15 text-gray-600 border-gray-200',
  failed: 'bg-red-500/15 text-red-700 border-red-200',
}

export function OpenClawManagement() {
  const { t } = useTranslation()
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

  const instanceRunning = instance?.exists && (instance.status === 'running' || instance.status === 'starting')

  const { data: deviceData, isLoading: devicesLoading } = useQuery<DeviceResponse>({
    queryKey: ['openclaw-devices'],
    queryFn: () => apiGet<DeviceResponse>('openclaw/devices'),
    refetchInterval: 10_000,
    enabled: !!instanceRunning,
  })

  const startMutation = useMutation({
    mutationFn: () => apiPost('openclaw/instances'),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['openclaw-instance'] }),
  })
  const stopMutation = useMutation({
    mutationFn: () => apiPost('openclaw/instances/stop'),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['openclaw-instance'] }),
  })
  const restartMutation = useMutation({
    mutationFn: () => apiPost('openclaw/instances/restart'),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['openclaw-instance'] })
      queryClient.invalidateQueries({ queryKey: ['openclaw-devices'] })
    },
  })
  const deleteMutation = useMutation({
    mutationFn: () => apiDelete('openclaw/instances'),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['openclaw-instance'] }),
  })
  const approveMutation = useMutation({
    mutationFn: (id: string) => apiPost(`openclaw/devices/${id}/approve`),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['openclaw-devices'] }),
  })
  const approveAllMutation = useMutation({
    mutationFn: () => apiPost('openclaw/devices/approve-all'),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['openclaw-devices'] }),
  })

  const pending = deviceData?.pending ?? []
  const paired = deviceData?.paired ?? []
  const hasPending = pending.length > 0
  const isInstanceBusy =
    startMutation.isPending || stopMutation.isPending || restartMutation.isPending || deleteMutation.isPending

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
        <p className="mb-4 text-sm text-[var(--text-secondary)]">{t('openclaw.instanceNotRunning')}</p>
        <Button onClick={() => startMutation.mutate()} disabled={isInstanceBusy}>
          {startMutation.isPending ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <Play className="mr-1.5 h-4 w-4" />}
          {t('openclaw.start')}
        </Button>
      </div>
    )
  }

  const status = instance.status ?? 'unknown'

  return (
    <div className="space-y-6">
      {/* 实例信息卡片 */}
      <div className="flex flex-col rounded-xl border border-[var(--border)] bg-[var(--bg)] shadow-sm overflow-hidden">
        {/* 上半部分：状态与操作 */}
        <div className="p-4 sm:p-5 relative">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div className="flex items-start gap-3.5">
              <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-blue-500/10 border border-blue-500/20">
                <Server className="h-6 w-6 text-blue-600 dark:text-blue-400" />
              </div>
              <div className="flex flex-col gap-1.5 min-w-0">
                <h3 className="text-base font-semibold text-[var(--text-primary)] leading-none tracking-tight truncate">
                  {t('openclaw.instance')}
                </h3>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge className={cn('px-1.5 py-0 text-[10px] uppercase font-bold tracking-wider rounded border truncate', instanceStatusStyles[status] ?? instanceStatusStyles.failed)}>
                    {status}
                  </Badge>
                  {instance.alive !== undefined && (
                    <div className="flex items-center gap-1.5 text-xs font-medium text-[var(--text-secondary)]">
                      <span
                        className={cn(
                          'inline-block h-2 w-2 rounded-full shrink-0',
                          instance.alive ? 'bg-green-500 shadow-[0_0_6px_rgba(34,197,94,0.5)]' : 'bg-red-500',
                        )}
                      />
                      <span className="truncate">{instance.alive ? t('openclaw.online') : t('openclaw.offline')}</span>
                    </div>
                  )}
                </div>
              </div>
            </div>

            <div className="flex shrink-0 gap-2 items-center self-end sm:self-start">
              {status !== 'running' && status !== 'starting' && (
                <Button size="sm" onClick={() => startMutation.mutate()} disabled={isInstanceBusy} className="h-8 shadow-sm">
                  {startMutation.isPending ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Play className="mr-1.5 h-3.5 w-3.5" />}
                  {t('openclaw.start')}
                </Button>
              )}
              {status === 'running' && (
                <Button size="sm" variant="outline" onClick={() => stopMutation.mutate()} disabled={isInstanceBusy} className="h-8 border-red-200 text-red-600 hover:bg-red-50 hover:text-red-700 dark:border-red-900/50 dark:hover:bg-red-900/20 shadow-sm">
                  {stopMutation.isPending ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Power className="mr-1.5 h-3.5 w-3.5" />}
                  {t('openclaw.stop')}
                </Button>
              )}
              <Button size="sm" variant="secondary" onClick={() => restartMutation.mutate()} disabled={isInstanceBusy} className="h-8 shadow-sm">
                {restartMutation.isPending ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="mr-1.5 h-3.5 w-3.5" />}
                {t('openclaw.restart')}
              </Button>
              <Button
                size="icon"
                variant="ghost"
                onClick={() => deleteMutation.mutate()}
                disabled={isInstanceBusy}
                className="h-8 w-8 text-[var(--text-tertiary)] hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-900/20 rounded-md"
                title={t('openclaw.deleteInstanceTitle')}
              >
                {deleteMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
              </Button>
            </div>
          </div>
        </div>

        {/* 下半部分：详细信息 */}
        <div className="border-t border-[var(--border)] bg-[var(--muted)]/20 p-4 sm:p-5">
          <div className="grid grid-cols-2 gap-y-4 gap-x-6">
            <div className="flex flex-col gap-1.5">
              <span className="text-[11px] font-semibold text-[var(--text-tertiary)] uppercase tracking-wider">{t('openclaw.gatewayPort')}</span>
              <span className="font-mono text-sm font-medium text-[var(--text-primary)]">
                {instance.gatewayPort ?? '--'}
              </span>
            </div>
            <div className="flex flex-col gap-1.5">
              <span className="text-[11px] font-semibold text-[var(--text-tertiary)] uppercase tracking-wider">{t('openclaw.containerId')}</span>
              <span className="font-mono text-sm font-medium text-[var(--text-primary)]">
                {instance.containerId ? instance.containerId.substring(0, 12) : '--'}
              </span>
            </div>
            <div className="col-span-2 flex flex-col gap-1.5 mt-1">
              <span className="text-[11px] font-semibold text-[var(--text-tertiary)] uppercase tracking-wider">{t('openclaw.token')}</span>
              {instance.gatewayToken ? (
                <div className="group flex items-center justify-between rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-1.5 shadow-sm">
                  <span className="block truncate font-mono text-sm text-[var(--text-secondary)]" title={instance.gatewayToken}>
                    {instance.gatewayToken}
                  </span>
                  <button
                    onClick={() => handleCopyToken(instance.gatewayToken!)}
                    className="p-1 -mr-1 rounded-md text-[var(--text-tertiary)] transition-colors hover:text-[var(--text-primary)] hover:bg-[var(--muted)] shrink-0 ml-2"
                    title={t('openclaw.copyToken')}
                  >
                    {copiedToken ? <Check className="h-4 w-4 text-green-500" /> : <Copy className="h-4 w-4" />}
                  </button>
                </div>
              ) : (
                <span className="font-mono text-sm font-medium text-[var(--text-tertiary)]">--</span>
              )}
            </div>
          </div>

          {instance.errorMessage && (
            <div className="mt-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-600 dark:border-red-900/30 dark:bg-red-900/10">
              <span className="font-semibold block mb-1">{t('openclaw.errorMessage')}</span>
              {instance.errorMessage}
            </div>
          )}
        </div>
      </div>

      {/* 设备配对 */}
      <div className="space-y-3">
        <div className="flex items-center justify-between px-1">
          <div className="flex items-center gap-2">
            <Smartphone className="h-4 w-4 text-[var(--text-primary)]" />
            <h3 className="text-sm font-semibold text-[var(--text-primary)]">{t('openclaw.devicePairing')}</h3>
          </div>
          {hasPending && (
            <Button
              variant="default"
              size="sm"
              onClick={() => approveAllMutation.mutate()}
              disabled={approveAllMutation.isPending}
              className="h-7 px-3 text-xs"
            >
              {approveAllMutation.isPending ? <Loader2 className="mr-1.5 h-3 w-3 animate-spin" /> : <CheckCheck className="mr-1.5 h-3 w-3" />}
              {t('openclaw.approveAll')}
            </Button>
          )}
        </div>

        <div className="overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--bg)] shadow-sm">
          {!instanceRunning ? (
            <div className="flex flex-col items-center justify-center p-8 text-center bg-[var(--muted)]/10">
              <Server className="mb-3 h-8 w-8 text-[var(--text-tertiary)] opacity-60" />
              <p className="text-sm font-medium text-[var(--text-secondary)]">{t('openclaw.instanceNotRunning')}</p>
              <p className="mt-1 text-xs text-[var(--text-tertiary)]">{t('openclaw.startInstanceFirst')}</p>
            </div>
          ) : devicesLoading ? (
            <div className="flex items-center justify-center p-8 text-sm text-[var(--text-secondary)] bg-[var(--muted)]/10">
              <Loader2 className="mr-2 h-5 w-5 animate-spin" />
              {t('openclaw.loadingDevices')}
            </div>
          ) : pending.length === 0 && paired.length === 0 ? (
            <div className="flex flex-col items-center justify-center p-8 text-center bg-[var(--muted)]/10">
              <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-[var(--muted)]/50">
                <Smartphone className="h-5 w-5 text-[var(--text-tertiary)]" />
              </div>
              <p className="text-sm font-medium text-[var(--text-secondary)]">{t('openclaw.noPairedDevices')}</p>
              <p className="mt-1 text-xs text-[var(--text-tertiary)]">{t('openclaw.operateOnClientToConnect')}</p>
            </div>
          ) : (
            <ul className="divide-y divide-[var(--border)]">
              {pending.map((d) => (
                <li key={d.deviceId} className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-3 sm:px-4 hover:bg-[var(--muted)]/30 transition-colors">
                  <div className="flex items-center gap-3">
                    <div className="flex h-8 w-8 items-center justify-center rounded-md bg-amber-500/10 text-amber-600 dark:bg-amber-500/20 dark:text-amber-400">
                      <Smartphone className="h-4 w-4" />
                    </div>
                    <div className="flex flex-col">
                      <span className="text-sm font-medium text-[var(--text-primary)]">{d.clientId || d.deviceId}</span>
                      <span className="text-xs text-[var(--text-tertiary)]">{d.platform || t('openclaw.platformUnknown')} · {t('openclaw.statusPending')}</span>
                    </div>
                  </div>
                  <Button
                    size="sm"
                    className="h-8 w-full sm:w-auto"
                    onClick={() => approveMutation.mutate(d.deviceId)}
                    disabled={approveMutation.isPending}
                  >
                    {approveMutation.isPending ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Check className="mr-1.5 h-3.5 w-3.5" />}
                    {t('openclaw.approveAccess')}
                  </Button>
                </li>
              ))}
              {paired.map((d) => (
                <li key={d.deviceId} className="flex items-center justify-between p-3 sm:px-4 hover:bg-[var(--muted)]/30 transition-colors">
                  <div className="flex items-center gap-3">
                    <div className="flex h-8 w-8 items-center justify-center rounded-md bg-green-500/10 text-green-600 dark:bg-green-500/20 dark:text-green-400">
                      <CheckCheck className="h-4 w-4" />
                    </div>
                    <div className="flex flex-col">
                      <span className="text-sm font-medium text-[var(--text-primary)]">{d.clientId || d.deviceId}</span>
                      <span className="text-xs text-[var(--text-tertiary)]">{d.platform || t('openclaw.platformUnknown')} · {t('openclaw.statusPaired')}</span>
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
