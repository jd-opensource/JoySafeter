'use client'

import { useQuery } from '@tanstack/react-query'

import { managedGet } from '@/lib/api-client'
import { apiCollectionPath } from '@/lib/managed/api-paths'
import {
  hasManagedRequestScope,
  managedRequestOptions,
  type ManagedRequestScope,
  useManagedRequestScope,
} from '@/lib/managed/request-scope'
import { parseSecretListResponse } from '@/lib/managed/secret-response-parsers'
import type { Secret } from '@/types/managed'

interface SecretPage {
  data: unknown[]
  has_more: boolean
  last_id?: string | null
}

const PAGE_SIZE = 100

export function serviceCredentialsQueryKey(scopeKey: string) {
  return ['service-credentials', scopeKey] as const
}

export async function fetchAllServiceCredentials(scope: ManagedRequestScope): Promise<Secret[]> {
  const credentials: Secret[] = []
  let afterId: string | undefined

  for (;;) {
    const page = await managedGet<SecretPage>(
      apiCollectionPath('secrets', { limit: PAGE_SIZE, kind: 'generic', after_id: afterId }),
      managedRequestOptions(scope),
    )
    credentials.push(...parseSecretListResponse(page.data))
    if (!page.has_more) return credentials
    if (!page.last_id || page.last_id === afterId) {
      throw new Error('Service Credential pagination returned an invalid cursor')
    }
    afterId = page.last_id
  }
}

export function useServiceCredentials({ enabled = true }: { enabled?: boolean } = {}) {
  const scope = useManagedRequestScope()
  return useQuery({
    queryKey: serviceCredentialsQueryKey(scope.key),
    queryFn: () => fetchAllServiceCredentials(scope),
    enabled: enabled && hasManagedRequestScope(scope),
    staleTime: 30_000,
  })
}
