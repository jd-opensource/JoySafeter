'use client'

import { useQuery } from '@tanstack/react-query'

import { useLlmCatalog } from '@/hooks/managed/use-llm-catalog'
import {
  activeModelConnectionsQueryKey,
  compatibleCredentialsQueryKey,
  consumerCredentialsQueryKey,
  fetchManagedModelConnectionByName,
  fetchManagedModelCredentialOptions,
  modelConnectionByNameQueryKey,
  protocolCredentialsQueryKey,
} from '@/lib/managed/credential-client'
import { hasManagedRequestScope, useManagedRequestScope } from '@/lib/managed/request-scope'
import type { Credential } from '@/types/managed'

interface UseCompatibleCredentialsOptions {
  engineId?: string
  modelConsumerId?: string
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

export function useCompatibleCredentials({
  engineId = '',
  modelConsumerId = '',
  enabled = true,
}: UseCompatibleCredentialsOptions) {
  const managedScope = useManagedRequestScope()
  const catalogQuery = useLlmCatalog()
  const catalogVersion = catalogQuery.data?.version ?? ''
  const queryEnabled =
    enabled &&
    Boolean(engineId || modelConsumerId) &&
    !(engineId && modelConsumerId) &&
    catalogQuery.isSuccess &&
    Boolean(catalogVersion) &&
    hasManagedRequestScope(managedScope)

  return useQuery<Credential[]>({
    queryKey: modelConsumerId
      ? consumerCredentialsQueryKey(managedScope.key, modelConsumerId, catalogVersion)
      : compatibleCredentialsQueryKey(managedScope.key, engineId, catalogVersion),
    queryFn: () =>
      fetchManagedModelCredentialOptions(
        modelConsumerId ? { compatibleConsumer: modelConsumerId } : { compatibleEngine: engineId },
        managedScope,
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
    queryFn: () => fetchManagedModelCredentialOptions({}, managedScope, 'Active Model Connection'),
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
    queryFn: () => fetchManagedModelConnectionByName(name, managedScope),
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
      fetchManagedModelCredentialOptions(
        { protocol: protocolId },
        managedScope,
        'Protocol Credential',
      ),
    enabled: queryEnabled,
    staleTime: 30_000,
  })
}
