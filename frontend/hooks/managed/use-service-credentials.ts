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
import {
  filterSelectableCredentials,
  parseCredentialListResponse,
} from '@/lib/managed/credential-response-parsers'
import type { Credential } from '@/types/managed'

interface CredentialPage {
  data: unknown[]
  has_more: boolean
  last_id?: string | null
}

const PAGE_SIZE = 100

export function serviceCredentialsQueryKey(scopeKey: string) {
  return ['service-credentials', scopeKey] as const
}

export async function fetchAllServiceCredentials(
  scope: ManagedRequestScope,
): Promise<Credential[]> {
  const credentials: Credential[] = []
  const seenCursors = new Set<string>()
  let afterId: string | undefined

  for (;;) {
    const page = await managedGet<CredentialPage>(
      apiCollectionPath('credentials', {
        limit: PAGE_SIZE,
        kind: 'service',
        include_archived: false,
        after_id: afterId,
      }),
      managedRequestOptions(scope),
    )
    if (page.has_more) {
      if (!page.last_id || seenCursors.has(page.last_id)) {
        throw new Error('Service Credential pagination returned an invalid cursor')
      }
      seenCursors.add(page.last_id)
      afterId = page.last_id
    }
    credentials.push(...filterSelectableCredentials(parseCredentialListResponse(page.data)))
    if (!page.has_more) return credentials
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
