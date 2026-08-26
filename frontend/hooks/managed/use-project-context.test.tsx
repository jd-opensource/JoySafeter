import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, render, waitFor } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  AGENT_ID,
  ORGANIZATION_ID,
  OTHER_ORGANIZATION_ID,
  OTHER_PROJECT_ID,
  PROJECT_ID,
  THIRD_ORGANIZATION_ID,
  THIRD_PROJECT_ID,
  USER_ID,
} from '@/test-utils/entity-ids'
import type { OrganizationId, ProjectId } from '@/types/entity-id'

vi.mock('@/lib/api-client', () => ({
  extractErrorFromResponse: vi.fn(async () => new Error('mock api error')),
  managedDelete: vi.fn(),
  managedGet: vi.fn(),
  managedPatch: vi.fn(),
  managedPost: vi.fn(),
  managedPut: vi.fn(),
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

function authContext(orgId: OrganizationId, projectId: ProjectId) {
  return {
    user: { id: USER_ID, email: 'user@example.com', name: 'User' },
    organization: { id: orgId, name: orgId, slug: orgId, role: 'owner' },
    project: { id: projectId, name: projectId, slug: projectId, is_default: true },
    organizations: [
      { id: ORGANIZATION_ID, name: 'Org A', slug: 'org-a', role: 'owner' },
      { id: OTHER_ORGANIZATION_ID, name: 'Org B', slug: 'org-b', role: 'owner' },
    ],
    projects: [{ id: projectId, name: projectId, slug: projectId, is_default: true }],
  }
}

function switchContext(orgId: OrganizationId, projectId: ProjectId, name: string, slug: string) {
  const project = { id: projectId, name, slug, is_default: true }
  return {
    org_id: orgId,
    project_id: projectId,
    project,
    projects: [project],
  }
}

function Harness({ onReady }: { onReady: (ctx: ReturnType<typeof useProjectContext>) => void }) {
  const ctx = useProjectContext()
  onReady(ctx)
  return (
    <button
      type="button"
      onClick={() => ctx.switchProject(OTHER_PROJECT_ID, OTHER_ORGANIZATION_ID)}
    >
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
      currentProject: null,
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
      currentProject: null,
      organizations: [],
      projects: [],
    })
    localStorage.clear()
  })

  it('uses existing managed context without bootstrapping auth context again', async () => {
    useProjectStore.setState({
      currentOrgId: ORGANIZATION_ID,
      currentProjectId: PROJECT_ID,
      currentProject: { id: PROJECT_ID, name: 'Project A', slug: 'project-a', is_default: true },
      organizations: [{ id: ORGANIZATION_ID, name: 'Org A', slug: 'org-a', role: 'owner' }],
      projects: [{ id: PROJECT_ID, name: 'Project A', slug: 'project-a', is_default: true }],
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
      await Promise.resolve()
    })

    expect(managedGetMock).not.toHaveBeenCalled()
    expect(currentContext?.orgId).toBe(ORGANIZATION_ID)
    expect(currentContext?.projectId).toBe(PROJECT_ID)
    expect(currentContext?.isLoading).toBe(false)
  })

  it('clears old managed query data immediately after switching project context', async () => {
    managedGetMock.mockResolvedValue(authContext(ORGANIZATION_ID, PROJECT_ID))
    managedPostMock.mockResolvedValue(
      switchContext(OTHER_ORGANIZATION_ID, OTHER_PROJECT_ID, 'Project B', 'project-b'),
    )
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    queryClient.setQueryData(['agents'], [{ id: AGENT_ID }])
    queryClient.setQueryData(['agent', AGENT_ID], { id: AGENT_ID })

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
      expect(useProjectStore.getState().currentProjectId).toBe(PROJECT_ID)
    })

    await act(async () => {
      getByText('switch').click()
    })

    await waitFor(() => {
      expect(useProjectStore.getState().currentProjectId).toBe(OTHER_PROJECT_ID)
      expect(currentContext?.projectId).toBe(OTHER_PROJECT_ID)
    })
    expect(queryClient.getQueryData(['agents'])).toBeUndefined()
    expect(queryClient.getQueryData(['agent', AGENT_ID])).toBeUndefined()
  })

  it('accepts the complete switch-context response contract', async () => {
    managedGetMock.mockResolvedValue(authContext(ORGANIZATION_ID, PROJECT_ID))
    managedPostMock.mockResolvedValue(
      switchContext(OTHER_ORGANIZATION_ID, OTHER_PROJECT_ID, 'Project B', 'project-b'),
    )
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
      expect(useProjectStore.getState().currentProjectId).toBe(PROJECT_ID)
    })

    await act(async () => {
      await currentContext!.switchProject(OTHER_PROJECT_ID, OTHER_ORGANIZATION_ID)
    })

    expect(useProjectStore.getState().currentOrgId).toBe(OTHER_ORGANIZATION_ID)
    expect(useProjectStore.getState().currentProjectId).toBe(OTHER_PROJECT_ID)
  })

  it('does not let the initial auth context load overwrite a completed project switch', async () => {
    const initialLoad = deferred<ReturnType<typeof authContext>>()
    managedGetMock.mockReturnValue(initialLoad.promise)
    managedPostMock.mockResolvedValue(
      switchContext(OTHER_ORGANIZATION_ID, OTHER_PROJECT_ID, 'Project B', 'project-b'),
    )
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
      await currentContext!.switchProject(OTHER_PROJECT_ID, OTHER_ORGANIZATION_ID)
    })

    expect(useProjectStore.getState().currentOrgId).toBe(OTHER_ORGANIZATION_ID)
    expect(useProjectStore.getState().currentProjectId).toBe(OTHER_PROJECT_ID)

    await act(async () => {
      initialLoad.resolve(authContext(ORGANIZATION_ID, PROJECT_ID))
      await Promise.resolve()
    })

    expect(useProjectStore.getState().currentOrgId).toBe(OTHER_ORGANIZATION_ID)
    expect(useProjectStore.getState().currentProjectId).toBe(OTHER_PROJECT_ID)
  })

  it('does not let an old auth context load overwrite a context changed by another hook instance', async () => {
    const initialLoad = deferred<ReturnType<typeof authContext>>()
    managedGetMock.mockReturnValue(initialLoad.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    render(
      <QueryClientProvider client={queryClient}>
        <Harness onReady={() => undefined} />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(managedGetMock).toHaveBeenCalledWith('/auth/me')
    })

    await act(async () => {
      useProjectStore.setState({
        currentOrgId: OTHER_ORGANIZATION_ID,
        currentProjectId: OTHER_PROJECT_ID,
        currentProject: {
          id: OTHER_PROJECT_ID,
          name: 'Project B',
          slug: 'project-b',
          is_default: true,
        },
        organizations: [{ id: OTHER_ORGANIZATION_ID, name: 'Org B', slug: 'org-b', role: 'owner' }],
        projects: [
          { id: OTHER_PROJECT_ID, name: 'Project B', slug: 'project-b', is_default: true },
        ],
      })
      await Promise.resolve()
    })

    await act(async () => {
      initialLoad.resolve(authContext(ORGANIZATION_ID, PROJECT_ID))
      await Promise.resolve()
    })

    expect(useProjectStore.getState().currentOrgId).toBe(OTHER_ORGANIZATION_ID)
    expect(useProjectStore.getState().currentProjectId).toBe(OTHER_PROJECT_ID)
  })

  it('ignores an older switch response that resolves after a newer switch', async () => {
    managedGetMock.mockResolvedValue(authContext(ORGANIZATION_ID, PROJECT_ID))
    const firstSwitch = deferred<ReturnType<typeof switchContext>>()
    const secondSwitch = deferred<ReturnType<typeof switchContext>>()
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
      expect(useProjectStore.getState().currentProjectId).toBe(PROJECT_ID)
    })

    let firstPromise!: Promise<void>
    let secondPromise!: Promise<void>
    await act(async () => {
      firstPromise = currentContext!.switchProject(OTHER_PROJECT_ID, OTHER_ORGANIZATION_ID)
      secondPromise = currentContext!.switchProject(THIRD_PROJECT_ID, THIRD_ORGANIZATION_ID)
      await Promise.resolve()
    })

    await act(async () => {
      secondSwitch.resolve(
        switchContext(THIRD_ORGANIZATION_ID, THIRD_PROJECT_ID, 'Project C', 'project-c'),
      )
      await secondPromise
    })

    expect(useProjectStore.getState().currentProjectId).toBe(THIRD_PROJECT_ID)

    await act(async () => {
      firstSwitch.resolve(
        switchContext(OTHER_ORGANIZATION_ID, OTHER_PROJECT_ID, 'Project B', 'project-b'),
      )
      await firstPromise
    })

    expect(useProjectStore.getState().currentOrgId).toBe(THIRD_ORGANIZATION_ID)
    expect(useProjectStore.getState().currentProjectId).toBe(THIRD_PROJECT_ID)
  })
})
