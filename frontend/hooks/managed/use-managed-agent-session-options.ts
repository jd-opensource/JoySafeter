'use client'

import { useQuery } from '@tanstack/react-query'

import {
  fetchManagedAgentSessionOptions,
  managedAgentSessionOptionsQueryKey,
} from '@/lib/managed/session-client'
import { hasManagedRequestScope, useManagedRequestScope } from '@/lib/managed/request-scope'
import type { AgentId } from '@/types/entity-id'

interface UseManagedAgentSessionOptionsOptions {
  enabled?: boolean
}

export function useManagedAgentSessionOptions(
  agentId: AgentId | null,
  { enabled = true }: UseManagedAgentSessionOptionsOptions = {},
) {
  const managedScope = useManagedRequestScope()
  return useQuery({
    queryKey: managedAgentSessionOptionsQueryKey(managedScope.key, agentId),
    queryFn: () => fetchManagedAgentSessionOptions(agentId!, managedScope),
    enabled: enabled && agentId !== null && hasManagedRequestScope(managedScope),
  })
}
