import type { Query, QueryClient } from '@tanstack/react-query'

interface ClearNonSessionQueryDataOptions {
  refetchActive?: boolean
}

function isSessionQuery(query: Query): boolean {
  return query.queryKey.length === 1 && query.queryKey[0] === 'session'
}

export function clearNonSessionQueryData(
  queryClient: QueryClient,
  { refetchActive = false }: ClearNonSessionQueryDataOptions = {},
): void {
  const predicate = (query: Query) => !isSessionQuery(query)
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
