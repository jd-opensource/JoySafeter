'use client'

import { CheckCircle2, Loader2, Terminal, XCircle, Wifi, WifiOff } from 'lucide-react'
import { useEffect, useRef } from 'react'

import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { cn } from '@/lib/core/utils/cn'
import { useOpenClawTaskStream } from '@/hooks/use-openclaw-task-stream'

interface Props {
  taskId: string | null
}

export function TaskOutputViewer({ taskId }: Props) {
  const { isConnected, output, finished, error } = useOpenClawTaskStream(taskId)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = scrollRef.current
    if (el) {
      el.scrollTop = el.scrollHeight
    }
  }, [output])

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
          {error ? (
            <Badge className="gap-1 bg-red-500/15 text-red-700 border-red-200 text-[10px]">
              <XCircle className="h-3 w-3" />
              Error
            </Badge>
          ) : finished ? (
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
          {output ? (
            <pre className="whitespace-pre-wrap break-words">{output}</pre>
          ) : !finished && isConnected ? (
            <div className="flex items-center gap-2 text-gray-500">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Waiting for output...
            </div>
          ) : !finished ? (
            <span className="text-gray-500">Connecting...</span>
          ) : null}
          {error && (
            <div className="mt-2 text-red-400">
              Error: {error}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
