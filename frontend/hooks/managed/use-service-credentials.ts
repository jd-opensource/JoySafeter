'use client'

import { useQuery } from '@tanstack/react-query'

import {
  fetchManagedServiceCredentialOptions,
  serviceCredentialsQueryKey,
} from '@/lib/managed/credential-client'
import { hasManagedRequestScope, useManagedRequestScope } from '@/lib/managed/request-scope'

export function useServiceCredentials({ enabled = true }: { enabled?: boolean } = {}) {
  const scope = useManagedRequestScope()
  return useQuery({
    queryKey: serviceCredentialsQueryKey(scope.key),
    queryFn: () => fetchManagedServiceCredentialOptions(scope),
    enabled: enabled && hasManagedRequestScope(scope),
    staleTime: 30_000,
  })
}
