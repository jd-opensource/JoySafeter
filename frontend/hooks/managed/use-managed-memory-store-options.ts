'use client'

import { useQuery } from '@tanstack/react-query'

import {
  fetchManagedMemoryStoreOptions,
  managedMemoryStoreOptionsQueryKey,
} from '@/lib/managed/memory-store-client'
import { hasManagedRequestScope, useManagedRequestScope } from '@/lib/managed/request-scope'

interface UseManagedMemoryStoreOptionsOptions {
  enabled?: boolean
}

export function useManagedMemoryStoreOptions({
  enabled = true,
}: UseManagedMemoryStoreOptionsOptions = {}) {
  const managedScope = useManagedRequestScope()
  return useQuery({
    queryKey: managedMemoryStoreOptionsQueryKey(managedScope.key),
    queryFn: () => fetchManagedMemoryStoreOptions(managedScope),
    enabled: enabled && hasManagedRequestScope(managedScope),
  })
}
