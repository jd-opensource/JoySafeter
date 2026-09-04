'use client'

import { useQuery } from '@tanstack/react-query'

import {
  fetchManagedOrganization,
  managedOrganizationQueryKey,
} from '@/lib/managed/organization-client'
import type { OrganizationId } from '@/types/entity-id'

export function useManagedOrganization(organizationId: OrganizationId | null) {
  return useQuery({
    queryKey: managedOrganizationQueryKey(organizationId),
    queryFn: () => fetchManagedOrganization(organizationId!),
    enabled: organizationId !== null,
  })
}
