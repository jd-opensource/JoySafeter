'use client'

import { usePaginatedList } from '@/hooks/managed/use-paginated-list'
import {
  fetchManagedCredentialGroups,
  MANAGED_CREDENTIAL_GROUPS_QUERY_ROOT,
  MANAGED_CREDENTIAL_GROUPS_SOURCE_KEY,
} from '@/lib/managed/credential-group-client'
import { parseCredentialGroupId, type CredentialGroupId } from '@/types/entity-id'
import type { CredentialGroup } from '@/types/managed'

interface UseManagedCredentialGroupListOptions {
  includeArchived: boolean
  pageSize: number
  onPageSizeChange: (pageSize: number) => void
}

export function useManagedCredentialGroupList({
  includeArchived,
  pageSize,
  onPageSizeChange,
}: UseManagedCredentialGroupListOptions) {
  return usePaginatedList<CredentialGroup, CredentialGroupId>({
    queryKey: MANAGED_CREDENTIAL_GROUPS_QUERY_ROOT,
    sourceKey: MANAGED_CREDENTIAL_GROUPS_SOURCE_KEY,
    includeArchived,
    pageSize,
    onPageSizeChange,
    parseCursor: parseCredentialGroupId,
    fetchPage: fetchManagedCredentialGroups,
  })
}
