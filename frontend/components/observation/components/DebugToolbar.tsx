'use client'

import { useState } from 'react'
import { Play, Square, RotateCcw } from 'lucide-react'
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
  /** Number of turns in the current session (0 = no session started) */
  turnCount?: number
  /** Reset the session to start fresh */
  onNewSession?: () => void
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
  turnCount = 0,
  onNewSession,
}: DebugToolbarProps) {
  const [prompt, setPrompt] = useState('')
  const [showPrompt, setShowPrompt] = useState(true)

  const handleStart = () => {
    if (!prompt.trim()) return
    onStartDebug(prompt.trim())
  }

  const isMultiTurn = turnCount > 0

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
            {isMultiTurn ? `Turn ${turnCount + 1}` : 'Debug'}
          </Button>
        )}

        {/* Session indicator + New Session button */}
        {isMultiTurn && (
          <>
            <span className="text-xs text-muted-foreground">
              Session: {turnCount} turn{turnCount > 1 ? 's' : ''}
            </span>
            {onNewSession && (
              <Button
                size="sm"
                variant="ghost"
                onClick={onNewSession}
                disabled={isExecuting}
                className="h-7 px-2 text-xs"
                title="Start a new debug session"
              >
                <RotateCcw className="mr-1 h-3 w-3" />
                New Session
              </Button>
            )}
          </>
        )}

        {traces.length > 0 && (
          <select
            className="h-8 rounded-sm border bg-transparent px-2 text-xs"
            onChange={(e) => e.target.value && onSelectTrace(e.target.value)}
            defaultValue=""
          >
            <option value="" disabled>
              {isMultiTurn ? `Traces (${traces.length})...` : 'History...'}
            </option>
            {traces.map((t, i) => (
              <option key={t.id} value={t.id}>
                {isMultiTurn ? `Turn ${i + 1} – ` : ''}{new Date(t.createdAt).toLocaleString()}
              </option>
            ))}
          </select>
        )}
      </div>

      {showPrompt && (
        <Textarea
          placeholder={isMultiTurn ? 'Follow-up message (context preserved)...' : 'Enter test prompt...'}
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
