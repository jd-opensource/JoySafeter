'use client'

import { useQuery } from '@tanstack/react-query'

import {
  fetchManagedCredentialGroupOptions,
  managedCredentialGroupOptionsQueryKey,
} from '@/lib/managed/credential-group-client'
import { hasManagedRequestScope, useManagedRequestScope } from '@/lib/managed/request-scope'

interface UseManagedCredentialGroupOptionsOptions {
  enabled?: boolean
  refetchOnMount?: boolean | 'always'
}

export function useManagedCredentialGroupOptions({
  enabled = true,
  refetchOnMount,
}: UseManagedCredentialGroupOptionsOptions = {}) {
  const managedScope = useManagedRequestScope()
  return useQuery({
    queryKey: managedCredentialGroupOptionsQueryKey(managedScope.key),
    queryFn: () => fetchManagedCredentialGroupOptions(managedScope),
    enabled: enabled && hasManagedRequestScope(managedScope),
    refetchOnMount,
  })
}
