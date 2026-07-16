import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, render, waitFor } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('next-runtime-env', () => ({
  env: vi.fn(() => undefined),
}))

vi.mock('@/lib/api-client', () => {
  class MockApiError extends Error {
    public readonly code: string
    public readonly payload: {
      code: string
      message: string
      data?: Record<string, unknown> | null
      source?: string
      retryable?: boolean
      user_action?: string
      detail?: string
      trace_id?: string
    }
    public readonly data?: Record<string, unknown> | null
    public readonly source: string
    public readonly retryable: boolean
    public readonly userAction?: string
    public readonly traceId?: string
    public readonly detail?: string

    constructor(
      public readonly status: number,
      public readonly statusText = 'API error',
      payload?: {
        code: string
        message: string
        data?: Record<string, unknown> | null
        source?: string
        retryable?: boolean
        user_action?: string
        detail?: string
        trace_id?: string
      },
    ) {
      const normalizedPayload = payload ?? {
        code: status > 0 ? `HTTP_${status}` : 'UNKNOWN_ERROR',
        message: statusText,
        data: null,
      }
      super(normalizedPayload.message || statusText)
      this.name = 'ApiError'
      this.code = normalizedPayload.code
      this.payload = normalizedPayload
      this.data = normalizedPayload.data ?? null
      this.source = normalizedPayload.source ?? 'internal'
      this.retryable = normalizedPayload.retryable ?? false
      this.userAction = normalizedPayload.user_action
      this.traceId = normalizedPayload.trace_id
      this.detail = normalizedPayload.detail
    }
  }

  return {
    ApiError: MockApiError,
    createApiError: vi.fn((status: number, message: string) => new MockApiError(status, message)),
    extractErrorFromResponse: vi.fn(
      async (response: Response) => new MockApiError(response.status, response.statusText),
    ),
    isUnauthorizedApiError: vi.fn(() => false),
    MANAGED_API_BASE: 'http://localhost:8000/api/v1',
    managedGet: vi.fn(),
    managedDelete: vi.fn(async (url: string) => {
      const response = await fetch(`http://localhost:8000/api/v1/${url.replace(/^\/+/, '')}`, {
        method: 'DELETE',
      })
      if (!response.ok) {
        throw new MockApiError(response.status, `API ${response.status}`)
      }
      const json = await response.json().catch(() => undefined)
      return json?.data ?? json
    }),
    managedPatch: vi.fn(async (url: string, body?: unknown) => {
      const response = await fetch(`http://localhost:8000/api/v1/${url.replace(/^\/+/, '')}`, {
        method: 'PATCH',
        body: JSON.stringify(body),
      })
      if (!response.ok) {
        throw new MockApiError(response.status, `API ${response.status}`)
      }
      const json = await response.json().catch(() => undefined)
      return json?.data ?? json
    }),
    managedPost: vi.fn(async (url: string, body?: unknown) => {
      const response = await fetch(`http://localhost:8000/api/v1/${url.replace(/^\/+/, '')}`, {
        method: 'POST',
        body: JSON.stringify(body),
      })
      if (!response.ok) {
        throw new MockApiError(response.status, `API ${response.status}`)
      }
      const json = await response.json().catch(() => undefined)
      return json?.data ?? json
    }),
    managedPut: vi.fn(async (url: string, body?: unknown) => {
      const response = await fetch(`http://localhost:8000/api/v1/${url.replace(/^\/+/, '')}`, {
        method: 'PUT',
        body: JSON.stringify(body),
      })
      if (!response.ok) {
        throw new MockApiError(response.status, `API ${response.status}`)
      }
      const json = await response.json().catch(() => undefined)
      return json?.data ?? json
    }),
    managedUpload: vi.fn(),
    apiStream: vi.fn((url: string, body?: unknown, options?: { signal?: AbortSignal }) =>
      fetch(`http://localhost:8000/api/v1/${url.replace(/^\/+/, '')}`, {
        method: 'POST',
        body: JSON.stringify(body),
        signal: options?.signal,
      }),
    ),
    refreshAccessTokenOrRelogin: vi.fn(),
  }
})

interface AuthUser {
  id: string
  email: string
  name: string
  emailVerified: boolean
  isSuperUser: boolean
}

type AuthMockGlobal = typeof globalThis & {
  __joysafeterAuthMockUser?: AuthUser | null
  __joysafeterAuthClientMock?: {
    forgetPassword?: (...args: unknown[]) => unknown
    signInEmail?: (...args: unknown[]) => unknown
    signUpEmail?: (...args: unknown[]) => unknown
  }
}

function setMockSessionUser(user: AuthUser | null) {
  ;(globalThis as AuthMockGlobal).__joysafeterAuthMockUser = user
}

function getMockSessionUser() {
  return (globalThis as AuthMockGlobal).__joysafeterAuthMockUser ?? null
}

function getMockAuthClient() {
  return (globalThis as AuthMockGlobal).__joysafeterAuthClientMock
}

vi.mock('@/lib/auth/auth-client', () => {
  return {
    __setMockSessionUser: setMockSessionUser,
    client: {
      forgetPassword: (...args: unknown[]) =>
        getMockAuthClient()?.forgetPassword?.(...args) ?? Promise.resolve({}),
      signIn: {
        email: (...args: unknown[]) =>
          getMockAuthClient()?.signInEmail?.(...args) ?? Promise.resolve({}),
      },
      signUp: {
        email: (...args: unknown[]) =>
          getMockAuthClient()?.signUpEmail?.(...args) ?? Promise.resolve({}),
      },
    },
    useSession: () => ({
      data: getMockSessionUser() ? { user: getMockSessionUser() } : null,
      isPending: false,
      error: null,
      refetch: async () => {},
    }),
  }
})

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement
globalThis.localStorage = dom.window.localStorage

let ProjectProvider: typeof import('./project-provider').ProjectProvider
let useProjectStore: typeof import('@/stores/managed/project-store').useProjectStore
let managedGetMock: ReturnType<typeof vi.fn>

function wait(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms))
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

function user(id: string): AuthUser {
  return {
    id,
    email: `${id}@example.com`,
    name: id,
    emailVerified: true,
    isSuperUser: false,
  }
}

function authMe(userId: string, orgId: string, projectId: string) {
  return {
    user: {
      id: userId,
      email: `${userId}@example.com`,
      name: userId,
    },
    organization: { id: orgId, name: orgId, slug: orgId, role: 'owner' },
    project: { id: projectId, name: projectId, slug: projectId, is_default: true },
    organizations: [{ id: orgId, name: orgId, slug: orgId, role: 'owner' }],
    projects: [{ id: projectId, name: projectId, slug: projectId, is_default: true }],
  }
}

function authMeWithProject(
  userId: string,
  orgId: string,
  project: {
    id: string
    name: string
    slug: string
    is_default: boolean
    archived_at?: string | null
  },
  projects = [project],
) {
  return {
    user: {
      id: userId,
      email: `${userId}@example.com`,
      name: userId,
    },
    organization: { id: orgId, name: orgId, slug: orgId, role: 'owner' },
    project,
    organizations: [{ id: orgId, name: orgId, slug: orgId, role: 'owner' }],
    projects,
  }
}

describe('ProjectProvider auth context lifecycle', () => {
  let originalFetch: typeof fetch | undefined

  beforeAll(async () => {
    const apiClientModule = await import('@/lib/api-client')
    const projectStoreModule = await import('@/stores/managed/project-store')
    const projectProviderModule = await import('./project-provider')
    managedGetMock = apiClientModule.managedGet as unknown as ReturnType<typeof vi.fn>
    useProjectStore = projectStoreModule.useProjectStore
    ProjectProvider = projectProviderModule.ProjectProvider
  })

  beforeEach(() => {
    originalFetch = globalThis.fetch
    managedGetMock.mockReset()
    setMockSessionUser(null)
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
    if (originalFetch) {
      globalThis.fetch = originalFetch
    } else {
      delete (globalThis as { fetch?: typeof fetch }).fetch
    }
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

  it('does not reuse cached auth-me context after the session user changes', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    queryClient.setQueryData(['session'], { user: user('user-a') })
    queryClient.setQueryData(['auth-me'], authMe('user-a', 'org-a', 'project-a'))
    setMockSessionUser(user('user-a'))

    managedGetMock
      .mockResolvedValueOnce(authMe('user-a', 'org-a', 'project-a'))
      .mockResolvedValueOnce(authMe('user-b', 'org-b', 'project-b'))

    const { rerender } = render(
      <QueryClientProvider client={queryClient}>
        <ProjectProvider>
          <div>ready</div>
        </ProjectProvider>
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(useProjectStore.getState().currentProjectId).toBe('project-a')
    })

    await act(async () => {
      useProjectStore.setState({
        currentOrgId: null,
        currentProjectId: null,
        currentProject: null,
        organizations: [],
        projects: [],
      })
      setMockSessionUser(null)
      rerender(
        <QueryClientProvider client={queryClient}>
          <ProjectProvider>
            <div>ready</div>
          </ProjectProvider>
        </QueryClientProvider>,
      )
      await wait(0)
      setMockSessionUser(user('user-b'))
      rerender(
        <QueryClientProvider client={queryClient}>
          <ProjectProvider>
            <div>ready</div>
          </ProjectProvider>
        </QueryClientProvider>,
      )
      await wait(20)
    })

    await waitFor(() => {
      expect(useProjectStore.getState().currentOrgId).toBe('org-b')
      expect(useProjectStore.getState().currentProjectId).toBe('project-b')
    })
    expect(managedGetMock).toHaveBeenCalledTimes(2)
    expect(managedGetMock.mock.calls[0][0]).toBe('/auth/me')
    expect(managedGetMock.mock.calls[1][0]).toBe('/auth/me')
  })

  it('does not let a stale auth-me response overwrite a newer managed context', async () => {
    const initialAuthMe = deferred<ReturnType<typeof authMe>>()
    managedGetMock.mockReturnValue(initialAuthMe.promise)
    setMockSessionUser(user('user-a'))
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    render(
      <QueryClientProvider client={queryClient}>
        <ProjectProvider>
          <div>ready</div>
        </ProjectProvider>
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(managedGetMock).toHaveBeenCalledWith('/auth/me')
    })

    await act(async () => {
      useProjectStore.setState({
        currentOrgId: 'org-b',
        currentProjectId: 'project-b',
        organizations: [{ id: 'org-b', name: 'org-b', slug: 'org-b', role: 'owner' }],
        projects: [{ id: 'project-b', name: 'project-b', slug: 'project-b', is_default: true }],
      })
      await Promise.resolve()
    })

    await act(async () => {
      initialAuthMe.resolve(authMe('user-a', 'org-a', 'project-a'))
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(queryClient.getQueryData(['auth-me', 'user-a'])).toBeTruthy()
    })

    expect(useProjectStore.getState().currentOrgId).toBe('org-b')
    expect(useProjectStore.getState().currentProjectId).toBe('project-b')
  })

  it('preserves archived current project metadata even when active project list excludes it', async () => {
    const archivedProject = {
      id: 'project-archived',
      name: 'Archived Project',
      slug: 'archived-project',
      is_default: false,
      archived_at: '2026-01-02T00:00:00Z',
    }
    managedGetMock.mockResolvedValueOnce(authMeWithProject('user-a', 'org-a', archivedProject, []))
    setMockSessionUser(user('user-a'))
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    render(
      <QueryClientProvider client={queryClient}>
        <ProjectProvider>
          <div>ready</div>
        </ProjectProvider>
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(useProjectStore.getState().currentProjectId).toBe('project-archived')
    })
    expect(useProjectStore.getState().currentProject?.archived_at).toBe('2026-01-02T00:00:00Z')
    expect(useProjectStore.getState().projects).toEqual([])
  })
})
