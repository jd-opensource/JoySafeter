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
import {
  Check,
  CheckCheck,
  Loader2,
  Play,
  Power,
  RefreshCw,
  Server,
  Smartphone,
  Trash2,
} from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { apiDelete, apiGet, apiPost } from '@/lib/api-client'
import { cn } from '@/lib/core/utils/cn'

interface InstanceStatus {
  exists: boolean
  id?: string
  status?: string
  gatewayPort?: number
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
  const queryClient = useQueryClient()

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
        加载中…
      </div>
    )
  }

  if (!instance?.exists) {
    return (
      <div className="flex flex-col items-center py-8">
        <Server className="mb-3 h-8 w-8 text-[var(--text-tertiary)]" />
        <p className="mb-4 text-sm text-[var(--text-secondary)]">暂无实例，请先启动 OpenClaw 实例。</p>
        <Button onClick={() => startMutation.mutate()} disabled={isInstanceBusy}>
          {startMutation.isPending ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <Play className="mr-1.5 h-4 w-4" />}
          启动实例
        </Button>
      </div>
    )
  }

  const status = instance.status ?? 'unknown'

  return (
    <div className="space-y-6">
      {/* 实例：一行摘要 + 操作 */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium text-[var(--text-primary)]">实例</span>
          <Badge className={cn('text-[10px]', instanceStatusStyles[status] ?? instanceStatusStyles.failed)}>
            {status}
          </Badge>
          {instance.alive !== undefined && (
            <span
              className={cn(
                'inline-block h-2 w-2 rounded-full',
                instance.alive ? 'bg-green-500' : 'bg-red-500',
              )}
              title={instance.alive ? 'Gateway 在线' : 'Gateway 离线'}
            />
          )}
          {instance.gatewayPort != null && (
            <span className="text-xs text-[var(--text-tertiary)]">端口 {instance.gatewayPort}</span>
          )}
          {instance.errorMessage && (
            <span className="text-xs text-red-600">{instance.errorMessage}</span>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          {status !== 'running' && status !== 'starting' && (
            <Button size="sm" onClick={() => startMutation.mutate()} disabled={isInstanceBusy}>
              {startMutation.isPending ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : <Play className="mr-1 h-3.5 w-3.5" />}
              启动
            </Button>
          )}
          {status === 'running' && (
            <Button size="sm" variant="outline" onClick={() => stopMutation.mutate()} disabled={isInstanceBusy}>
              {stopMutation.isPending ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : <Power className="mr-1 h-3.5 w-3.5" />}
              停止
            </Button>
          )}
          <Button size="sm" variant="outline" onClick={() => restartMutation.mutate()} disabled={isInstanceBusy}>
            {restartMutation.isPending ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="mr-1 h-3.5 w-3.5" />}
            重启
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="text-red-600 hover:text-red-700"
            onClick={() => deleteMutation.mutate()}
            disabled={isInstanceBusy}
          >
            {deleteMutation.isPending ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : <Trash2 className="mr-1 h-3.5 w-3.5" />}
            删除
          </Button>
        </div>
      </div>

      {/* 设备：仅实例 running 时展示 */}
      <div className="border-t border-[var(--border)] pt-4">
        <div className="mb-3 flex items-center justify-between">
          <span className="text-sm font-medium text-[var(--text-primary)]">设备配对</span>
          {hasPending && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => approveAllMutation.mutate()}
              disabled={approveAllMutation.isPending}
            >
              {approveAllMutation.isPending ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : <CheckCheck className="mr-1 h-3.5 w-3.5" />}
              全部批准
            </Button>
          )}
        </div>
        {!instanceRunning ? (
          <p className="py-4 text-xs text-[var(--text-tertiary)]">请先启动实例后再管理设备。</p>
        ) : devicesLoading ? (
          <div className="flex items-center py-6 text-sm text-[var(--text-secondary)]">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            加载设备…
          </div>
        ) : pending.length === 0 && paired.length === 0 ? (
          <div className="flex flex-col items-center py-6">
            <Smartphone className="mb-2 h-5 w-5 text-[var(--text-tertiary)]" />
            <p className="text-xs text-[var(--text-tertiary)]">暂无配对设备</p>
          </div>
        ) : (
          <ul className="divide-y divide-[var(--border)]">
            {pending.map((d) => (
              <li key={d.deviceId} className="flex items-center justify-between py-2.5">
                <div className="flex items-center gap-2">
                  <Smartphone className="h-4 w-4 text-[var(--text-secondary)]" />
                  <span className="text-sm text-[var(--text-primary)]">{d.clientId || d.deviceId}</span>
                  {d.platform && <span className="text-[10px] text-[var(--text-tertiary)]">{d.platform}</span>}
                </div>
                <Badge variant="outline" className="text-[10px]">待批准</Badge>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 px-2 text-xs"
                  onClick={() => approveMutation.mutate(d.deviceId)}
                  disabled={approveMutation.isPending}
                >
                  <Check className="mr-0.5 h-3 w-3" /> 批准
                </Button>
              </li>
            ))}
            {paired.map((d) => (
              <li key={d.deviceId} className="flex items-center justify-between py-2.5">
                <div className="flex items-center gap-2">
                  <Smartphone className="h-4 w-4 text-[var(--text-secondary)]" />
                  <span className="text-sm text-[var(--text-primary)]">{d.clientId || d.deviceId}</span>
                  {d.platform && <span className="text-[10px] text-[var(--text-tertiary)]">{d.platform}</span>}
                </div>
                <Badge variant="outline" className="text-[10px] text-green-600">已配对</Badge>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
