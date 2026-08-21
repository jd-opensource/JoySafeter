import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { act, cleanup, render, waitFor } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { authApi } from './auth/api-client'
import { startSilentSessionRefresh } from './auth/session-refresh'
import { clearNonSessionQueryData, resetManagedScopeQueries } from './query-client-lifecycle'

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement
globalThis.localStorage = dom.window.localStorage

function ActiveManagedQuery({
  queryFn = () => new Promise<Array<{ id: string }>>(() => {}),
}: {
  queryFn?: () => Promise<Array<{ id: string }>>
}) {
  const { data } = useQuery({
    queryKey: ['agents'],
    queryFn,
    staleTime: Infinity,
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

function ActiveAuthMeQuery({
  queryFn = () => new Promise<{ orgId: string }>(() => {}),
}: {
  queryFn?: () => Promise<{ orgId: string }>
}) {
  const { data } = useQuery({
    queryKey: ['auth-me', 'user-1'],
    queryFn,
    staleTime: Infinity,
    retry: false,
  })
  return <div data-testid="auth-me">{data?.orgId ?? ''}</div>
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
    queryClient.setQueryData(['session', 'org-a:project-a', 'session-a'], {
      id: 'session-a',
      project_id: 'project-a',
    })
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
    expect(queryClient.getQueryData(['session', 'org-a:project-a', 'session-a'])).toBeUndefined()
    expect(queryClient.getQueryData(['agent', 'agent-from-project-a'])).toBeUndefined()
  })

  it('does not refetch active managed queries by default while clearing context data', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    queryClient.setQueryData(['agents'], [{ id: 'agent-from-project-a' }])
    let fetchCount = 0
    const queryFn = async () => {
      fetchCount += 1
      return [{ id: 'agent-refetched-from-old-scope' }]
    }

    const { getByTestId } = render(
      <QueryClientProvider client={queryClient}>
        <ActiveManagedQuery queryFn={queryFn} />
      </QueryClientProvider>,
    )

    expect(getByTestId('agents').textContent).toBe('agent-from-project-a')

    await act(async () => {
      clearNonSessionQueryData(queryClient)
    })

    await waitFor(() => {
      expect(getByTestId('agents').textContent).toBe('')
    })
    expect(fetchCount).toBe(0)
  })

  it('preserves an active auth-me query when resetting managed scope after an org switch', async () => {
    const queryClient = createQueryClient()
    queryClient.setQueryData(['session'], { user: { id: 'user-1' } })
    queryClient.setQueryData(['auth-me', 'user-1'], { orgId: 'org-a' })
    queryClient.setQueryData(['agents'], [{ id: 'agent-from-project-a' }])
    let authMeFetchCount = 0
    const authMeQueryFn = () => {
      authMeFetchCount += 1
      return new Promise<{ orgId: string }>(() => {})
    }
    let managedFetchCount = 0
    const managedQueryFn = () => {
      managedFetchCount += 1
      return new Promise<Array<{ id: string }>>(() => {})
    }

    const { getByTestId } = render(
      <QueryClientProvider client={queryClient}>
        <ActiveAuthMeQuery queryFn={authMeQueryFn} />
        <ActiveManagedQuery queryFn={managedQueryFn} />
      </QueryClientProvider>,
    )

    expect(getByTestId('auth-me').textContent).toBe('org-a')
    expect(getByTestId('agents').textContent).toBe('agent-from-project-a')

    await act(async () => {
      resetManagedScopeQueries(queryClient)
    })

    // Scoped data is cleared and refetched under the new context...
    await waitFor(() => {
      expect(getByTestId('agents').textContent).toBe('')
    })
    expect(managedFetchCount).toBe(1)
    expect(authMeFetchCount).toBe(1)
    // ...but the auth-me query that ProjectProvider gates rendering on must survive,
    // otherwise the whole app hangs on the loading spinner (blank page) until refresh.
    expect(getByTestId('auth-me').textContent).toBe('org-a')
    expect(queryClient.getQueryData(['auth-me', 'user-1'])).toEqual({ orgId: 'org-a' })
    expect(queryClient.getQueryData(['session'])).toEqual({ user: { id: 'user-1' } })
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

      expect(firstInvalidate).toHaveBeenCalledWith({ queryKey: ['session'], exact: true })
      expect(secondInvalidate).not.toHaveBeenCalled()
    } finally {
      cleanupFirst()
    }
  })
})
