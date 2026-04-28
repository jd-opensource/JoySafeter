'use client'

import { useState } from 'react'
import { Play, Square } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'

interface DebugToolbarProps {
  agentId: string
  agentVersionId: string
  workspaceId: string
  isExecuting: boolean
  onStartDebug: (prompt: string, variables?: Record<string, string>) => void
  onStop: () => void
  onSelectTrace: (traceId: string) => void
  traces: Array<{ id: string; createdAt: string }>
}

export function DebugToolbar({
  agentId,
  agentVersionId,
  workspaceId,
  isExecuting,
  onStartDebug,
  onStop,
  onSelectTrace,
  traces,
}: DebugToolbarProps) {
  const [prompt, setPrompt] = useState('')
  const [showPrompt, setShowPrompt] = useState(true)

  const handleStart = () => {
    if (!prompt.trim()) return
    onStartDebug(prompt.trim())
  }

  return (
    <div className="space-y-2 border-b px-3 py-2">
      <div className="flex items-center gap-2">
        {isExecuting ? (
          <Button size="sm" variant="destructive" onClick={onStop}>
            <Square className="mr-1 h-3 w-3" />
            Stop
          </Button>
        ) : (
          <Button size="sm" onClick={handleStart} disabled={!prompt.trim()}>
            <Play className="mr-1 h-3 w-3" />
            Debug
          </Button>
        )}

        {traces.length > 0 && (
          <select
            className="h-8 rounded-sm border bg-transparent px-2 text-xs"
            onChange={(e) => e.target.value && onSelectTrace(e.target.value)}
            defaultValue=""
          >
            <option value="" disabled>
              History...
            </option>
            {traces.map((t) => (
              <option key={t.id} value={t.id}>
                {new Date(t.createdAt).toLocaleString()}
              </option>
            ))}
          </select>
        )}
      </div>

      {showPrompt && (
        <Textarea
          placeholder="Enter test prompt..."
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={2}
          className="resize-none text-sm"
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
              e.preventDefault()
              handleStart()
            }
          }}
        />
      )}
    </div>
  )
}
