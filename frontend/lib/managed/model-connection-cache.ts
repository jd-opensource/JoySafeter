import type { QueryClient } from '@tanstack/react-query'

import {
  compatibleCredentialsQueryPrefix,
  consumerCredentialsQueryPrefix,
} from '@/hooks/managed/use-compatible-credentials'
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
    { queryKey: ['active-model-connections', scopeKey] },
    (current) => upsertCredential(current, credential),
  )
  if (credential.protocol) {
    queryClient.setQueriesData<Credential[]>(
      { queryKey: ['protocol-credentials', scopeKey, credential.protocol] },
      (current) => upsertCredential(current, credential),
    )
  }
  void queryClient.invalidateQueries({ queryKey: ['credentials', scopeKey] })
}
