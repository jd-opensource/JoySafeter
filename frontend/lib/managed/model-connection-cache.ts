import type { QueryClient } from '@tanstack/react-query'

import {
  activeModelConnectionsQueryPrefix,
  compatibleCredentialsQueryPrefix,
  consumerCredentialsQueryPrefix,
  managedCredentialsQueryPrefix,
  protocolCredentialsQueryPrefix,
} from '@/lib/managed/credential-client'
import type { Credential } from '@/types/managed'

function upsertCredential(current: Credential[] | undefined, credential: Credential) {
  return [credential, ...(current ?? []).filter((item) => item.id !== credential.id)]
}

export function recordCreatedModelConnection(
  queryClient: QueryClient,
  scopeKey: string,
  targetId: string,
  credential: Credential,
  targetKind: 'engine' | 'consumer' = 'engine',
) {
  queryClient.setQueriesData<Credential[]>(
    {
      queryKey:
        targetKind === 'consumer'
          ? consumerCredentialsQueryPrefix(scopeKey, targetId)
          : compatibleCredentialsQueryPrefix(scopeKey, targetId),
    },
    (current) => upsertCredential(current, credential),
  )
  queryClient.setQueriesData<Credential[]>(
    { queryKey: activeModelConnectionsQueryPrefix(scopeKey) },
    (current) => upsertCredential(current, credential),
  )
  if (credential.protocol) {
    queryClient.setQueriesData<Credential[]>(
      { queryKey: protocolCredentialsQueryPrefix(scopeKey, credential.protocol) },
      (current) => upsertCredential(current, credential),
    )
  }
  void queryClient.invalidateQueries({ queryKey: managedCredentialsQueryPrefix(scopeKey) })
}
