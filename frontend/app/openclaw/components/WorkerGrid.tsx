'use client'

import { useQuery } from '@tanstack/react-query'
import { Activity, RefreshCw, Server, Trash2 } from 'lucide-react'
import { useCallback } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { apiDelete, apiGet, apiPost } from '@/lib/api-client'
import { cn } from '@/lib/core/utils/cn'

interface Worker {
  id: string
  name: string
  endpointUrl: string
  status: string
  currentTasks: number
  maxTasks: number
  lastHeartbeatAt: string | null
  errorMessage: string | null
}

const statusColor: Record<string, string> = {
  idle: 'bg-green-500/15 text-green-700 border-green-200',
  busy: 'bg-amber-500/15 text-amber-700 border-amber-200',
  offline: 'bg-red-500/15 text-red-700 border-red-200',
}

export function WorkerGrid() {
  const { data, isLoading, refetch } = useQuery<{ success: boolean; data: Worker[] }>({
    queryKey: ['openclaw-workers'],
    queryFn: () => apiGet<{ success: boolean; data: Worker[] }>('openclaw/workers'),
    refetchInterval: 10_000,
  })

  const workers = data?.data ?? []

  const handlePing = useCallback(
    async (id: string) => {
      await apiPost(`openclaw/workers/${id}/ping`)
      refetch()
    },
    [refetch],
  )

  const handleRemove = useCallback(
    async (id: string) => {
      await apiDelete(`openclaw/workers/${id}`)
      refetch()
    },
    [refetch],
  )

  const handleHealthCheckAll = useCallback(async () => {
    await apiPost('openclaw/workers/health-check-all')
    refetch()
  }, [refetch])

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold text-[var(--text-primary)]">Worker Pool</h2>
        <Button variant="outline" size="sm" onClick={handleHealthCheckAll}>
          <RefreshCw className="mr-1 h-3.5 w-3.5" />
          Health Check All
        </Button>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-12 text-sm text-[var(--text-secondary)]">
          Loading workers...
        </div>
      ) : workers.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12">
            <Server className="mb-3 h-8 w-8 text-[var(--text-tertiary)]" />
            <p className="text-sm text-[var(--text-secondary)]">
              No workers registered. Start workers with docker-compose and they will auto-register.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {workers.map((w) => (
            <Card key={w.id} className="group relative">
              <CardHeader className="p-4 pb-2">
                <div className="flex items-start justify-between">
                  <CardTitle className="text-sm font-medium">{w.name}</CardTitle>
                  <Badge className={cn('text-[10px]', statusColor[w.status] ?? statusColor.offline)}>
                    {w.status}
                  </Badge>
                </div>
              </CardHeader>
              <CardContent className="p-4 pt-0">
                <div className="space-y-1.5 text-xs text-[var(--text-secondary)]">
                  <div className="flex items-center gap-1.5">
                    <Activity className="h-3 w-3" />
                    <span>
                      {w.currentTasks} / {w.maxTasks} tasks
                    </span>
                  </div>
                  <div className="truncate font-mono text-[10px] opacity-60">{w.endpointUrl}</div>
                  {w.errorMessage && (
                    <div className="truncate text-red-600">{w.errorMessage}</div>
                  )}
                </div>
                <div className="mt-3 flex gap-1.5 opacity-0 transition-opacity group-hover:opacity-100">
                  <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" onClick={() => handlePing(w.id)}>
                    Ping
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 px-2 text-xs text-red-600 hover:text-red-700"
                    onClick={() => handleRemove(w.id)}
                  >
                    <Trash2 className="mr-0.5 h-3 w-3" />
                    Remove
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
