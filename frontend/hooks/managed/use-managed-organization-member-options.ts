'use client'

import { useQuery } from '@tanstack/react-query'

import {
  fetchManagedOrganizationMemberOptions,
  managedOrganizationMemberOptionsQueryKey,
} from '@/lib/managed/organization-client'
import type { OrganizationId } from '@/types/entity-id'

export function useManagedOrganizationMemberOptions(
  organizationId: OrganizationId | null,
  enabled: boolean,
) {
  return useQuery({
    queryKey: managedOrganizationMemberOptionsQueryKey(organizationId),
    queryFn: () => fetchManagedOrganizationMemberOptions(organizationId!),
    enabled: enabled && organizationId !== null,
  })
}
