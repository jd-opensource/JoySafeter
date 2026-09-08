'use client'

import { useQuery } from '@tanstack/react-query'

import { fetchManagedFileOptions, managedFileOptionsQueryKey } from '@/lib/managed/file-client'
import { hasManagedRequestScope, useManagedRequestScope } from '@/lib/managed/request-scope'

interface UseManagedFileOptionsOptions {
  enabled?: boolean
}

export function useManagedFileOptions({ enabled = true }: UseManagedFileOptionsOptions = {}) {
  const managedScope = useManagedRequestScope()
  return useQuery({
    queryKey: managedFileOptionsQueryKey(managedScope.key),
    queryFn: () => fetchManagedFileOptions(managedScope),
    enabled: enabled && hasManagedRequestScope(managedScope),
  })
}
