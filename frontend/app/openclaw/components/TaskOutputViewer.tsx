'use client'

import { useQuery } from '@tanstack/react-query'
import { CheckCircle2, Loader2, Terminal, XCircle, Wifi, WifiOff } from 'lucide-react'
import { useEffect, useRef } from 'react'

import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { apiGet } from '@/lib/api-client'
import { cn } from '@/lib/core/utils/cn'
import { useOpenClawTaskStream } from '@/hooks/use-openclaw-task-stream'

interface Props {
  taskId: string | null
}

interface Task {
  id: string
  title: string
  status: string
  output: string | null
}

export function TaskOutputViewer({ taskId }: Props) {
  const { data: task, isLoading: isLoadingTask } = useQuery<Task>({
    queryKey: ['openclaw-task', taskId],
    queryFn: () => apiGet<Task>(`openclaw/tasks/${taskId}`),
    enabled: !!taskId,
  })

  const { isConnected, output: streamOutput, finished: streamFinished, error: streamError } = useOpenClawTaskStream(taskId)
  const scrollRef = useRef<HTMLDivElement>(null)

  const isResolved = task?.status === 'completed' || task?.status === 'failed' || task?.status === 'cancelled'
  const displayOutput = streamOutput || (task?.output ?? '')
  const displayFinished = streamFinished || isResolved
  const displayError = streamError || (task?.status === 'failed' ? 'Task failed' : null)

  useEffect(() => {
    const el = scrollRef.current
    if (el) {
      el.scrollTop = el.scrollHeight
    }
  }, [displayOutput])

  if (!taskId) {
    return (
      <Card className="flex flex-col items-center justify-center">
        <CardContent className="flex flex-col items-center justify-center py-24">
          <Terminal className="mb-3 h-8 w-8 text-[var(--text-tertiary)]" />
          <p className="text-sm text-[var(--text-secondary)]">
            Select a task to view its real-time output.
          </p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card className="flex flex-col overflow-hidden">
      <CardHeader className="flex flex-row items-center justify-between p-4 pb-2">
        <CardTitle className="text-sm font-medium">Task Output</CardTitle>
        <div className="flex items-center gap-2">
          {displayError ? (
            <Badge className="gap-1 bg-red-500/15 text-red-700 border-red-200 text-[10px]">
              <XCircle className="h-3 w-3" />
              Error
            </Badge>
          ) : displayFinished ? (
            <Badge className="gap-1 bg-green-500/15 text-green-700 border-green-200 text-[10px]">
              <CheckCircle2 className="h-3 w-3" />
              Done
            </Badge>
          ) : isConnected ? (
            <Badge className="gap-1 bg-blue-500/15 text-blue-700 border-blue-200 text-[10px]">
              <Wifi className="h-3 w-3" />
              Streaming
            </Badge>
          ) : (
            <Badge className="gap-1 bg-gray-500/15 text-gray-600 border-gray-200 text-[10px]">
              <WifiOff className="h-3 w-3" />
              Disconnected
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent className="flex-1 overflow-hidden p-0">
        <div
          ref={scrollRef}
          className={cn(
            'h-full min-h-[300px] overflow-auto bg-[#1e1e1e] p-4 font-mono text-xs leading-relaxed text-green-400',
          )}
        >
          {isLoadingTask ? (
            <div className="flex items-center justify-center py-12 text-gray-500">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Loading task...
            </div>
          ) : displayOutput ? (
            <pre className="whitespace-pre-wrap break-words">{displayOutput}</pre>
          ) : !displayFinished && isConnected ? (
            <div className="flex items-center gap-2 text-gray-500">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Waiting for output...
            </div>
          ) : !displayFinished ? (
            <span className="text-gray-500">Connecting...</span>
          ) : null}
          {displayError && (
            <div className="mt-2 text-red-400">
              Error: {displayError}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
