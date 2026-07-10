import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { act, cleanup, render, waitFor } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { authApi } from './auth/api-client'
import { startSilentSessionRefresh } from './auth/session-refresh'
import { clearNonSessionQueryData } from './query-client-lifecycle'

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement
globalThis.localStorage = dom.window.localStorage

function ActiveManagedQuery() {
  const { data } = useQuery({
    queryKey: ['agents'],
    queryFn: () => new Promise<Array<{ id: string }>>(() => {}),
    retry: false,
  })
  return <div data-testid="agents">{data?.map((agent) => agent.id).join(',') ?? ''}</div>
}

function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  })
}

describe('query client lifecycle', () => {
  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
    localStorage.clear()
  })

  it('clears active and inactive non-session query data while preserving session', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    queryClient.setQueryData(['session'], { user: { id: 'user-1' } })
    queryClient.setQueryData(['agents'], [{ id: 'agent-from-project-a' }])
    queryClient.setQueryData(['agent', 'agent-from-project-a'], { id: 'agent-from-project-a' })

    const { getByTestId } = render(
      <QueryClientProvider client={queryClient}>
        <ActiveManagedQuery />
      </QueryClientProvider>,
    )

    expect(getByTestId('agents').textContent).toBe('agent-from-project-a')

    await act(async () => {
      clearNonSessionQueryData(queryClient)
    })

    await waitFor(() => {
      expect(getByTestId('agents').textContent).toBe('')
    })
    expect(queryClient.getQueryData(['session'])).toEqual({ user: { id: 'user-1' } })
    expect(queryClient.getQueryData(['agent', 'agent-from-project-a'])).toBeUndefined()
  })

  it('refreshes the remaining active query client after the latest session subscriber unmounts', async () => {
    const firstClient = createQueryClient()
    const secondClient = createQueryClient()
    const firstInvalidate = vi.spyOn(firstClient, 'invalidateQueries')
    const secondInvalidate = vi.spyOn(secondClient, 'invalidateQueries')
    const refreshTokenMock = vi.spyOn(authApi, 'refreshToken').mockResolvedValue(undefined)
    const cleanupFirst = startSilentSessionRefresh(firstClient)
    const cleanupSecond = startSilentSessionRefresh(secondClient)

    try {
      cleanupSecond()
      window.dispatchEvent(new window.Event('focus'))
      await waitFor(() => expect(refreshTokenMock).toHaveBeenCalledTimes(1))

      expect(firstInvalidate).toHaveBeenCalledWith({ queryKey: ['session'] })
      expect(secondInvalidate).not.toHaveBeenCalled()
    } finally {
      cleanupFirst()
    }
  })
})
