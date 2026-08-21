import type { Query, QueryClient } from '@tanstack/react-query'

interface ClearNonSessionQueryDataOptions {
  refetchActive?: boolean
}

function isSessionQuery(query: Query): boolean {
  return query.queryKey.length === 1 && query.queryKey[0] === 'session'
}

function isAuthMeQuery(query: Query): boolean {
  return query.queryKey[0] === 'auth-me'
}

function clearQueryData(
  queryClient: QueryClient,
  predicate: (query: Query) => boolean,
  refetchActive: boolean,
): void {
  const queries = queryClient.getQueryCache().findAll({ predicate })

  for (const query of queries) {
    if (query.isActive()) {
      query.reset()
    }
  }

  queryClient.removeQueries({ predicate, type: 'inactive' })
  if (refetchActive) {
    void queryClient.refetchQueries({ predicate, type: 'active' })
  }
}

export function clearNonSessionQueryData(
  queryClient: QueryClient,
  { refetchActive = false }: ClearNonSessionQueryDataOptions = {},
): void {
  const predicate = (query: Query) => !isSessionQuery(query)
  clearQueryData(queryClient, predicate, refetchActive)
}

export function resetManagedScopeQueries(queryClient: QueryClient): void {
  const predicate = (query: Query) => !isSessionQuery(query) && !isAuthMeQuery(query)
  clearQueryData(queryClient, predicate, true)
  void queryClient.invalidateQueries({ predicate: isAuthMeQuery, refetchType: 'active' })
}
