'use client'

import { QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useState } from 'react'

import { i18n } from '@/lib/i18n'
import { toastOperationError } from '@/lib/managed/errors'

interface QueryProviderProps {
  children: React.ReactNode
}

/**
 * React Query provider for data fetching
 */
export function QueryProvider({ children }: QueryProviderProps) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        queryCache: new QueryCache({
          onError: (error, query) => {
            // Only toast background refetch failures (data was previously loaded).
            // Fresh loads should show error state in the component, not a toast.
            if (query.state.data !== undefined) {
              const t = i18n.t.bind(i18n)
              toastOperationError(t, error, 'common.operationFailed')
            }
          },
        }),
        defaultOptions: {
          queries: {
            staleTime: 60 * 1000, // 1 minute
            gcTime: 10 * 60 * 1000, // 10 minutes (formerly cacheTime)
            refetchOnWindowFocus: false,
          },
          mutations: {
            onError: (error) => {
              const t = i18n.t.bind(i18n)
              toastOperationError(t, error, 'common.operationFailed')
            },
          },
        },
      }),
  )

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}
