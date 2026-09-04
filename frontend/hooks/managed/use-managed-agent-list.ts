'use client'

import { usePaginatedList } from '@/hooks/managed/use-paginated-list'
import {
  fetchManagedAgents,
  MANAGED_AGENTS_QUERY_ROOT,
  MANAGED_AGENTS_SOURCE_KEY,
} from '@/lib/managed/agent-client'
import { parseAgentId, type AgentId } from '@/types/entity-id'
import type { Agent } from '@/types/managed'

export function useManagedAgentList(includeArchived: boolean) {
  return usePaginatedList<Agent, AgentId>({
    queryKey: MANAGED_AGENTS_QUERY_ROOT,
    sourceKey: MANAGED_AGENTS_SOURCE_KEY,
    includeArchived,
    parseCursor: parseAgentId,
    fetchPage: fetchManagedAgents,
  })
}
