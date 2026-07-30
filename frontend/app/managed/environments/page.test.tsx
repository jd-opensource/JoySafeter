import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(''),
}))

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({ t: (key: string, fallback?: string) => fallback ?? key }),
}))

vi.mock('@/lib/api-client', () => ({
  managedGet: vi.fn(),
  managedPost: vi.fn(),
}))

vi.mock('@/lib/managed/errors', () => ({
  toastOperationError: vi.fn(),
}))

vi.mock('@/lib/managed/filters', () => ({
  createCreatedTimeFilter: () => ({ id: 'created', label: 'created', options: [] }),
  filterByCreatedTime: () => true,
  matchesSearch: () => true,
}))

vi.mock('@/components/managed/shared', () => ({
  AdvancedSection: ({ children }: { children: ReactNode }) => <section>{children}</section>,
  DataTable: ({
    actionMenu,
    data,
  }: {
    actionMenu?: (row: EnvironmentRecord) => { label: string; onClick: () => void }[]
    data: EnvironmentRecord[]
  }) => (
    <div>
      {data.map((environment) => (
        <div key={environment.id}>
          <span>{environment.name}</span>
          {actionMenu?.(environment).map((item) => (
            <button key={item.label} onClick={item.onClick}>
              {environment.id}:{item.label}
            </button>
          ))}
        </div>
      ))}
    </div>
  ),
  FilterBar: () => null,
  FormActionBar: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  FormFieldError: ({ message }: { message?: string }) => (message ? <p>{message}</p> : null),
  FormFieldLabel: ({ children }: { children: ReactNode }) => <label>{children}</label>,
  FormSectionCard: ({ children }: { children: ReactNode }) => <section>{children}</section>,
  MonoId: ({ id }: { id: string }) => <span>{id}</span>,
  PageHeader: ({ title, action }: { title: string; action?: ReactNode }) => (
    <div>
      <h1>{title}</h1>
      {action}
    </div>
  ),
  RelativeTime: ({ date }: { date: string }) => <span>{date}</span>,
  ResourceErrorState: () => null,
  StatusBadge: ({ status }: { status: string }) => <span>{status}</span>,
}))

vi.mock('@/components/ui/button', () => ({
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

vi.mock('@/components/ui/dialog', () => ({
  Dialog: ({
    children,
    onOpenChange,
    open,
  }: {
    children: ReactNode
    onOpenChange?: (open: boolean) => void
    open: boolean
  }) =>
    open ? (
      <div>
        {children}
        <button onClick={() => onOpenChange?.(false)}>dialog-close</button>
      </div>
    ) : null,
  DialogContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogDescription: ({ children }: { children: ReactNode }) => <p>{children}</p>,
  DialogFooter: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogHeader: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children: ReactNode }) => <h2>{children}</h2>,
}))

vi.mock('@/components/ui/input', () => ({
  Input: ({
    autoFocus: _autoFocus,
    onChange,
    ...props
  }: React.InputHTMLAttributes<HTMLInputElement>) => (
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

import EnvironmentListPage from './page'

const managedPostMock = managedPost as unknown as ReturnType<typeof vi.fn>
const managedGetMock = managedGet as unknown as ReturnType<typeof vi.fn>

function managedOptions(projectId = 'project-a') {
  return {
    headers: {
      'X-Org-Id': 'org-a',
      'X-Project-Id': projectId,
    },
    skipManagedContext: true,
  }
}

interface EnvironmentRecord {
  id: string
  name: string
  description?: string | null
  config?: Record<string, unknown>
  archived_at?: string | null
  created_at: string
}

function environment(id: string, name: string): EnvironmentRecord {
  return {
    id,
    name,
    description: null,
    config: { type: 'cloud' },
    archived_at: null,
    created_at: '2026-01-01T00:00:00Z',
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

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

describe('EnvironmentListPage create lifecycle', () => {
  beforeEach(() => {
    managedGetMock.mockReset()
    managedPostMock.mockReset()
    managedGetMock.mockResolvedValue({ data: [], has_more: false })
    managedPostMock.mockResolvedValue({})
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

  it('hides project write actions when the current project is archived', async () => {
    managedGetMock.mockResolvedValue({ data: [environment('env-a', 'Env A')], has_more: false })
    useProjectStore.setState({
      currentOrgId: 'org-a',
      currentProjectId: 'project-archived',
      currentProject: {
        id: 'project-archived',
        org_id: 'org-a',
        name: 'Archived Project',
        slug: 'project-archived',
        is_default: false,
        archived_at: '2026-01-02T00:00:00Z',
      },
      organizations: [],
      projects: [],
    })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText, queryByText } = render(
      <QueryClientProvider client={queryClient}>
        <EnvironmentListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Env A')).toBeTruthy()
    })

    expect(queryByText('managed.environments.add')).toBeNull()
    expect(queryByText('env-a:managed.environments.archiveEnv')).toBeNull()
  })

  it('does not submit a create draft after the managed project changes', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getAllByRole, getAllByText, getByPlaceholderText, queryByPlaceholderText, rerender } =
      render(
        <QueryClientProvider client={queryClient}>
          <EnvironmentListPage />
        </QueryClientProvider>,
      )

    await waitFor(() => {
      expect(managedGetMock).toHaveBeenCalled()
    })

    await act(async () => {
      fireEvent.click(getAllByText('managed.environments.add')[0])
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('managed.environments.namePlaceholder'), {
        target: { value: 'Project A Environment' },
      })
    })

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      rerender(
        <QueryClientProvider client={queryClient}>
          <EnvironmentListPage />
        </QueryClientProvider>,
      )
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(queryByPlaceholderText('managed.environments.namePlaceholder')).toBeNull()
    })

    const addButtons = getAllByRole('button', { name: /managed\.environments\.add/ })
    if (addButtons.length > 1) {
      await act(async () => {
        fireEvent.click(addButtons[addButtons.length - 1])
      })
    }

    expect(managedPostMock).not.toHaveBeenCalled()
  })

  it('does not create an environment from old dialog state in the same turn as a project switch', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getAllByText, getByPlaceholderText } = render(
      <QueryClientProvider client={queryClient}>
        <EnvironmentListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(managedGetMock).toHaveBeenCalled()
    })

    await act(async () => {
      fireEvent.click(getAllByText('managed.environments.add')[0])
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('managed.environments.namePlaceholder'), {
        target: { value: 'Project A Environment' },
      })
      fireEvent.input(getByPlaceholderText('managed.environments.descPlaceholder'), {
        target: { value: 'Only for project A' },
      })
      fireEvent.input(getByPlaceholderText(/api\.example\.com/), {
        target: { value: 'api.project-a.example.com, github.com' },
      })
      fireEvent.input(getByPlaceholderText('curl, git, build-essential'), {
        target: { value: 'curl, git' },
      })
      fireEvent.input(getByPlaceholderText('numpy, pandas, requests'), {
        target: { value: 'requests' },
      })
      fireEvent.input(getByPlaceholderText('KEY=value, NODE_ENV=production'), {
        target: { value: 'PROJECT=project-a' },
      })
    })

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      fireEvent.click(getAllByText('managed.environments.add').at(-1)!)
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith(
      '/environments',
      expect.anything(),
      managedOptions(),
    )
  })

  it('does not create an environment from old dialog state after the current project is archived', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getAllByText, getByPlaceholderText } = render(
      <QueryClientProvider client={queryClient}>
        <EnvironmentListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(managedGetMock).toHaveBeenCalled()
    })

    await act(async () => {
      fireEvent.click(getAllByText('managed.environments.add')[0])
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('managed.environments.namePlaceholder'), {
        target: { value: 'Archived Project Environment' },
      })
      fireEvent.input(getByPlaceholderText('managed.environments.descPlaceholder'), {
        target: { value: 'Only for project A before archive' },
      })
      fireEvent.input(getByPlaceholderText(/api\.example\.com/), {
        target: { value: 'api.project-a.example.com, github.com' },
      })
      fireEvent.input(getByPlaceholderText('curl, git, build-essential'), {
        target: { value: 'curl, git' },
      })
      fireEvent.input(getByPlaceholderText('numpy, pandas, requests'), {
        target: { value: 'requests' },
      })
      fireEvent.input(getByPlaceholderText('KEY=value, NODE_ENV=production'), {
        target: { value: 'PROJECT=project-a' },
      })
    })

    await act(async () => {
      useProjectStore.setState({
        currentProject: projectInfo('2026-01-02T00:00:00Z'),
      })
      fireEvent.click(getAllByText('managed.environments.add').at(-1)!)
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith(
      '/environments',
      expect.anything(),
      managedOptions(),
    )
  })

  it('does not close a new create dialog when an older create finishes', async () => {
    const create = deferred<Record<string, unknown>>()
    managedPostMock.mockReturnValueOnce(create.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getAllByText, getByDisplayValue, getByPlaceholderText, queryByDisplayValue } = render(
      <QueryClientProvider client={queryClient}>
        <EnvironmentListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(managedGetMock).toHaveBeenCalled()
    })

    await act(async () => {
      fireEvent.click(getAllByText('managed.environments.add')[0])
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('managed.environments.namePlaceholder'), {
        target: { value: 'First Environment' },
      })
    })

    await act(async () => {
      fireEvent.click(getAllByText('managed.environments.add').at(-1)!)
      await Promise.resolve()
    })

    expect(managedPostMock).toHaveBeenCalledWith(
      '/environments',
      {
        name: 'First Environment',
        description: '',
        config: {
          type: 'cloud',
          networking: {
            type: 'limited',
          },
        },
      },
      managedOptions(),
    )

    await act(async () => {
      fireEvent.click(getAllByText('dialog-close')[0])
    })

    await act(async () => {
      fireEvent.click(getAllByText('managed.environments.add')[0])
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('managed.environments.namePlaceholder'), {
        target: { value: 'Second Environment' },
      })
    })

    expect(getByDisplayValue('Second Environment')).toBeTruthy()

    await act(async () => {
      create.resolve({})
      await create.promise
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(queryByDisplayValue('Second Environment')).toBeTruthy()
    })
  })

  it('does not invalidate environments from a create completion after the page unmounts', async () => {
    const create = deferred<Record<string, unknown>>()
    managedPostMock.mockReturnValueOnce(create.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    const { getAllByText, getByPlaceholderText, unmount } = render(
      <QueryClientProvider client={queryClient}>
        <EnvironmentListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(managedGetMock).toHaveBeenCalled()
    })

    await act(async () => {
      fireEvent.click(getAllByText('managed.environments.add')[0])
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('managed.environments.namePlaceholder'), {
        target: { value: 'Unmounted Environment' },
      })
    })

    await act(async () => {
      fireEvent.click(getAllByText('managed.environments.add').at(-1)!)
      await Promise.resolve()
    })

    unmount()

    await act(async () => {
      create.resolve({})
      await Promise.resolve()
    })

    expect(invalidateSpy).not.toHaveBeenCalledWith({
      queryKey: ['environments', 'org-a:project-a'],
    })
  })

  it('does not invalidate environments from a create completion after the current project is archived', async () => {
    const create = deferred<Record<string, unknown>>()
    managedPostMock.mockReturnValueOnce(create.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    const { getAllByText, getByPlaceholderText } = render(
      <QueryClientProvider client={queryClient}>
        <EnvironmentListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(managedGetMock).toHaveBeenCalled()
    })

    await act(async () => {
      fireEvent.click(getAllByText('managed.environments.add')[0])
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('managed.environments.namePlaceholder'), {
        target: { value: 'Archived Completion Environment' },
      })
    })

    await act(async () => {
      fireEvent.click(getAllByText('managed.environments.add').at(-1)!)
      await Promise.resolve()
    })

    await act(async () => {
      useProjectStore.setState({
        currentProject: projectInfo('2026-01-02T00:00:00Z'),
      })
      create.resolve({})
      await Promise.resolve()
    })

    expect(invalidateSpy).not.toHaveBeenCalledWith({
      queryKey: ['environments', 'org-a:project-a'],
    })
  })

  it('does not invalidate environments from an archive completion after the page unmounts', async () => {
    const archive = deferred<Record<string, unknown>>()
    managedGetMock.mockResolvedValue({
      data: [environment('env-a', 'Env A')],
      has_more: false,
    })
    managedPostMock.mockReturnValueOnce(archive.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    const { getByText, unmount } = render(
      <QueryClientProvider client={queryClient}>
        <EnvironmentListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Env A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('env-a:managed.environments.archiveEnv'))
      await Promise.resolve()
    })

    unmount()

    await act(async () => {
      archive.resolve({})
      await Promise.resolve()
    })

    expect(invalidateSpy).not.toHaveBeenCalledWith({
      queryKey: ['environments', 'org-a:project-a'],
    })
  })

  it('does not archive an environment from an old row action after the current project is archived', async () => {
    managedGetMock.mockResolvedValue({
      data: [environment('env-a', 'Env A')],
      has_more: false,
    })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText } = render(
      <QueryClientProvider client={queryClient}>
        <EnvironmentListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Env A')).toBeTruthy()
    })

    const oldArchiveButton = getByText('env-a:managed.environments.archiveEnv')

    await act(async () => {
      useProjectStore.setState({
        currentProject: projectInfo('2026-01-02T00:00:00Z'),
      })
      fireEvent.click(oldArchiveButton)
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith(
      '/environments/env-a/archive',
      {},
      managedOptions(),
    )
  })

  it('does not invalidate environments from an archive completion after the current project is archived', async () => {
    const archive = deferred<Record<string, unknown>>()
    managedGetMock.mockResolvedValue({
      data: [environment('env-a', 'Env A')],
      has_more: false,
    })
    managedPostMock.mockReturnValueOnce(archive.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    const { getByText } = render(
      <QueryClientProvider client={queryClient}>
        <EnvironmentListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Env A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('env-a:managed.environments.archiveEnv'))
      await Promise.resolve()
    })

    await act(async () => {
      useProjectStore.setState({
        currentProject: projectInfo('2026-01-02T00:00:00Z'),
      })
      archive.resolve({})
      await Promise.resolve()
    })

    expect(invalidateSpy).not.toHaveBeenCalledWith({
      queryKey: ['environments', 'org-a:project-a'],
    })
  })

  it('does not archive an environment target that leaves the current environments list', async () => {
    managedGetMock.mockResolvedValue({
      data: [environment('env-a', 'Env A')],
      has_more: false,
    })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText } = render(
      <QueryClientProvider client={queryClient}>
        <EnvironmentListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Env A')).toBeTruthy()
    })

    await act(async () => {
      queryClient.setQueryData(
        ['environments', 'org-a:project-a', '/environments', undefined, false, 10],
        {
          data: [environment('env-b', 'Env B')],
          has_more: false,
        },
      )
      fireEvent.click(getByText('env-a:managed.environments.archiveEnv'))
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith(
      '/environments/env-a/archive',
      {},
      managedOptions(),
    )
  })
})
