'use client'

import { useQuery } from '@tanstack/react-query'

import { fetchManagedAgentOptions, managedAgentOptionsQueryKey } from '@/lib/managed/agent-client'
import { hasManagedRequestScope, useManagedRequestScope } from '@/lib/managed/request-scope'

interface UseManagedAgentOptionsOptions {
  enabled?: boolean
}

export function useManagedAgentOptions({ enabled = true }: UseManagedAgentOptionsOptions = {}) {
  const managedScope = useManagedRequestScope()
  return useQuery({
    queryKey: managedAgentOptionsQueryKey(managedScope.key),
    queryFn: () => fetchManagedAgentOptions(managedScope),
    enabled: enabled && hasManagedRequestScope(managedScope),
  })
}
