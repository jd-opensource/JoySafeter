'use client'

import { useQuery } from '@tanstack/react-query'

import {
  fetchManagedMemoryDirectory,
  managedMemoryDirectoryQueryKey,
} from '@/lib/managed/memory-store-client'
import { hasManagedRequestScope, useManagedRequestScope } from '@/lib/managed/request-scope'
import type { MemoryStoreId } from '@/types/entity-id'

export function useManagedMemoryDirectory(storeId: MemoryStoreId | null) {
  const managedScope = useManagedRequestScope()
  return useQuery({
    queryKey: managedMemoryDirectoryQueryKey(managedScope.key, storeId),
    queryFn: () => fetchManagedMemoryDirectory(storeId!, managedScope),
    enabled: storeId !== null && hasManagedRequestScope(managedScope),
  })
}
