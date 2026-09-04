'use client'

import { useCallback } from 'react'

import { usePaginatedList } from '@/hooks/managed/use-paginated-list'
import {
  fetchManagedCredentials,
  managedCredentialListSourceKey,
  MANAGED_CREDENTIALS_QUERY_ROOT,
} from '@/lib/managed/credential-client'
import { parseCredentialId, type CredentialId } from '@/types/entity-id'
import type { Credential } from '@/types/managed'

interface UseManagedCredentialListOptions {
  kind: Credential['kind']
  includeArchived: boolean
  pageSize: number
  onPageSizeChange: (pageSize: number) => void
  enabled?: boolean
  cacheVersion?: string
}

export function useManagedCredentialList({
  kind,
  includeArchived,
  pageSize,
  onPageSizeChange,
  enabled,
  cacheVersion,
}: UseManagedCredentialListOptions) {
  const fetchPage = useCallback(
    (
      request: Parameters<typeof fetchManagedCredentials>[0],
      scope: Parameters<typeof fetchManagedCredentials>[1],
    ) => fetchManagedCredentials({ ...request, kind }, scope),
    [kind],
  )
  return usePaginatedList<Credential, CredentialId>({
    queryKey: MANAGED_CREDENTIALS_QUERY_ROOT,
    sourceKey: managedCredentialListSourceKey(kind),
    includeArchived,
    pageSize,
    onPageSizeChange,
    enabled,
    cacheVersion,
    parseCursor: parseCredentialId,
    fetchPage,
  })
}
