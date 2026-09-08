'use client'

import { useCallback } from 'react'

import {
  usePaginatedList,
  type ManagedPaginatedListPageRequest,
} from '@/hooks/managed/use-paginated-list'
import {
  fetchManagedStorageMountAudits,
  MANAGED_STORAGE_VOLUME_AUDIT_QUERY_ROOT,
  MANAGED_STORAGE_VOLUME_AUDIT_SOURCE_KEY,
} from '@/lib/managed/storage-volume-client'
import type { ManagedRequestScope } from '@/lib/managed/request-scope'
import {
  parseStorageMountAuditId,
  type StorageMountAuditId,
  type StorageVolumeId,
} from '@/types/entity-id'
import type { StorageMountAudit } from '@/types/managed'

export function useManagedStorageMountAuditList(volumeId: StorageVolumeId | null) {
  const fetchPage = useCallback(
    (request: ManagedPaginatedListPageRequest<StorageMountAuditId>, scope: ManagedRequestScope) =>
      fetchManagedStorageMountAudits({ ...request, volumeId }, scope),
    [volumeId],
  )
  return usePaginatedList<StorageMountAudit, StorageMountAuditId>({
    queryKey: MANAGED_STORAGE_VOLUME_AUDIT_QUERY_ROOT,
    sourceKey: MANAGED_STORAGE_VOLUME_AUDIT_SOURCE_KEY,
    cacheVersion: volumeId ?? 'all-volumes',
    limit: 25,
    pageSizeOptions: [25, 50, 100],
    parseCursor: parseStorageMountAuditId,
    fetchPage,
  })
}
