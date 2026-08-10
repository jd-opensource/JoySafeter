import type { SessionEvent } from '@/types/managed'

const STATUS_EVENT_TYPES = new Set([
  'session.status_idle',
  'session.status_rescheduled',
  'session.status_running',
  'session.status_terminated',
  'session.thread_status_idle',
  'session.thread_status_running',
  'session.thread_status_terminated',
])

export function normalizeSessionEventId(id: string) {
  return id.replace(/^evt_/, '')
}

export function getEventType(event: SessionEvent) {
  return event.type || event.event_type || ''
}

export function compareSessionEvents(a: SessionEvent, b: SessionEvent) {
  const seqA = a.seq ?? Number.MAX_SAFE_INTEGER
  const seqB = b.seq ?? Number.MAX_SAFE_INTEGER
  if (seqA !== seqB) return seqA - seqB

  const timeA = a.created_at ? new Date(a.created_at).getTime() : 0
  const timeB = b.created_at ? new Date(b.created_at).getTime() : 0
  if (timeA !== timeB) return timeA - timeB

  return normalizeSessionEventId(a.id || '').localeCompare(normalizeSessionEventId(b.id || ''))
}

export function sortSessionEvents(events: SessionEvent[]) {
  return [...events].sort(compareSessionEvents)
}

export function getMaxSeq(events: SessionEvent[]) {
  return events.reduce((maxSeq, event) => Math.max(maxSeq, event.seq ?? 0), 0)
}

export function getMinSeq(events: SessionEvent[]) {
  let minSeq = Number.MAX_SAFE_INTEGER
  for (const event of events) {
    if (event.seq != null && event.seq < minSeq) minSeq = event.seq
  }
  return minSeq === Number.MAX_SAFE_INTEGER ? 0 : minSeq
}

export function getEventIdentity(event: SessionEvent) {
  const eventType = getEventType(event)
  if (event.seq != null) return `seq:${event.seq}:${eventType}`
  if (event.id) return `id:${normalizeSessionEventId(event.id)}:${eventType}`
  return `payload:${eventType}:${JSON.stringify(
    event.usage ?? event.content ?? event.stop_reason ?? event.tool ?? '',
  )}`
}

function preferSessionEvent(existing: SessionEvent, incoming: SessionEvent) {
  if (existing.seq == null && incoming.seq != null) return incoming
  if (!existing.created_at && incoming.created_at) return incoming
  if (existing.id?.startsWith('evt_') && incoming.id && !incoming.id.startsWith('evt_')) {
    return incoming
  }
  return existing
}

export function mergeSessionEvents(persistedEvents: SessionEvent[], streamEvents: SessionEvent[]) {
  if (streamEvents.length === 0) return sortSessionEvents(persistedEvents)

  const byIdentity = new Map<string, SessionEvent>()
  for (const event of persistedEvents) {
    byIdentity.set(getEventIdentity(event), event)
  }

  for (const event of streamEvents) {
    const identity = getEventIdentity(event)
    const existing = byIdentity.get(identity)
    byIdentity.set(identity, existing ? preferSessionEvent(existing, event) : event)
  }

  return sortSessionEvents(Array.from(byIdentity.values()))
}

function getStopReasonKey(event: SessionEvent) {
  return JSON.stringify(event.stop_reason ?? '')
}

export function collapseRepeatedStatusEvents(events: SessionEvent[]) {
  const collapsed: SessionEvent[] = []

  for (const event of events) {
    const eventType = getEventType(event)
    const previous = collapsed[collapsed.length - 1]
    const previousType = previous ? getEventType(previous) : ''

    if (
      previous &&
      STATUS_EVENT_TYPES.has(eventType) &&
      previousType === eventType &&
      getStopReasonKey(previous) === getStopReasonKey(event)
    ) {
      const count = typeof previous._collapsedCount === 'number' ? previous._collapsedCount : 1
      collapsed[collapsed.length - 1] = {
        ...previous,
        id: event.id || previous.id,
        seq: event.seq ?? previous.seq,
        created_at: event.created_at || previous.created_at,
        _collapsedCount: count + 1,
      } as SessionEvent
      continue
    }

    collapsed.push(event)
  }

  return collapsed
}

export function isRequiresActionIdle(event: SessionEvent) {
  return (
    getEventType(event) === 'session.status_idle' &&
    typeof event.stop_reason === 'object' &&
    event.stop_reason !== null &&
    (event.stop_reason as { type?: string }).type === 'requires_action'
  )
}

export function getLatestSessionStatusEvent(events: SessionEvent[]) {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index]
    const eventType = getEventType(event)
    if (eventType.startsWith('session.status_')) return event
  }

  return null
}
