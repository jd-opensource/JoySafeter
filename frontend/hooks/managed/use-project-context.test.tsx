import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, render, waitFor } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/api-client', () => ({
  managedGet: vi.fn(),
  managedPost: vi.fn(),
}))

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement
globalThis.localStorage = dom.window.localStorage

let managedGetMock: ReturnType<typeof vi.fn>
let managedPostMock: ReturnType<typeof vi.fn>
let useProjectContext: typeof import('./use-project-context').useProjectContext
let useProjectStore: typeof import('@/stores/managed/project-store').useProjectStore

function authContext(orgId: string, projectId: string) {
  return {
    user: { id: 'user-1', email: 'user@example.com', name: 'User' },
    organization: { id: orgId, name: orgId, slug: orgId, role: 'owner' },
    project: { id: projectId, name: projectId, slug: projectId, is_default: true },
    organizations: [
      { id: 'org-a', name: 'Org A', slug: 'org-a', role: 'owner' },
      { id: 'org-b', name: 'Org B', slug: 'org-b', role: 'owner' },
    ],
    projects: [{ id: projectId, name: projectId, slug: projectId, is_default: true }],
  }
}

function Harness({ onReady }: { onReady: (ctx: ReturnType<typeof useProjectContext>) => void }) {
  const ctx = useProjectContext()
  onReady(ctx)
  return (
    <button type="button" onClick={() => ctx.switchProject('project-b', 'org-b')}>
      switch
    </button>
  )
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

describe('useProjectContext managed cache lifecycle', () => {
  beforeAll(async () => {
    const apiClientModule = await import('@/lib/api-client')
    const projectContextModule = await import('./use-project-context')
    const projectStoreModule = await import('@/stores/managed/project-store')
    managedGetMock = apiClientModule.managedGet as unknown as ReturnType<typeof vi.fn>
    managedPostMock = apiClientModule.managedPost as unknown as ReturnType<typeof vi.fn>
    useProjectContext = projectContextModule.useProjectContext
    useProjectStore = projectStoreModule.useProjectStore
  })

  beforeEach(() => {
    managedGetMock.mockReset()
    managedPostMock.mockReset()
    useProjectStore.setState({
      currentOrgId: null,
      currentProjectId: null,
      organizations: [],
      projects: [],
    })
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
    useProjectStore.setState({
      currentOrgId: null,
      currentProjectId: null,
      organizations: [],
      projects: [],
    })
    localStorage.clear()
  })

  it('clears old managed query data immediately after switching project context', async () => {
    managedGetMock.mockResolvedValue(authContext('org-a', 'project-a'))
    managedPostMock.mockResolvedValue({
      org_id: 'org-b',
      project: { id: 'project-b', name: 'Project B', slug: 'project-b', is_default: true },
      projects: [{ id: 'project-b', name: 'Project B', slug: 'project-b', is_default: true }],
    })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    queryClient.setQueryData(['agents'], [{ id: 'agent-from-project-a' }])
    queryClient.setQueryData(['agent', 'agent-from-project-a'], { id: 'agent-from-project-a' })

    let currentContext: ReturnType<typeof useProjectContext> | null = null
    const { getByText } = render(
      <QueryClientProvider client={queryClient}>
        <Harness
          onReady={(ctx) => {
            currentContext = ctx
          }}
        />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(useProjectStore.getState().currentProjectId).toBe('project-a')
    })

    await act(async () => {
      getByText('switch').click()
    })

    await waitFor(() => {
      expect(useProjectStore.getState().currentProjectId).toBe('project-b')
      expect(currentContext?.projectId).toBe('project-b')
    })
    expect(queryClient.getQueryData(['agents'])).toBeUndefined()
    expect(queryClient.getQueryData(['agent', 'agent-from-project-a'])).toBeUndefined()
  })

  it('does not let the initial auth context load overwrite a completed project switch', async () => {
    const initialLoad = deferred<ReturnType<typeof authContext>>()
    managedGetMock.mockReturnValue(initialLoad.promise)
    managedPostMock.mockResolvedValue({
      org_id: 'org-b',
      project: { id: 'project-b', name: 'Project B', slug: 'project-b', is_default: true },
      projects: [{ id: 'project-b', name: 'Project B', slug: 'project-b', is_default: true }],
    })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    let currentContext: ReturnType<typeof useProjectContext> | null = null
    render(
      <QueryClientProvider client={queryClient}>
        <Harness
          onReady={(ctx) => {
            currentContext = ctx
          }}
        />
      </QueryClientProvider>,
    )

    await act(async () => {
      await currentContext!.switchProject('project-b', 'org-b')
    })

    expect(useProjectStore.getState().currentOrgId).toBe('org-b')
    expect(useProjectStore.getState().currentProjectId).toBe('project-b')

    await act(async () => {
      initialLoad.resolve(authContext('org-a', 'project-a'))
      await Promise.resolve()
    })

    expect(useProjectStore.getState().currentOrgId).toBe('org-b')
    expect(useProjectStore.getState().currentProjectId).toBe('project-b')
  })

  it('ignores an older switch response that resolves after a newer switch', async () => {
    managedGetMock.mockResolvedValue(authContext('org-a', 'project-a'))
    const firstSwitch = deferred<{
      org_id: string
      project: { id: string; name: string; slug: string; is_default: boolean }
      projects: Array<{ id: string; name: string; slug: string; is_default: boolean }>
    }>()
    const secondSwitch = deferred<{
      org_id: string
      project: { id: string; name: string; slug: string; is_default: boolean }
      projects: Array<{ id: string; name: string; slug: string; is_default: boolean }>
    }>()
    managedPostMock
      .mockReturnValueOnce(firstSwitch.promise)
      .mockReturnValueOnce(secondSwitch.promise)

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    let currentContext: ReturnType<typeof useProjectContext> | null = null
    render(
      <QueryClientProvider client={queryClient}>
        <Harness
          onReady={(ctx) => {
            currentContext = ctx
          }}
        />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(useProjectStore.getState().currentProjectId).toBe('project-a')
    })

    let firstPromise!: Promise<void>
    let secondPromise!: Promise<void>
    await act(async () => {
      firstPromise = currentContext!.switchProject('project-b', 'org-b')
      secondPromise = currentContext!.switchProject('project-c', 'org-c')
      await Promise.resolve()
    })

    await act(async () => {
      secondSwitch.resolve({
        org_id: 'org-c',
        project: { id: 'project-c', name: 'Project C', slug: 'project-c', is_default: true },
        projects: [{ id: 'project-c', name: 'Project C', slug: 'project-c', is_default: true }],
      })
      await secondPromise
    })

    expect(useProjectStore.getState().currentProjectId).toBe('project-c')

    await act(async () => {
      firstSwitch.resolve({
        org_id: 'org-b',
        project: { id: 'project-b', name: 'Project B', slug: 'project-b', is_default: true },
        projects: [{ id: 'project-b', name: 'Project B', slug: 'project-b', is_default: true }],
      })
      await firstPromise
    })

    expect(useProjectStore.getState().currentOrgId).toBe('org-c')
    expect(useProjectStore.getState().currentProjectId).toBe('project-c')
  })
})
