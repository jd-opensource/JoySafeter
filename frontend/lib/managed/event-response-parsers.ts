import { parseEventId } from '@/types/entity-id'
import type { SessionEvent } from '@/types/managed'

type RawSessionEvent = Omit<SessionEvent, 'id'> & { id?: string | null }

export function parseSessionEventResponse(response: unknown): SessionEvent {
  const raw = response as RawSessionEvent
  return {
    ...raw,
    id: raw.id ? parseEventId(raw.id) : undefined,
  }
}

export function parseSessionEventListResponse(response: unknown): SessionEvent[] {
  return (response as RawSessionEvent[]).map(parseSessionEventResponse)
}
