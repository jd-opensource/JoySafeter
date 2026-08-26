'use client'

import { useQuery } from '@tanstack/react-query'

import { useLlmCatalog } from '@/hooks/managed/use-llm-catalog'
import { managedGet } from '@/lib/api-client'
import { apiCollectionPath } from '@/lib/managed/api-paths'
import {
  hasManagedRequestScope,
  managedRequestOptions,
  useManagedRequestScope,
} from '@/lib/managed/request-scope'
import { parseCredentialListResponse } from '@/lib/managed/credential-response-parsers'
import { parseCredentialId, type CredentialId } from '@/types/entity-id'
import type { Credential } from '@/types/managed'

interface CredentialPage {
  data: unknown[]
  has_more: boolean
  last_id?: string | null
}

interface UseCompatibleCredentialsOptions {
  engineId: string
  enabled?: boolean
}

interface UseActiveModelConnectionsOptions {
  enabled?: boolean
}

interface UseModelConnectionByNameOptions {
  name: string
  enabled?: boolean
}

interface UseProtocolCredentialsOptions {
  protocolId: string
  enabled?: boolean
}

const PAGE_SIZE = 100

async function fetchAllModelConnections(
  managedScope: ReturnType<typeof useManagedRequestScope>,
  filter: Record<string, string>,
  errorLabel: string,
): Promise<Credential[]> {
  const credentials: Credential[] = []
  let afterId: CredentialId | undefined

  for (;;) {
    const page = await managedGet<CredentialPage>(
      apiCollectionPath('credentials', {
        limit: PAGE_SIZE,
        after_id: afterId,
        kind: 'model',
        include_archived: false,
        ...filter,
      }),
      managedRequestOptions(managedScope),
    )
    credentials.push(...parseCredentialListResponse(page.data))
    const lastId = page.last_id == null ? null : parseCredentialId(page.last_id)
    if (!page.has_more) return credentials
    if (!lastId || lastId === afterId) {
      throw new Error(`${errorLabel} pagination returned an invalid cursor`)
    }
    afterId = lastId
  }
}

export function compatibleCredentialsScopePrefix(scopeKey: string) {
  return ['compatible-credentials', scopeKey] as const
}

export function compatibleCredentialsQueryPrefix(scopeKey: string, engineId: string) {
  return [...compatibleCredentialsScopePrefix(scopeKey), engineId] as const
}

export function activeModelConnectionsQueryKey(scopeKey: string, catalogVersion = '') {
  return ['active-model-connections', scopeKey, catalogVersion] as const
}

export function compatibleCredentialsQueryKey(
  scopeKey: string,
  engineId: string,
  catalogVersion = '',
) {
  return [...compatibleCredentialsQueryPrefix(scopeKey, engineId), catalogVersion] as const
}

export function modelConnectionByNameQueryKey(scopeKey: string, name: string, catalogVersion = '') {
  return ['model-connection-by-name', scopeKey, name, catalogVersion] as const
}

export function protocolCredentialsQueryKey(
  scopeKey: string,
  protocolId: string,
  catalogVersion = '',
) {
  return ['protocol-credentials', scopeKey, protocolId, catalogVersion] as const
}

export function useCompatibleCredentials({
  engineId,
  enabled = true,
}: UseCompatibleCredentialsOptions) {
  const managedScope = useManagedRequestScope()
  const catalogQuery = useLlmCatalog()
  const catalogVersion = catalogQuery.data?.version ?? ''
  const queryEnabled =
    enabled &&
    Boolean(engineId) &&
    catalogQuery.isSuccess &&
    Boolean(catalogVersion) &&
    hasManagedRequestScope(managedScope)

  return useQuery<Credential[]>({
    queryKey: compatibleCredentialsQueryKey(managedScope.key, engineId, catalogVersion),
    queryFn: () =>
      fetchAllModelConnections(
        managedScope,
        { compatible_engine: engineId },
        'Compatible Credential',
      ),
    enabled: queryEnabled,
    staleTime: 30_000,
  })
}

export function useActiveModelConnections({
  enabled = true,
}: UseActiveModelConnectionsOptions = {}) {
  const managedScope = useManagedRequestScope()
  const catalogQuery = useLlmCatalog()
  const catalogVersion = catalogQuery.data?.version ?? ''
  const queryEnabled =
    enabled &&
    catalogQuery.isSuccess &&
    Boolean(catalogVersion) &&
    hasManagedRequestScope(managedScope)

  return useQuery<Credential[]>({
    queryKey: activeModelConnectionsQueryKey(managedScope.key, catalogVersion),
    queryFn: () => fetchAllModelConnections(managedScope, {}, 'Active Model Connection'),
    enabled: queryEnabled,
    staleTime: 30_000,
  })
}

export function useModelConnectionByName({
  name,
  enabled = true,
}: UseModelConnectionByNameOptions) {
  const managedScope = useManagedRequestScope()
  const catalogQuery = useLlmCatalog()
  const catalogVersion = catalogQuery.data?.version ?? ''
  const queryEnabled =
    enabled &&
    Boolean(name) &&
    catalogQuery.isSuccess &&
    Boolean(catalogVersion) &&
    hasManagedRequestScope(managedScope)

  return useQuery<Credential | null>({
    queryKey: modelConnectionByNameQueryKey(managedScope.key, name, catalogVersion),
    queryFn: async () => {
      const page = await managedGet<CredentialPage>(
        apiCollectionPath('credentials', { limit: 1, kind: 'model', name }),
        managedRequestOptions(managedScope),
      )
      const credentials = parseCredentialListResponse(page.data)
      return credentials.find((credential) => credential.name === name) ?? null
    },
    enabled: queryEnabled,
    staleTime: 30_000,
  })
}

export function useProtocolCredentials({
  protocolId,
  enabled = true,
}: UseProtocolCredentialsOptions) {
  const managedScope = useManagedRequestScope()
  const catalogQuery = useLlmCatalog()
  const catalogVersion = catalogQuery.data?.version ?? ''
  const queryEnabled =
    enabled &&
    Boolean(protocolId) &&
    catalogQuery.isSuccess &&
    Boolean(catalogVersion) &&
    hasManagedRequestScope(managedScope)

  return useQuery<Credential[]>({
    queryKey: protocolCredentialsQueryKey(managedScope.key, protocolId, catalogVersion),
    queryFn: () =>
      fetchAllModelConnections(managedScope, { protocol: protocolId }, 'Protocol Credential'),
    enabled: queryEnabled,
    staleTime: 30_000,
  })
}
