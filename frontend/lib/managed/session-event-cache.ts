import { getMaxSeq, mergeSessionEvents, sortSessionEvents } from '@/lib/managed/session-events'
import type { SessionEvent } from '@/types/managed'

const MAX_CACHED_SESSIONS = 20
const MAX_CACHED_EVENTS_PER_SESSION = 10000

export interface CachedSessionEventState {
  events: SessionEvent[]
  hasMoreOlder: boolean
  minSeq: number
  maxSeq: number
  updatedAt: number
}

const cache = new Map<string, CachedSessionEventState>()

function getMinSeq(events: SessionEvent[]) {
  let minSeq = Number.MAX_SAFE_INTEGER
  for (const event of events) {
    if (event.seq != null && event.seq < minSeq) minSeq = event.seq
  }
  return minSeq === Number.MAX_SAFE_INTEGER ? 0 : minSeq
}

function trimEvents(events: SessionEvent[]) {
  const sorted = sortSessionEvents(events)
  if (sorted.length <= MAX_CACHED_EVENTS_PER_SESSION) return sorted
  return sorted.slice(sorted.length - MAX_CACHED_EVENTS_PER_SESSION)
}

function evictOldSessions() {
  if (cache.size <= MAX_CACHED_SESSIONS) return
  const entries = Array.from(cache.entries()).sort((a, b) => a[1].updatedAt - b[1].updatedAt)
  for (const [key] of entries.slice(0, cache.size - MAX_CACHED_SESSIONS)) {
    cache.delete(key)
  }
}

export function getCachedSessionEventState(key: string): CachedSessionEventState | null {
  const state = cache.get(key)
  if (!state) return null
  const next = { ...state, events: [...state.events], updatedAt: Date.now() }
  cache.set(key, next)
  return next
}

export function setCachedSessionEventState(
  key: string,
  events: SessionEvent[],
  hasMoreOlder: boolean,
) {
  const normalized = trimEvents(events)
  const state: CachedSessionEventState = {
    events: normalized,
    hasMoreOlder,
    minSeq: getMinSeq(normalized),
    maxSeq: getMaxSeq(normalized),
    updatedAt: Date.now(),
  }
  cache.set(key, state)
  evictOldSessions()
  return { ...state, events: [...state.events] }
}

export function mergeCachedSessionEvents(
  key: string,
  events: SessionEvent[],
  hasMoreOlder?: boolean,
) {
  const existing = cache.get(key)
  return setCachedSessionEventState(
    key,
    mergeSessionEvents(existing?.events ?? [], events),
    hasMoreOlder ?? existing?.hasMoreOlder ?? true,
  )
}

export function clearCachedSessionEventState(key: string) {
  cache.delete(key)
}
