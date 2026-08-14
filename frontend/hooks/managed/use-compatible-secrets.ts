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
import { parseSecretListResponse } from '@/lib/managed/secret-response-parsers'
import type { Secret } from '@/types/managed'

interface SecretPage {
  data: unknown[]
  has_more: boolean
  last_id?: string | null
}

interface UseCompatibleSecretsOptions {
  engineId: string
  enabled?: boolean
}

interface UseLlmSecretByNameOptions {
  name: string
  enabled?: boolean
}

interface UseProtocolSecretsOptions {
  protocolId: string
  enabled?: boolean
}

const PAGE_SIZE = 100

async function fetchAllLlmSecrets(
  managedScope: ReturnType<typeof useManagedRequestScope>,
  filter: Record<string, string>,
  errorLabel: string,
): Promise<Secret[]> {
  const secrets: Secret[] = []
  let afterId: string | undefined

  for (;;) {
    const page = await managedGet<SecretPage>(
      apiCollectionPath('credentials', {
        limit: PAGE_SIZE,
        after_id: afterId,
        kind: 'model',
        ...filter,
      }),
      managedRequestOptions(managedScope),
    )
    secrets.push(...parseSecretListResponse(page.data))
    if (!page.has_more) return secrets
    if (!page.last_id || page.last_id === afterId) {
      throw new Error(`${errorLabel} pagination returned an invalid cursor`)
    }
    afterId = page.last_id
  }
}

export function compatibleSecretsQueryPrefix(scopeKey: string, engineId: string) {
  return ['compatible-secrets', scopeKey, engineId] as const
}

export function compatibleSecretsQueryKey(scopeKey: string, engineId: string, catalogVersion = '') {
  return [...compatibleSecretsQueryPrefix(scopeKey, engineId), catalogVersion] as const
}

export function llmSecretByNameQueryKey(scopeKey: string, name: string, catalogVersion = '') {
  return ['llm-secret-by-name', scopeKey, name, catalogVersion] as const
}

export function protocolSecretsQueryKey(scopeKey: string, protocolId: string, catalogVersion = '') {
  return ['llm-protocol-secrets', scopeKey, protocolId, catalogVersion] as const
}

export function useCompatibleSecrets({ engineId, enabled = true }: UseCompatibleSecretsOptions) {
  const managedScope = useManagedRequestScope()
  const catalogQuery = useLlmCatalog()
  const catalogVersion = catalogQuery.data?.version ?? ''
  const queryEnabled =
    enabled &&
    Boolean(engineId) &&
    catalogQuery.isSuccess &&
    Boolean(catalogVersion) &&
    hasManagedRequestScope(managedScope)

  return useQuery<Secret[]>({
    queryKey: compatibleSecretsQueryKey(managedScope.key, engineId, catalogVersion),
    queryFn: () =>
      fetchAllLlmSecrets(managedScope, { compatible_engine: engineId }, 'Compatible Secret'),
    enabled: queryEnabled,
    staleTime: 30_000,
  })
}

export function useLlmSecretByName({ name, enabled = true }: UseLlmSecretByNameOptions) {
  const managedScope = useManagedRequestScope()
  const catalogQuery = useLlmCatalog()
  const catalogVersion = catalogQuery.data?.version ?? ''
  const queryEnabled =
    enabled &&
    Boolean(name) &&
    catalogQuery.isSuccess &&
    Boolean(catalogVersion) &&
    hasManagedRequestScope(managedScope)

  return useQuery<Secret | null>({
    queryKey: llmSecretByNameQueryKey(managedScope.key, name, catalogVersion),
    queryFn: async () => {
      const page = await managedGet<SecretPage>(
        apiCollectionPath('credentials', { limit: 1, kind: 'model', name }),
        managedRequestOptions(managedScope),
      )
      const secrets = parseSecretListResponse(page.data)
      return secrets.find((secret) => secret.name === name) ?? null
    },
    enabled: queryEnabled,
    staleTime: 30_000,
  })
}

export function useProtocolSecrets({ protocolId, enabled = true }: UseProtocolSecretsOptions) {
  const managedScope = useManagedRequestScope()
  const catalogQuery = useLlmCatalog()
  const catalogVersion = catalogQuery.data?.version ?? ''
  const queryEnabled =
    enabled &&
    Boolean(protocolId) &&
    catalogQuery.isSuccess &&
    Boolean(catalogVersion) &&
    hasManagedRequestScope(managedScope)

  return useQuery<Secret[]>({
    queryKey: protocolSecretsQueryKey(managedScope.key, protocolId, catalogVersion),
    queryFn: () => fetchAllLlmSecrets(managedScope, { protocol: protocolId }, 'Protocol Secret'),
    enabled: queryEnabled,
    staleTime: 30_000,
  })
}
