'use client'

import { useQuery } from '@tanstack/react-query'

import {
  fetchManagedStorageMountCatalog,
  managedStorageMountCatalogQueryKey,
} from '@/lib/managed/storage-volume-client'
import { hasManagedRequestScope, useManagedRequestScope } from '@/lib/managed/request-scope'

export function useManagedStorageMountCatalog() {
  const managedScope = useManagedRequestScope()
  return useQuery({
    queryKey: managedStorageMountCatalogQueryKey(managedScope.key),
    queryFn: () => fetchManagedStorageMountCatalog(managedScope),
    enabled: hasManagedRequestScope(managedScope),
    staleTime: 60_000,
  })
}
