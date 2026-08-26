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
import { parseCredentialId, type CredentialId } from '@/types/entity-id'
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
  const seenCursors = new Set<CredentialId>()
  let afterId: CredentialId | undefined

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
    const lastId = page.last_id == null ? null : parseCredentialId(page.last_id)
    if (page.has_more) {
      if (!lastId || seenCursors.has(lastId)) {
        throw new Error('Service Credential pagination returned an invalid cursor')
      }
      seenCursors.add(lastId)
      afterId = lastId
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
