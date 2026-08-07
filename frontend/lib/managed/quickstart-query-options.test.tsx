import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { cleanup, render, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { quickstartQueryOptions } from './quickstart-query-options'

function QuickstartResource({ queryFn }: { queryFn: () => Promise<string> }) {
  const { data } = useQuery(
    quickstartQueryOptions({
      queryKey: ['quickstart-resource'],
      queryFn,
    }),
  )

  return <div data-testid="resource">{data ?? ''}</div>
}

describe('quickstart query options', () => {
  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
  })

  it('refetches fresh cached resources when quickstart is entered again', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
          staleTime: 60_000,
        },
      },
    })
    const queryFn = vi.fn().mockResolvedValue('loaded')

    const firstRender = render(
      <QueryClientProvider client={queryClient}>
        <QuickstartResource queryFn={queryFn} />
      </QueryClientProvider>,
    )

    await waitFor(() => expect(queryFn).toHaveBeenCalledTimes(1))
    firstRender.unmount()

    render(
      <QueryClientProvider client={queryClient}>
        <QuickstartResource queryFn={queryFn} />
      </QueryClientProvider>,
    )

    await waitFor(() => expect(queryFn).toHaveBeenCalledTimes(2))
  })
})
