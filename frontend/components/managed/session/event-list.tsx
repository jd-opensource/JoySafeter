'use client'

import type { SessionEvent } from '@/types/managed'
import { useTranslation } from '@/lib/i18n'
import { EventRow } from './event-row'

interface EventListProps {
  events: SessionEvent[]
  sessionStart: string
  selectedId: string | null
  onSelect: (event: SessionEvent) => void
  mode: 'transcript' | 'debug'
}

function getEventKey(event: SessionEvent, index: number): string {
  const type = event.type || event.event_type || 'event'
  const stablePart =
    event.id ||
    (event.seq != null ? `seq_${event.seq}` : '') ||
    event.created_at ||
    JSON.stringify(event.content ?? event.usage ?? event.stop_reason ?? event.tool ?? '')

  return `${stablePart || type}:${type}:${index}`
}

export function EventList({ events, sessionStart, selectedId, onSelect, mode }: EventListProps) {
  const { t } = useTranslation()

  if (events.length === 0) {
    return (
      <div className="p-8 text-center text-sm text-muted-foreground">
        {t('managed.sessions.noEventsYet')}
      </div>
    )
  }

  return (
    <div className="divide-y divide-border">
      {events.map((event, index) => (
        <EventRow
          key={getEventKey(event, index)}
          event={event}
          sessionStart={sessionStart}
          selected={event.id === selectedId}
          onClick={() => onSelect(event)}
          mode={mode}
        />
      ))}
    </div>
  )
}
