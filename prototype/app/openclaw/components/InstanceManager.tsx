'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Activity, Loader2, Play, Power, RefreshCw, Server, Trash2 } from 'lucide-react'
import { useCallback } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
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
  createdAt?: string | null
}

const statusStyles: Record<string, string> = {
  running: 'bg-green-500/15 text-green-700 border-green-200',
  starting: 'bg-blue-500/15 text-blue-700 border-blue-200',
  pending: 'bg-gray-500/15 text-gray-600 border-gray-200',
  stopped: 'bg-gray-500/15 text-gray-600 border-gray-200',
  failed: 'bg-red-500/15 text-red-700 border-red-200',
}

export function InstanceManager() {
  const queryClient = useQueryClient()

  const { data: instance, isLoading } = useQuery<InstanceStatus>({
    queryKey: ['openclaw-instance'],
    queryFn: () => apiGet<InstanceStatus>('openclaw/instances'),
    refetchInterval: 8_000,
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
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['openclaw-instance'] }),
  })

  const deleteMutation = useMutation({
    mutationFn: () => apiDelete('openclaw/instances'),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['openclaw-instance'] }),
  })

  const isAnyLoading =
    startMutation.isPending || stopMutation.isPending || restartMutation.isPending || deleteMutation.isPending

  if (isLoading) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-12">
          <Loader2 className="mr-2 h-5 w-5 animate-spin text-[var(--text-secondary)]" />
          <span className="text-sm text-[var(--text-secondary)]">加载实例状态...</span>
        </CardContent>
      </Card>
    )
  }

  if (!instance?.exists) {
    return (
      <Card>
        <CardHeader className="p-4 pb-2">
          <CardTitle className="text-sm font-medium">我的 OpenClaw 实例</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col items-center justify-center py-12">
          <Server className="mb-3 h-8 w-8 text-[var(--text-tertiary)]" />
          <p className="mb-4 text-sm text-[var(--text-secondary)]">
            你还没有 OpenClaw 实例，点击下方按钮启动。
          </p>
          <Button onClick={() => startMutation.mutate()} disabled={isAnyLoading}>
            {startMutation.isPending ? (
              <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
            ) : (
              <Play className="mr-1.5 h-4 w-4" />
            )}
            启动实例
          </Button>
        </CardContent>
      </Card>
    )
  }

  const status = instance.status ?? 'unknown'

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between p-4 pb-2">
        <CardTitle className="text-sm font-medium">我的 OpenClaw 实例</CardTitle>
        <Badge className={cn('text-[10px]', statusStyles[status] ?? statusStyles.failed)}>
          {status}
        </Badge>
      </CardHeader>
      <CardContent className="p-4 pt-2">
        <div className="space-y-2 text-xs text-[var(--text-secondary)]">
          <div className="flex items-center gap-2">
            <Activity className="h-3.5 w-3.5" />
            <span>
              端口: {instance.gatewayPort} &nbsp;|&nbsp; 容器: {instance.containerId ?? '-'}
            </span>
          </div>
          {instance.alive !== undefined && (
            <div className="flex items-center gap-2">
              <span className={cn('inline-block h-2 w-2 rounded-full', instance.alive ? 'bg-green-500' : 'bg-red-500')} />
              <span>Gateway {instance.alive ? '在线' : '离线'}</span>
            </div>
          )}
          {instance.lastActiveAt && (
            <div className="text-[10px] opacity-60">
              最后活跃: {new Date(instance.lastActiveAt).toLocaleString()}
            </div>
          )}
          {instance.errorMessage && (
            <div className="text-red-600 text-xs">{instance.errorMessage}</div>
          )}
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          {status !== 'running' && status !== 'starting' && (
            <Button size="sm" onClick={() => startMutation.mutate()} disabled={isAnyLoading}>
              {startMutation.isPending ? (
                <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
              ) : (
                <Play className="mr-1 h-3.5 w-3.5" />
              )}
              启动
            </Button>
          )}
          {status === 'running' && (
            <Button size="sm" variant="outline" onClick={() => stopMutation.mutate()} disabled={isAnyLoading}>
              {stopMutation.isPending ? (
                <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
              ) : (
                <Power className="mr-1 h-3.5 w-3.5" />
              )}
              停止
            </Button>
          )}
          <Button size="sm" variant="outline" onClick={() => restartMutation.mutate()} disabled={isAnyLoading}>
            {restartMutation.isPending ? (
              <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
            ) : (
              <RefreshCw className="mr-1 h-3.5 w-3.5" />
            )}
            重启
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="text-red-600 hover:text-red-700"
            onClick={() => deleteMutation.mutate()}
            disabled={isAnyLoading}
          >
            {deleteMutation.isPending ? (
              <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
            ) : (
              <Trash2 className="mr-1 h-3.5 w-3.5" />
            )}
            删除
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
