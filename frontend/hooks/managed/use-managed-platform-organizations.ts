'use client'

import { useQuery } from '@tanstack/react-query'

import {
  fetchManagedPlatformOrganizations,
  managedPlatformOrganizationsQueryKey,
} from '@/lib/managed/organization-client'
import { hasManagedRequestScope, useManagedRequestScope } from '@/lib/managed/request-scope'

export function useManagedPlatformOrganizations(enabled: boolean) {
  const managedScope = useManagedRequestScope()
  return useQuery({
    queryKey: managedPlatformOrganizationsQueryKey(),
    queryFn: () => fetchManagedPlatformOrganizations(managedScope),
    enabled: enabled && hasManagedRequestScope(managedScope),
  })
}
