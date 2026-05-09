'use client'

import { Button } from '@/components/ui/button'
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
          <Button
            key={t.id}
            type="button"
            variant={isActive ? 'default' : 'outline'}
            size="sm"
            onClick={() => onSelect(t.id)}
            // Chip is smaller than the default `sm` — override height + padding.
            className={cn('h-6 shrink-0 px-2 text-xs', !isActive && 'text-muted-foreground')}
            title={new Date(t.createdAt).toLocaleString()}
          >
            {isLastAndLive && (
              <span className="relative flex h-1.5 w-1.5">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary-foreground/70" />
                <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-primary-foreground" />
              </span>
            )}
            Turn {i + 1}
          </Button>
        )
      })}
    </div>
  )
}
