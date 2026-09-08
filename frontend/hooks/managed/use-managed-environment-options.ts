'use client'

import { useQuery } from '@tanstack/react-query'

import {
  fetchManagedEnvironmentOptions,
  managedEnvironmentOptionsQueryKey,
} from '@/lib/managed/environment-client'
import { hasManagedRequestScope, useManagedRequestScope } from '@/lib/managed/request-scope'

interface UseManagedEnvironmentOptionsOptions {
  enabled?: boolean
  refetchOnMount?: boolean | 'always'
}

export function useManagedEnvironmentOptions({
  enabled = true,
  refetchOnMount,
}: UseManagedEnvironmentOptionsOptions = {}) {
  const managedScope = useManagedRequestScope()
  return useQuery({
    queryKey: managedEnvironmentOptionsQueryKey(managedScope.key),
    queryFn: () => fetchManagedEnvironmentOptions(managedScope),
    enabled: enabled && hasManagedRequestScope(managedScope),
    refetchOnMount,
  })
}
