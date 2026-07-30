import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const pushMock = vi.fn()

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: pushMock }),
}))

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({ t: (key: string, _params?: unknown) => key }),
}))

vi.mock('@/lib/api-client', () => ({
  managedGet: vi.fn(),
  managedPost: vi.fn(),
}))

vi.mock('@/lib/managed/errors', () => ({
  shouldRetryManagedResourceError: vi.fn(() => false),
  toastOperationError: vi.fn(),
}))

vi.mock('@/components/managed/shared', () => ({
  AdvancedSection: ({ children }: { children: ReactNode }) => <section>{children}</section>,
  FormActionBar: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  MonoId: ({ id }: { id: string }) => <span>{id}</span>,
  PageHeader: ({ action, title }: { action?: ReactNode; title: string }) => (
    <div>
      <h1>{title}</h1>
      {action}
    </div>
  ),
  FormFieldLabel: ({ children }: { children: ReactNode }) => <label>{children}</label>,
  FormSectionCard: ({ children }: { children: ReactNode }) => <section>{children}</section>,
  RelativeTime: ({ date }: { date: string }) => <span>{date}</span>,
  ResourceErrorState: () => null,
  StatusBadge: ({ status }: { status: string }) => <span>{status}</span>,
}))

vi.mock('@/components/ui/button', () => ({
  buttonVariants: () => '',
  Button: ({
    children,
    disabled,
    onClick,
    type = 'button',
  }: {
    children: ReactNode
    disabled?: boolean
    onClick?: () => void
    type?: 'button' | 'submit' | 'reset'
  }) => (
    <button type={type} disabled={disabled} onClick={onClick}>
      {children}
    </button>
  ),
}))

vi.mock('@/components/ui/input', () => ({
  Input: ({ onChange, ...props }: React.InputHTMLAttributes<HTMLInputElement>) => (
    <input
      {...props}
      onChange={onChange}
      onInput={onChange as React.FormEventHandler<HTMLInputElement>}
    />
  ),
}))

vi.mock('@/components/ui/select', () => ({
  Select: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectItem: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectTrigger: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectValue: () => null,
}))

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement
globalThis.localStorage = dom.window.localStorage

import { managedGet, managedPost } from '@/lib/api-client'
import { useProjectStore } from '@/stores/managed/project-store'

import EnvironmentDetailPage from './page'

const managedGetMock = managedGet as unknown as ReturnType<typeof vi.fn>
const managedPostMock = managedPost as unknown as ReturnType<typeof vi.fn>

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

function environment(
  id: string,
  name: string,
  overrides: Partial<{ archived_at: string | null }> = {},
) {
  return {
    id,
    name,
    description: '',
    config: { networking: { type: 'limited' } },
    archived_at: null,
    created_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

function projectInfo(archivedAt: string | null = null) {
  return {
    id: 'project-a',
    org_id: 'org-a',
    name: 'Project A',
    slug: 'project-a',
    is_default: true,
    archived_at: archivedAt,
  }
}

function managedOptions(projectId = 'project-a') {
  return {
    headers: {
      'X-Org-Id': 'org-a',
      'X-Project-Id': projectId,
    },
    skipManagedContext: true,
  }
}

function renderEnvironmentPage(queryClient: QueryClient, envId: string) {
  const params = {
    status: 'fulfilled',
    value: { envId },
    then: () => undefined,
  } as unknown as Promise<{ envId: string }>

  return (
    <QueryClientProvider client={queryClient}>
      <EnvironmentDetailPage params={params} />
    </QueryClientProvider>
  )
}

describe('EnvironmentDetailPage save lifecycle', () => {
  beforeEach(() => {
    pushMock.mockReset()
    managedGetMock.mockReset()
    managedPostMock.mockReset()
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/environments/env-a') return environment('env-a', 'Env A')
      if (path === '/environments/env-b') return environment('env-b', 'Env B')
      return { data: [] }
    })
    managedPostMock.mockResolvedValue(environment('env-a', 'Env A'))
    useProjectStore.setState({
      currentOrgId: 'org-a',
      currentProjectId: 'project-a',
      currentProject: projectInfo(null),
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

  it('refetches the environment after the managed project changes', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText } = render(renderEnvironmentPage(queryClient, 'env-a'))

    await waitFor(() => {
      expect(getByText('Env A')).toBeTruthy()
      expect(managedGetMock).toHaveBeenCalledWith('/environments/env-a', managedOptions())
    })
    expect(
      managedGetMock.mock.calls.filter(([path]) => path === '/environments/env-a'),
    ).toHaveLength(1)

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(
        managedGetMock.mock.calls.filter(([path]) => path === '/environments/env-a'),
      ).toHaveLength(2)
      expect(managedGetMock).toHaveBeenCalledWith(
        '/environments/env-a',
        managedOptions('project-b'),
      )
    })
  })

  it('does not navigate from a save completion after the managed project changes', async () => {
    const save = deferred<unknown>()
    managedPostMock.mockReturnValueOnce(save.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText } = render(renderEnvironmentPage(queryClient, 'env-a'))

    await waitFor(() => {
      expect(getByText('Env A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('managed.environments.save'))
      await Promise.resolve()
    })

    expect(managedPostMock).toHaveBeenCalledWith(
      '/environments/env-a',
      expect.anything(),
      managedOptions(),
    )

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      save.resolve(environment('env-a', 'Env A'))
      await save.promise
      await Promise.resolve()
      await new Promise((resolve) => setTimeout(resolve, 0))
    })

    expect(pushMock).not.toHaveBeenCalledWith('/managed/environments')
  })

  it('does not save an old environment draft to a new project that has the same environment id', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const view = render(renderEnvironmentPage(queryClient, 'env-a'))

    await waitFor(() => {
      expect(view.getByDisplayValue('Env A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.input(view.getByDisplayValue('Env A'), {
        target: { value: 'Old Project Env Draft' },
      })
    })

    queryClient.setQueryData(
      ['environment', 'org-a:project-b', 'env-a'],
      environment('env-a', 'Project B Env'),
    )
    const saveButton = view.getByText('managed.environments.save')

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      fireEvent.click(saveButton)
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalled()
  })

  it('does not overwrite an unsaved environment draft when refreshed environment data arrives', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const view = render(renderEnvironmentPage(queryClient, 'env-a'))

    await waitFor(() => {
      expect(view.getByDisplayValue('Env A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.input(view.getByDisplayValue('Env A'), {
        target: { value: 'Local Env Draft' },
      })
    })

    await act(async () => {
      queryClient.setQueryData(
        ['environment', 'org-a:project-a', 'env-a'],
        environment('env-a', 'Env A Refresh'),
      )
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(queryClient.getQueryData(['environment', 'org-a:project-a', 'env-a'])).toMatchObject({
        name: 'Env A Refresh',
      })
    })

    expect(view.getByDisplayValue('Local Env Draft')).toBeTruthy()
    expect(view.queryByDisplayValue('Env A Refresh')).toBeNull()
  })

  it('does not save after the current environment detail becomes archived', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const view = render(renderEnvironmentPage(queryClient, 'env-a'))

    await waitFor(() => {
      expect(view.getByText('Env A')).toBeTruthy()
    })

    await act(async () => {
      queryClient.setQueryData(
        ['environment', 'org-a:project-a', 'env-a'],
        environment('env-a', 'Env A', { archived_at: '2026-01-02T00:00:00Z' }),
      )
      fireEvent.click(view.getByText('managed.environments.save'))
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalled()
  })

  it('does not save after the current project is archived', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const view = render(renderEnvironmentPage(queryClient, 'env-a'))

    await waitFor(() => {
      expect(view.getByText('Env A')).toBeTruthy()
    })

    const saveButton = view.getByText('managed.environments.save')

    await act(async () => {
      useProjectStore.setState({ currentProject: projectInfo('2026-01-02T00:00:00Z') })
      fireEvent.click(saveButton)
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalled()
    expect(view.queryByText('managed.environments.save')).toBeNull()
    expect(view.getByText('managed.errors.projectArchived')).toBeTruthy()
  })

  it('does not navigate from a save completion after the page unmounts', async () => {
    const save = deferred<unknown>()
    managedPostMock.mockReturnValueOnce(save.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const view = render(renderEnvironmentPage(queryClient, 'env-a'))

    await waitFor(() => {
      expect(view.getByText('Env A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(view.getByText('managed.environments.save'))
      await Promise.resolve()
    })

    expect(managedPostMock).toHaveBeenCalledWith(
      '/environments/env-a',
      expect.anything(),
      managedOptions(),
    )

    view.unmount()

    await act(async () => {
      save.resolve(environment('env-a', 'Env A'))
      await save.promise
      await Promise.resolve()
      await new Promise((resolve) => setTimeout(resolve, 0))
    })

    expect(pushMock).not.toHaveBeenCalledWith('/managed/environments')
  })
})
