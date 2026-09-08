'use client'

import { useCallback } from 'react'

import { usePaginatedList } from '@/hooks/managed/use-paginated-list'
import {
  fetchManagedOrganizationMembers,
  MANAGED_ORGANIZATION_MEMBERS_QUERY_ROOT,
  MANAGED_ORGANIZATION_MEMBERS_SOURCE_KEY,
} from '@/lib/managed/organization-client'
import {
  parseOrganizationMemberId,
  type OrganizationId,
  type OrganizationMemberId,
} from '@/types/entity-id'
import type { OrganizationMemberRecord } from '@/lib/managed/tenant-response-parsers'

export function useManagedOrganizationMemberList(organizationId: OrganizationId, search: string) {
  const normalizedSearch = search.trim()
  const fetchPage = useCallback(
    (request: Parameters<typeof fetchManagedOrganizationMembers>[0]) =>
      fetchManagedOrganizationMembers({ ...request, search: normalizedSearch }, organizationId),
    [normalizedSearch, organizationId],
  )
  return usePaginatedList<OrganizationMemberRecord, OrganizationMemberId>({
    queryKey: MANAGED_ORGANIZATION_MEMBERS_QUERY_ROOT,
    sourceKey: MANAGED_ORGANIZATION_MEMBERS_SOURCE_KEY,
    paginationScopeKey: organizationId,
    requiresManagedScope: false,
    cacheVersion: normalizedSearch,
    parseCursor: parseOrganizationMemberId,
    fetchPage,
  })
}
