'use client'

import { cn } from '@/lib/utils'

export interface TurnTimelineItem {
  id: string
  createdAt: string
}

interface TurnTimelineProps {
  /** Ordered list of traces for the current thread (ASC by created_at). */
  turns: TurnTimelineItem[]
  /** Currently selected trace id (live or replay). */
  activeTraceId: string | null
  /** True when the last turn is still streaming — shown with a live pulse. */
  isLive: boolean
  onSelect: (traceId: string) => void
}

/**
 * Horizontal strip of turns in the current Thread/session. Each chip is one
 * Trace — clicking switches the observation panel to replay mode for that
 * turn. When live, the last chip pulses and is the auto-selected active turn.
 */
export function TurnTimeline({ turns, activeTraceId, isLive, onSelect }: TurnTimelineProps) {
  if (turns.length === 0) return null

  return (
    <div className="flex items-center gap-1 overflow-x-auto border-b px-3 py-1.5">
      <span className="shrink-0 text-xs text-muted-foreground">Turns:</span>
      {turns.map((t, i) => {
        const isActive = t.id === activeTraceId
        const isLastAndLive = isLive && i === turns.length - 1
        return (
          <button
            key={t.id}
            type="button"
            onClick={() => onSelect(t.id)}
            className={cn(
              'shrink-0 rounded-sm border px-2 py-0.5 text-xs transition-colors',
              isActive
                ? 'border-primary bg-primary/10 text-primary'
                : 'border-border text-muted-foreground hover:bg-muted',
            )}
            title={new Date(t.createdAt).toLocaleString()}
          >
            <span className="inline-flex items-center gap-1">
              {isLastAndLive && (
                <span className="relative flex h-1.5 w-1.5">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary/70" />
                  <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-primary" />
                </span>
              )}
              Turn {i + 1}
            </span>
          </button>
        )
      })}
    </div>
  )
}
