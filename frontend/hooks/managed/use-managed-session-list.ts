'use client'

import { usePaginatedList } from '@/hooks/managed/use-paginated-list'
import {
  fetchManagedSessions,
  MANAGED_SESSIONS_QUERY_ROOT,
  MANAGED_SESSIONS_SOURCE_KEY,
} from '@/lib/managed/session-client'
import { parseSessionId, type SessionId } from '@/types/entity-id'
import type { Session } from '@/types/managed'

export function useManagedSessionList(includeArchived: boolean) {
  return usePaginatedList<Session, SessionId>({
    queryKey: MANAGED_SESSIONS_QUERY_ROOT,
    sourceKey: MANAGED_SESSIONS_SOURCE_KEY,
    includeArchived,
    parseCursor: parseSessionId,
    fetchPage: fetchManagedSessions,
  })
}
