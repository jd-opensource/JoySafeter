import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({ t: (key: string, _params?: unknown) => key }),
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
  DataTable: ({
    actionMenu,
    data,
  }: {
    actionMenu?: (row: SessionRecord) => { label: string; onClick: () => void }[]
    data: SessionRecord[]
  }) => (
    <div>
      {data.map((session) => (
        <div key={session.id}>
          <span>{session.title}</span>
          {actionMenu?.(session).map((item) => (
            <button key={item.label} onClick={item.onClick}>
              {session.id}:{item.label}
            </button>
          ))}
        </div>
      ))}
    </div>
  ),
  FieldHelp: () => null,
  FilterBar: () => null,
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

vi.mock('@/components/ui/dialog', () => ({
  Dialog: ({ children, open }: { children: ReactNode; open: boolean }) =>
    open ? <div>{children}</div> : null,
  DialogContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogDescription: ({ children }: { children: ReactNode }) => <p>{children}</p>,
  DialogFooter: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogHeader: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children: ReactNode }) => <h2>{children}</h2>,
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
  SelectGroup: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectItem: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectLabel: ({ children }: { children: ReactNode }) => <div>{children}</div>,
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

import SessionListPage from './page'

interface SessionRecord {
  id: string
  title: string
  status: string
  archived_at?: string | null
  agent?: {
    id: string
    name: string
    engine_kind?: string | null
  } | null
  created_at: string
}

const managedGetMock = managedGet as unknown as ReturnType<typeof vi.fn>
const managedPostMock = managedPost as unknown as ReturnType<typeof vi.fn>

function session(id: string, title: string): SessionRecord {
  return {
    id,
    title,
    status: 'active',
    archived_at: null,
    agent: { id: 'agent-a', name: 'Agent A', engine_kind: 'claude' },
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

function managedOptions(projectId = 'project-a') {
  return {
    headers: {
      'X-Org-Id': 'org-a',
      'X-Project-Id': projectId,
    },
    skipManagedContext: true,
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

describe('SessionListPage object lifecycle', () => {
  beforeEach(() => {
    managedGetMock.mockReset()
    managedPostMock.mockReset()
    managedGetMock.mockResolvedValue({
      data: [session('session-a', 'Session A')],
      has_more: false,
    })
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
    useProjectStore.setState({
      currentProject: projectInfo('2026-01-02T00:00:00Z'),
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
        <SessionListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Session A')).toBeTruthy()
    })

    expect(queryByText('managed.sessions.new')).toBeNull()
    expect(queryByText('session-a:managed.sessions.archiveSession')).toBeNull()
  })

  it('does not archive a session from an old row action in the same turn as a project switch', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText } = render(
      <QueryClientProvider client={queryClient}>
        <SessionListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Session A')).toBeTruthy()
    })

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      fireEvent.click(getByText('session-a:managed.sessions.archiveSession'))
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalled()
  })

  it('does not archive a session from an old row action after the current project is archived', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText } = render(
      <QueryClientProvider client={queryClient}>
        <SessionListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Session A')).toBeTruthy()
    })

    const oldArchiveButton = getByText('session-a:managed.sessions.archiveSession')

    await act(async () => {
      useProjectStore.setState({
        currentProject: projectInfo('2026-01-02T00:00:00Z'),
      })
      fireEvent.click(oldArchiveButton)
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalled()
  })

  it('does not invalidate sessions from an archive completion after the page unmounts', async () => {
    const archive = deferred<Record<string, never>>()
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
        <SessionListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Session A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('session-a:managed.sessions.archiveSession'))
      await Promise.resolve()
    })

    expect(managedPostMock).toHaveBeenCalledWith(
      '/sessions/session-a/archive',
      {},
      managedOptions(),
    )

    unmount()

    await act(async () => {
      archive.resolve({})
      await Promise.resolve()
    })

    expect(invalidateSpy).not.toHaveBeenCalledWith({ queryKey: ['sessions', 'org-a:project-a'] })
  })

  it('does not invalidate sessions from an archive completion after the current project is archived', async () => {
    const archive = deferred<Record<string, never>>()
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
        <SessionListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Session A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('session-a:managed.sessions.archiveSession'))
      await Promise.resolve()
    })

    expect(managedPostMock).toHaveBeenCalledWith(
      '/sessions/session-a/archive',
      {},
      managedOptions(),
    )

    await act(async () => {
      useProjectStore.setState({
        currentProject: projectInfo('2026-01-02T00:00:00Z'),
      })
      archive.resolve({})
      await Promise.resolve()
    })

    expect(invalidateSpy).not.toHaveBeenCalledWith({ queryKey: ['sessions', 'org-a:project-a'] })
  })

  it('does not archive a session target that is no longer in the current sessions list', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText } = render(
      <QueryClientProvider client={queryClient}>
        <SessionListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Session A')).toBeTruthy()
    })

    await act(async () => {
      queryClient.setQueryData(['sessions', 'org-a:project-a', '/sessions', undefined, false, 10], {
        data: [session('session-b', 'Session B')],
        has_more: false,
      })
      fireEvent.click(getByText('session-a:managed.sessions.archiveSession'))
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalled()
  })
})
