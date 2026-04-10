'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Activity, Loader2, Play, Power, RefreshCw, Server, Trash2 } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { apiDelete, apiGet, apiPost } from '@/lib/api-client'
import { cn } from '@/lib/utils'

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
  running: 'bg-[var(--status-success)]/15 text-[var(--status-success)] border-[var(--status-success-border)]',
  starting: 'bg-[var(--brand-500)]/15 text-[var(--brand-700)] border-[var(--brand-200)]',
  pending: 'bg-[var(--text-tertiary)] text-[var(--text-secondary)] border-[var(--border)]',
  stopped: 'bg-[var(--text-tertiary)] text-[var(--text-secondary)] border-[var(--border)]',
  failed: 'bg-[var(--status-error)]/15 text-[var(--status-error)] border-[var(--status-error-border)]',
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
    startMutation.isPending ||
    stopMutation.isPending ||
    restartMutation.isPending ||
    deleteMutation.isPending

  if (isLoading) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-12">
          <Loader2 className="mr-2 h-5 w-5 animate-spin text-[var(--text-secondary)]" />
          <span className="text-sm text-[var(--text-secondary)]">Loading instance status...</span>
        </CardContent>
      </Card>
    )
  }

  if (!instance?.exists) {
    return (
      <Card>
        <CardHeader className="p-4 pb-2">
          <CardTitle className="text-sm font-medium">My OpenClaw Instance</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col items-center justify-center py-12">
          <Server className="mb-3 h-8 w-8 text-[var(--text-tertiary)]" />
          <p className="mb-4 text-sm text-[var(--text-secondary)]">
            You don&apos;t have an OpenClaw instance yet. Click the button below to start one.
          </p>
          <Button onClick={() => startMutation.mutate()} disabled={isAnyLoading}>
            {startMutation.isPending ? (
              <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
            ) : (
              <Play className="mr-1.5 h-4 w-4" />
            )}
            Start Instance
          </Button>
        </CardContent>
      </Card>
    )
  }

  const status = instance.status ?? 'unknown'

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between p-4 pb-2">
        <CardTitle className="text-sm font-medium">My OpenClaw Instance</CardTitle>
        <Badge className={cn('text-2xs', statusStyles[status] ?? statusStyles.failed)}>
          {status}
        </Badge>
      </CardHeader>
      <CardContent className="p-4 pt-2">
        <div className="space-y-2 text-xs text-[var(--text-secondary)]">
          <div className="flex items-center gap-2">
            <Activity className="h-3.5 w-3.5" />
            <span>
              Port: {instance.gatewayPort} &nbsp;|&nbsp; Container: {instance.containerId ?? '-'}
            </span>
          </div>
          {instance.alive !== undefined && (
            <div className="flex items-center gap-2">
              <span
                className={cn(
                  'inline-block h-2 w-2 rounded-full',
                  instance.alive ? 'bg-[var(--status-success)]' : 'bg-[var(--status-error)]',
                )}
              />
              <span>Gateway {instance.alive ? 'Online' : 'Offline'}</span>
            </div>
          )}
          {instance.lastActiveAt && (
            <div className="text-2xs opacity-60">
              Last active: {new Date(instance.lastActiveAt).toLocaleString()}
            </div>
          )}
          {instance.errorMessage && (
            <div className="text-xs text-[var(--status-error)]">{instance.errorMessage}</div>
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
              Start
            </Button>
          )}
          {status === 'running' && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => stopMutation.mutate()}
              disabled={isAnyLoading}
            >
              {stopMutation.isPending ? (
                <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
              ) : (
                <Power className="mr-1 h-3.5 w-3.5" />
              )}
              Stop
            </Button>
          )}
          <Button
            size="sm"
            variant="outline"
            onClick={() => restartMutation.mutate()}
            disabled={isAnyLoading}
          >
            {restartMutation.isPending ? (
              <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
            ) : (
              <RefreshCw className="mr-1 h-3.5 w-3.5" />
            )}
            Restart
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="text-[var(--status-error)] hover:text-[var(--status-error-hover)]"
            onClick={() => deleteMutation.mutate()}
            disabled={isAnyLoading}
          >
            {deleteMutation.isPending ? (
              <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
            ) : (
              <Trash2 className="mr-1 h-3.5 w-3.5" />
            )}
            Delete
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
