'use client'

import type { SessionEvent } from "@/types/managed"
import { useTranslation } from '@/lib/i18n'
import { EventRow } from "./event-row"

interface EventListProps {
  events: SessionEvent[]
  sessionStart: string
  selectedId: string | null
  onSelect: (event: SessionEvent) => void
  mode: "transcript" | "debug"
}

export function EventList({ events, sessionStart, selectedId, onSelect, mode }: EventListProps) {
  const { t } = useTranslation()

  if (events.length === 0) {
    return (
      <div className="p-8 text-center text-muted-foreground text-sm">
        {t('managed.sessions.noEventsYet')}
      </div>
    )
  }

  return (
    <div className="divide-y divide-border">
      {events.map((event) => (
        <EventRow
          key={event.id || event.seq}
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
