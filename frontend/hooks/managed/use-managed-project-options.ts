'use client'

import { useQuery } from '@tanstack/react-query'

import {
  fetchManagedProjectOptions,
  managedProjectOptionsQueryKey,
} from '@/lib/managed/project-client'
import { hasManagedRequestScope, useManagedRequestScope } from '@/lib/managed/request-scope'

export function useManagedProjectOptions() {
  const managedScope = useManagedRequestScope()
  return useQuery({
    queryKey: managedProjectOptionsQueryKey(managedScope.orgId),
    queryFn: () => fetchManagedProjectOptions(managedScope),
    enabled: hasManagedRequestScope(managedScope),
  })
}
