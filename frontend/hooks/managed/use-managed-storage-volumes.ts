'use client'

import { useQuery } from '@tanstack/react-query'

import {
  fetchManagedStorageVolumes,
  managedStorageVolumesQueryKey,
  type ManagedStorageVolumeView,
} from '@/lib/managed/storage-volume-client'
import { hasManagedRequestScope, useManagedRequestScope } from '@/lib/managed/request-scope'

export function useManagedStorageVolumes(view: ManagedStorageVolumeView) {
  const managedScope = useManagedRequestScope()
  return useQuery({
    queryKey: managedStorageVolumesQueryKey(managedScope.key, view),
    queryFn: () => fetchManagedStorageVolumes(view, managedScope),
    enabled: hasManagedRequestScope(managedScope),
  })
}
