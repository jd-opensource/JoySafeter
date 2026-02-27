'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, Circle, Loader2, Trash2, XCircle } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { apiDelete, apiGet } from '@/lib/api-client'
import { cn } from '@/lib/core/utils/cn'

interface Task {
  id: string
  title: string
  status: string
  instanceId: string | null
  startedAt: string | null
  completedAt: string | null
  createdAt: string
}

const statusConfig: Record<string, { icon: typeof Circle; color: string }> = {
  pending: { icon: Circle, color: 'text-gray-400' },
  running: { icon: Loader2, color: 'text-blue-500' },
  completed: { icon: CheckCircle2, color: 'text-green-500' },
  failed: { icon: XCircle, color: 'text-red-500' },
  cancelled: { icon: XCircle, color: 'text-gray-500' },
}

interface Props {
  refreshKey: number
  selectedTaskId: string | null
  onSelectTask: (id: string | null) => void
}

export function TaskList({ refreshKey, selectedTaskId, onSelectTask }: Props) {
  const { data, isLoading } = useQuery<Task[]>({
    queryKey: ['openclaw-tasks', refreshKey],
    queryFn: () => apiGet<Task[]>('openclaw/tasks'),
    refetchInterval: 5_000,
  })

  const queryClient = useQueryClient()
  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiDelete(`openclaw/tasks/${id}`),
    onSuccess: (_, deletedId) => {
      queryClient.invalidateQueries({ queryKey: ['openclaw-tasks', refreshKey] })
      if (selectedTaskId === deletedId) {
        onSelectTask(null)
      }
    },
  })

  const tasks = data ?? []

  return (
    <Card className="flex flex-1 flex-col overflow-hidden">
      <CardHeader className="p-4 pb-2">
        <CardTitle className="text-sm font-medium">Task History</CardTitle>
      </CardHeader>
      <CardContent className="flex-1 overflow-auto p-0">
        {isLoading ? (
          <div className="flex items-center justify-center py-12 text-sm text-[var(--text-secondary)]">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            Loading...
          </div>
        ) : tasks.length === 0 ? (
          <div className="py-12 text-center text-sm text-[var(--text-tertiary)]">
            No tasks yet. Submit one above.
          </div>
        ) : (
          <ul className="divide-y divide-[var(--border)]">
            {tasks.map((t) => {
              const cfg = statusConfig[t.status] ?? statusConfig.pending
              const Icon = cfg.icon
              return (
                <li
                  key={t.id}
                  onClick={() => onSelectTask(t.id)}
                  className={cn(
                    'flex cursor-pointer items-center gap-3 px-4 py-3 transition-colors hover:bg-[var(--surface-3)]',
                    selectedTaskId === t.id && 'bg-[var(--surface-5)]',
                  )}
                >
                  <Icon
                    className={cn(
                      'h-4 w-4 flex-shrink-0',
                      cfg.color,
                      t.status === 'running' && 'animate-spin',
                    )}
                  />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-[var(--text-primary)]">
                      {t.title}
                    </p>
                    <p className="text-[10px] text-[var(--text-tertiary)]">
                      {new Date(t.createdAt).toLocaleString()}
                    </p>
                  </div>
                  <Badge
                    variant="outline"
                    className="text-[10px]"
                  >
                    {t.status}
                  </Badge>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6 text-[var(--text-tertiary)] hover:bg-red-500/10 hover:text-red-600"
                    onClick={(e) => {
                      e.stopPropagation()
                      deleteMutation.mutate(t.id)
                    }}
                    disabled={deleteMutation.isPending && deleteMutation.variables === t.id}
                  >
                    {deleteMutation.isPending && deleteMutation.variables === t.id ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : (
                      <Trash2 className="h-3 w-3" />
                    )}
                  </Button>
                </li>
              )
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}
