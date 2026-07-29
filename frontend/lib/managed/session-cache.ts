import type { QueryClient } from '@tanstack/react-query'

import { stripIdPrefix } from '@/lib/managed/id'
import type { Session } from '@/types/managed'

type SessionListCache = {
  data?: unknown
}

function sessionIdMatches(candidateId: string, id: string) {
  return candidateId === id || stripIdPrefix(candidateId) === stripIdPrefix(id)
}

function sessionsFromCacheValue(value: unknown): Session[] {
  if (Array.isArray(value)) return value as Session[]
  if (!value || typeof value !== 'object') return []
  const data = (value as SessionListCache).data
  return Array.isArray(data) ? data as Session[] : []
}

export function primeSessionDetailCache(queryClient: QueryClient, session: Session) {
  queryClient.setQueryData(['session', session.id], session)
  const strippedId = stripIdPrefix(session.id)
  if (strippedId !== session.id) {
    queryClient.setQueryData(['session', strippedId], session)
  }
}

export function findCachedSessionForDetail(queryClient: QueryClient, id: string) {
  const direct = queryClient.getQueryData<Session>(['session', id])
  if (direct) return direct

  const strippedId = stripIdPrefix(id)
  const stripped = strippedId !== id ? queryClient.getQueryData<Session>(['session', strippedId]) : null
  if (stripped) return stripped

  const sessionLists = queryClient.getQueriesData<unknown>({ queryKey: ['sessions'] })
  for (const [, value] of sessionLists) {
    const match = sessionsFromCacheValue(value).find((session) => sessionIdMatches(session.id, id))
    if (match) return match
  }

  return undefined
}
