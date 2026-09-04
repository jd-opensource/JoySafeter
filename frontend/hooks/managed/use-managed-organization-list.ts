'use client'

import { useCallback } from 'react'

import { usePaginatedList } from '@/hooks/managed/use-paginated-list'
import {
  fetchManagedOrganizations,
  MANAGED_ORGANIZATIONS_QUERY_ROOT,
  MANAGED_ORGANIZATIONS_SOURCE_KEY,
} from '@/lib/managed/organization-client'
import { parseOrganizationId, type OrganizationId } from '@/types/entity-id'
import type { OrgInfo } from '@/stores/managed/project-store'

export function useManagedOrganizationList(search: string) {
  const normalizedSearch = search.trim()
  const fetchPage = useCallback(
    (
      request: { limit: number; afterId?: OrganizationId },
      scope: Parameters<typeof fetchManagedOrganizations>[1],
    ) => fetchManagedOrganizations({ ...request, search: normalizedSearch }, scope),
    [normalizedSearch],
  )
  return usePaginatedList<OrgInfo, OrganizationId>({
    queryKey: MANAGED_ORGANIZATIONS_QUERY_ROOT,
    sourceKey: MANAGED_ORGANIZATIONS_SOURCE_KEY,
    cacheVersion: normalizedSearch,
    parseCursor: parseOrganizationId,
    fetchPage,
  })
}
