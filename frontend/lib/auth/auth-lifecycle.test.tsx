import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { cleanup, render, waitFor } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import { afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest'

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement
globalThis.localStorage = dom.window.localStorage

let clearAuthenticatedClientState: typeof import('./auth-lifecycle').clearAuthenticatedClientState
let useProjectStore: typeof import('@/stores/managed/project-store').useProjectStore

function ActiveManagedQuery({ queryFn }: { queryFn: () => Promise<Array<{ id: string }>> }) {
  const { data } = useQuery({
    queryKey: ['agents'],
    queryFn,
    staleTime: Infinity,
    retry: false,
  })
  return <div data-testid="agents">{data?.map((agent) => agent.id).join(',') ?? ''}</div>
}

describe('auth lifecycle cleanup', () => {
  beforeAll(async () => {
    const authLifecycleModule = await import('./auth-lifecycle')
    const projectStoreModule = await import('@/stores/managed/project-store')
    clearAuthenticatedClientState = authLifecycleModule.clearAuthenticatedClientState
    useProjectStore = projectStoreModule.useProjectStore
  })

  beforeEach(() => {
    useProjectStore.setState({
      currentOrgId: 'org-a',
      currentProjectId: 'project-a',
      organizations: [{ id: 'org-a', name: 'Org A', slug: 'org-a', role: 'owner' }],
      projects: [{ id: 'project-a', name: 'Project A', slug: 'project-a', is_default: true }],
    })
  })

  afterEach(() => {
    cleanup()
    useProjectStore.setState({
      currentOrgId: null,
      currentProjectId: null,
      organizations: [],
      projects: [],
    })
    localStorage.clear()
  })

  it('removes authenticated query data while preserving the session slot', () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    queryClient.setQueryData(['session'], { user: { id: 'user-a' } })
    queryClient.setQueryData(['auth-me', 'user-a'], { project: { id: 'project-a' } })
    queryClient.setQueryData(['agents'], [{ id: 'agent-a' }])

    clearAuthenticatedClientState(queryClient)

    expect(queryClient.getQueryData(['session'])).toEqual({ user: { id: 'user-a' } })
    expect(queryClient.getQueryData(['auth-me', 'user-a'])).toBeUndefined()
    expect(queryClient.getQueryData(['agents'])).toBeUndefined()
    expect(useProjectStore.getState().currentOrgId).toBeNull()
    expect(useProjectStore.getState().currentProjectId).toBeNull()
  })

  it('clears active authenticated query data without refetching during auth teardown', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    queryClient.setQueryData(['agents'], [{ id: 'agent-a' }])
    let fetchCount = 0
    const queryFn = async () => {
      fetchCount += 1
      return [{ id: 'agent-refetched-after-logout' }]
    }

    const { getByTestId } = render(
      <QueryClientProvider client={queryClient}>
        <ActiveManagedQuery queryFn={queryFn} />
      </QueryClientProvider>,
    )

    expect(getByTestId('agents').textContent).toBe('agent-a')

    clearAuthenticatedClientState(queryClient)

    await waitFor(() => {
      expect(getByTestId('agents').textContent).toBe('')
    })
    expect(fetchCount).toBe(0)
  })
})
