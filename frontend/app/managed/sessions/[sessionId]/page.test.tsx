import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

vi.mock('@/lib/i18n', () => ({
  i18n: { language: 'en' },
  useTranslation: () => ({ t: (key: string, _params?: unknown) => key }),
}))

vi.mock('@/lib/api-client', () => ({
  extractErrorFromResponse: vi.fn(async () => new Error('mock api error')),
  managedDelete: vi.fn(),
  managedGet: vi.fn(),
  managedPatch: vi.fn(),
  managedPost: vi.fn(),
}))

vi.mock('@/lib/managed/errors', () => ({
  shouldRetryManagedResourceError: vi.fn(() => false),
  toastOperationError: vi.fn(),
}))

vi.mock('@/lib/managed/sse', () => ({
  useSessionStream: () => ({ events: [], connected: false }),
}))

vi.mock('@/components/managed/session', () => ({
  EventDetail: () => null,
  EventFilter: () => null,
  EventList: ({ events }: { events: Array<{ content?: unknown; id?: string }> }) => (
    <div data-testid="event-list">
      {events.map((event) => (
        <div key={event.id}>{JSON.stringify(event.content)}</div>
      ))}
    </div>
  ),
  EventTimeline: () => null,
}))

vi.mock('@/components/managed/shared', () => ({
  MonoId: ({ id }: { id: string }) => <span>{id}</span>,
  PageHeader: ({ action, title }: { action?: ReactNode; title: string }) => (
    <div>
      <h1>{title}</h1>
      {action}
    </div>
  ),
  RelativeTime: ({ date }: { date: string }) => <span>{date}</span>,
  ResourceErrorState: () => null,
  StatusBadge: ({ status }: { status: string }) => <span>{status}</span>,
}))

vi.mock('@/components/ui/badge', () => ({
  Badge: ({ children }: { children: ReactNode }) => <span>{children}</span>,
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

vi.mock('@/components/ui/dropdown-menu', () => ({
  DropdownMenu: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DropdownMenuContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DropdownMenuItem: ({
    children,
    disabled,
    onSelect,
  }: {
    children: ReactNode
    disabled?: boolean
    onSelect?: () => void
  }) => (
    <button disabled={disabled} onClick={onSelect}>
      {children}
    </button>
  ),
  DropdownMenuSeparator: () => null,
  DropdownMenuTrigger: ({ children }: { children: ReactNode }) => <div>{children}</div>,
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

vi.mock('@/components/ui/tabs', () => ({
  Tabs: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  TabsContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  TabsList: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  TabsTrigger: ({ children }: { children: ReactNode }) => <button>{children}</button>,
}))

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement
globalThis.localStorage = dom.window.localStorage
globalThis.navigator.clipboard = {
  writeText: vi.fn(),
} as unknown as Clipboard

import { managedDelete, managedGet, managedPatch, managedPost } from '@/lib/api-client'
import { useProjectStore } from '@/stores/managed/project-store'

import SessionDetailPage from './page'

const managedGetMock = managedGet as unknown as ReturnType<typeof vi.fn>
const managedDeleteMock = managedDelete as unknown as ReturnType<typeof vi.fn>
const managedPatchMock = managedPatch as unknown as ReturnType<typeof vi.fn>
const managedPostMock = managedPost as unknown as ReturnType<typeof vi.fn>

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

function session(
  id: string,
  overrides: Partial<{
    archived_at: string | null
    status: string
  }> = {},
) {
  return {
    id,
    title: id,
    status: 'idle',
    archived_at: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    stats: {},
    usage: { input_tokens: 0, output_tokens: 0 },
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

function event(id: string, text: string) {
  return {
    id,
    seq: 1,
    type: 'user.message',
    content: [{ type: 'text', text }],
    created_at: '2026-01-01T00:00:01Z',
  }
}

function renderSessionPage(queryClient: QueryClient, sessionId: string) {
  const params = {
    status: 'fulfilled',
    value: { sessionId },
    then: () => undefined,
  } as unknown as Promise<{ sessionId: string }>

  return (
    <QueryClientProvider client={queryClient}>
      <SessionDetailPage params={params} />
    </QueryClientProvider>
  )
}

describe('SessionDetailPage route lifecycle', () => {
  beforeEach(() => {
    managedDeleteMock.mockReset()
    managedGetMock.mockReset()
    managedPatchMock.mockReset()
    managedPostMock.mockReset()
    managedDeleteMock.mockResolvedValue({})
    managedPatchMock.mockResolvedValue({})
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

  it('does not display a previous session event response after the route session changes', async () => {
    const sessionAEvents = deferred<{ data: ReturnType<typeof event>[]; has_more: boolean }>()
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/sessions/session-a') return session('session-a')
      if (path === '/sessions/session-b') return session('session-b')
      if (path === '/sessions/session-a/resources') return { data: [] }
      if (path === '/sessions/session-b/resources') return { data: [] }
      if (path.startsWith('/sessions/session-a/events?')) return sessionAEvents.promise
      if (path.startsWith('/sessions/session-b/events?')) {
        return { data: [event('event-b', 'from session b')], has_more: false }
      }
      return { data: [] }
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByTestId, rerender } = render(renderSessionPage(queryClient, 'session-a'))

    await waitFor(() => {
      expect(managedGetMock).toHaveBeenCalledWith('/sessions/session-a', managedOptions())
    })

    await act(async () => {
      rerender(renderSessionPage(queryClient, 'session-b'))
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(managedGetMock).toHaveBeenCalledWith('/sessions/session-b', managedOptions())
    })

    await act(async () => {
      sessionAEvents.resolve({ data: [event('event-a', 'from session a')], has_more: false })
      await sessionAEvents.promise
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(getByTestId('event-list').textContent).toContain('from session b')
    })
    expect(getByTestId('event-list').textContent).not.toContain('from session a')
  })

  it('does not invalidate from an archive completion after the route session changes', async () => {
    const archive = deferred<void>()
    managedPostMock.mockReturnValueOnce(archive.promise)
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/sessions/session-a') return session('session-a')
      if (path === '/sessions/session-b') return session('session-b')
      if (path.endsWith('/resources')) return { data: [] }
      if (path.includes('/events?')) return { data: [], has_more: false }
      return { data: [] }
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    const { getByText, rerender } = render(renderSessionPage(queryClient, 'session-a'))

    await waitFor(() => {
      expect(getByText('managed.sessions.archive')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('managed.sessions.archive'))
      await Promise.resolve()
    })

    expect(managedPostMock).toHaveBeenCalledWith(
      '/sessions/session-a/archive',
      {},
      managedOptions(),
    )

    await act(async () => {
      rerender(renderSessionPage(queryClient, 'session-b'))
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(managedGetMock).toHaveBeenCalledWith('/sessions/session-b', managedOptions())
    })

    await act(async () => {
      archive.resolve()
      await archive.promise
      await Promise.resolve()
    })

    expect(invalidateSpy).not.toHaveBeenCalledWith({
      queryKey: ['session', 'session-b:org-a:project-a'],
    })
  })

  it('does not send a message after the current session detail becomes archived', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/sessions/session-a') return session('session-a')
      if (path === '/sessions/session-a/resources') {
        return {
          data: [
            {
              id: 'session_resource_mounted',
              type: 'file',
              file_id: 'file_mounted',
              mount_path: '/workspace/mounted.txt',
              access: 'read',
              created_at: '2026-01-01T00:00:00Z',
            },
          ],
        }
      }
      if (path.includes('/events?')) return { data: [], has_more: false }
      return { data: [] }
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByPlaceholderText } = render(renderSessionPage(queryClient, 'session-a'))

    const input = await waitFor(() => getByPlaceholderText('managed.sessions.sendPlaceholder'))
    const sendButton = input.parentElement?.querySelector('button') as HTMLButtonElement
    expect(sendButton).toBeTruthy()

    await act(async () => {
      fireEvent.input(input, { target: { value: 'stale message' } })
      await Promise.resolve()
    })

    await act(async () => {
      queryClient.setQueryData(['session', 'session-a:org-a:project-a'], {
        ...session('session-a'),
        archived_at: '2026-01-02T00:00:00Z',
      })
      fireEvent.click(sendButton)
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith(
      '/sessions/session-a/events',
      {
        events: [{ type: 'user.message', content: [{ type: 'text', text: 'stale message' }] }],
      },
      expect.objectContaining({
        headers: expect.objectContaining(managedOptions().headers),
        skipManagedContext: true,
      }),
    )
  })

  it('does not send a message from old session UI after the current project is archived', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/sessions/session-a') return session('session-a')
      if (path === '/sessions/session-a/resources') return { data: [] }
      if (path.includes('/events?')) return { data: [], has_more: false }
      return { data: [] }
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByPlaceholderText } = render(renderSessionPage(queryClient, 'session-a'))

    const input = await waitFor(() => getByPlaceholderText('managed.sessions.sendPlaceholder'))
    const sendButton = input.parentElement?.querySelector('button') as HTMLButtonElement
    expect(sendButton).toBeTruthy()

    await act(async () => {
      fireEvent.input(input, { target: { value: 'message after project archive' } })
      await Promise.resolve()
    })

    await act(async () => {
      useProjectStore.setState({ currentProject: projectInfo('2026-01-02T00:00:00Z') })
      fireEvent.click(sendButton)
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith(
      '/sessions/session-a/events',
      {
        events: [
          {
            type: 'user.message',
            content: [{ type: 'text', text: 'message after project archive' }],
          },
        ],
      },
      expect.objectContaining({
        headers: expect.objectContaining(managedOptions().headers),
        skipManagedContext: true,
      }),
    )
  })

  it('does not send a message from old session UI after the managed project changes to a same-id session', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/sessions/session-a') return session('session-a')
      if (path === '/sessions/session-a/resources') return { data: [] }
      if (path.includes('/events?')) return { data: [], has_more: false }
      return { data: [] }
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByPlaceholderText } = render(renderSessionPage(queryClient, 'session-a'))

    const input = await waitFor(() => getByPlaceholderText('managed.sessions.sendPlaceholder'))
    const sendButton = input.parentElement?.querySelector('button') as HTMLButtonElement
    expect(sendButton).toBeTruthy()

    await act(async () => {
      fireEvent.input(input, { target: { value: 'message after project switch' } })
      await Promise.resolve()
    })

    await act(async () => {
      queryClient.setQueryData(['session', 'session-a:org-a:project-b'], session('session-a'))
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      fireEvent.click(sendButton)
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith(
      '/sessions/session-a/events',
      {
        events: [
          {
            type: 'user.message',
            content: [{ type: 'text', text: 'message after project switch' }],
          },
        ],
      },
      expect.objectContaining({
        headers: expect.objectContaining(managedOptions().headers),
        skipManagedContext: true,
      }),
    )
  })

  it('does not stop the session after the current session detail is no longer running', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/sessions/session-a') return session('session-a', { status: 'running' })
      if (path === '/sessions/session-a/resources') return { data: [] }
      if (path.includes('/events?')) return { data: [], has_more: false }
      return { data: [] }
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText } = render(renderSessionPage(queryClient, 'session-a'))

    await waitFor(() => {
      expect(getByText('managed.sessions.stopSession')).toBeTruthy()
    })

    await act(async () => {
      queryClient.setQueryData(
        ['session', 'session-a:org-a:project-a'],
        session('session-a', { status: 'idle' }),
      )
      fireEvent.click(getByText('managed.sessions.stopSession'))
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith(
      '/sessions/session-a/stop',
      {},
      managedOptions(),
    )
  })

  it('does not stop the session from old UI after the current project is archived', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/sessions/session-a') return session('session-a', { status: 'running' })
      if (path === '/sessions/session-a/resources') return { data: [] }
      if (path.includes('/events?')) return { data: [], has_more: false }
      return { data: [] }
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText } = render(renderSessionPage(queryClient, 'session-a'))

    await waitFor(() => {
      expect(getByText('managed.sessions.stopSession')).toBeTruthy()
    })

    const stopButton = getByText('managed.sessions.stopSession')

    await act(async () => {
      useProjectStore.setState({ currentProject: projectInfo('2026-01-02T00:00:00Z') })
      fireEvent.click(stopButton)
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith(
      '/sessions/session-a/stop',
      {},
      managedOptions(),
    )
  })

  it('does not archive the session after the current session detail becomes archived', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/sessions/session-a') return session('session-a')
      if (path === '/sessions/session-a/resources') return { data: [] }
      if (path.includes('/events?')) return { data: [], has_more: false }
      return { data: [] }
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText } = render(renderSessionPage(queryClient, 'session-a'))

    await waitFor(() => {
      expect(getByText('managed.sessions.archive')).toBeTruthy()
    })

    await act(async () => {
      queryClient.setQueryData(['session', 'session-a:org-a:project-a'], {
        ...session('session-a'),
        archived_at: '2026-01-02T00:00:00Z',
      })
      fireEvent.click(getByText('managed.sessions.archive'))
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith(
      '/sessions/session-a/archive',
      {},
      managedOptions(),
    )
  })

  it('does not archive the session from old UI after the current project is archived', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/sessions/session-a') return session('session-a')
      if (path === '/sessions/session-a/resources') return { data: [] }
      if (path.includes('/events?')) return { data: [], has_more: false }
      return { data: [] }
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText } = render(renderSessionPage(queryClient, 'session-a'))

    await waitFor(() => {
      expect(getByText('managed.sessions.archive')).toBeTruthy()
    })

    const archiveButton = getByText('managed.sessions.archive')

    await act(async () => {
      useProjectStore.setState({ currentProject: projectInfo('2026-01-02T00:00:00Z') })
      fireEvent.click(archiveButton)
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith(
      '/sessions/session-a/archive',
      {},
      managedOptions(),
    )
  })

  it('does not close a reopened add-file dropdown when an older add finishes', async () => {
    const addFile = deferred<Record<string, never>>()
    managedPostMock.mockReturnValueOnce(addFile.promise)
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/sessions/session-a') return session('session-a')
      if (path === '/sessions/session-a/resources') {
        return {
          data: [
            {
              id: 'session_resource_mounted',
              type: 'file',
              file_id: 'file_mounted',
              mount_path: '/workspace/mounted.txt',
              access: 'read',
              created_at: '2026-01-01T00:00:00Z',
            },
          ],
        }
      }
      if (path === '/files?limit=100') {
        return {
          data: [
            {
              id: 'file_new',
              filename: 'available.txt',
              purpose: 'assistants',
              content_type: 'text/plain',
              size_bytes: 12,
              downloadable: true,
              created_at: '2026-01-01T00:00:00Z',
            },
          ],
        }
      }
      if (path.includes('/events?')) return { data: [], has_more: false }
      return { data: [] }
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByRole, getByText } = render(renderSessionPage(queryClient, 'session-a'))

    await waitFor(() => {
      expect(getByRole('button', { name: /managed\.sessions\.create\.resources/ })).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByRole('button', { name: /managed\.sessions\.create\.resources/ }))
    })

    await act(async () => {
      fireEvent.click(getByRole('button', { name: 'managed.sessions.addFile' }))
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(getByText('available.txt')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('available.txt'))
      await Promise.resolve()
    })

    await act(async () => {
      fireEvent.click(getByRole('button', { name: 'managed.sessions.addFile' }))
    })

    await act(async () => {
      fireEvent.click(getByRole('button', { name: 'managed.sessions.addFile' }))
    })

    await waitFor(() => {
      expect(getByText('available.txt')).toBeTruthy()
    })

    await act(async () => {
      addFile.resolve({})
      await addFile.promise
      await Promise.resolve()
    })

    expect(getByText('available.txt')).toBeTruthy()
  })

  it('does not add a file after it leaves the current files-for-add list', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/sessions/session-a') return session('session-a')
      if (path === '/sessions/session-a/resources') {
        return {
          data: [
            {
              id: 'session_resource_mounted',
              type: 'file',
              file_id: 'file_mounted',
              mount_path: '/workspace/mounted.txt',
              access: 'read',
              created_at: '2026-01-01T00:00:00Z',
            },
          ],
        }
      }
      if (path === '/files?limit=100') {
        return {
          data: [
            {
              id: 'file_stale',
              filename: 'stale.txt',
              purpose: 'assistants',
              content_type: 'text/plain',
              size_bytes: 12,
              downloadable: true,
              created_at: '2026-01-01T00:00:00Z',
            },
          ],
        }
      }
      if (path.includes('/events?')) return { data: [], has_more: false }
      return { data: [] }
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByRole, getByText } = render(renderSessionPage(queryClient, 'session-a'))

    await waitFor(() => {
      expect(getByRole('button', { name: /managed\.sessions\.create\.resources/ })).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByRole('button', { name: /managed\.sessions\.create\.resources/ }))
    })

    await act(async () => {
      fireEvent.click(getByRole('button', { name: 'managed.sessions.addFile' }))
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(getByText('stale.txt')).toBeTruthy()
    })

    await act(async () => {
      queryClient.setQueryData(['files-for-add', 'session-a:org-a:project-a'], { data: [] })
      fireEvent.click(getByText('stale.txt'))
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith(
      '/sessions/session-a/resources',
      {
        type: 'file',
        file_id: 'file_stale',
        mount_path: '/workspace/stale.txt',
      },
      managedOptions(),
    )
  })

  it('does not add a file after the current session is no longer idle', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/sessions/session-a') return session('session-a')
      if (path === '/sessions/session-a/resources') {
        return {
          data: [
            {
              id: 'session_resource_mounted',
              type: 'file',
              file_id: 'file_mounted',
              mount_path: '/workspace/mounted.txt',
              access: 'read',
              created_at: '2026-01-01T00:00:00Z',
            },
          ],
        }
      }
      if (path === '/files?limit=100') {
        return {
          data: [
            {
              id: 'file_stale_session',
              filename: 'stale-session.txt',
              purpose: 'assistants',
              content_type: 'text/plain',
              size_bytes: 12,
              downloadable: true,
              created_at: '2026-01-01T00:00:00Z',
            },
          ],
        }
      }
      if (path.includes('/events?')) return { data: [], has_more: false }
      return { data: [] }
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByRole, getByText } = render(renderSessionPage(queryClient, 'session-a'))

    await waitFor(() => {
      expect(getByRole('button', { name: /managed\.sessions\.create\.resources/ })).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByRole('button', { name: /managed\.sessions\.create\.resources/ }))
    })

    await act(async () => {
      fireEvent.click(getByRole('button', { name: 'managed.sessions.addFile' }))
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(getByText('stale-session.txt')).toBeTruthy()
    })

    await act(async () => {
      queryClient.setQueryData(['session', 'session-a:org-a:project-a'], {
        ...session('session-a'),
        status: 'running',
      })
      fireEvent.click(getByText('stale-session.txt'))
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith(
      '/sessions/session-a/resources',
      {
        type: 'file',
        file_id: 'file_stale_session',
        mount_path: '/workspace/stale-session.txt',
      },
      managedOptions(),
    )
  })

  it('does not add a file from old drawer UI after the current project is archived', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/sessions/session-a') return session('session-a')
      if (path === '/sessions/session-a/resources') {
        return {
          data: [
            {
              id: 'session_resource_mounted',
              type: 'file',
              file_id: 'file_mounted',
              mount_path: '/workspace/mounted.txt',
              access: 'read',
              created_at: '2026-01-01T00:00:00Z',
            },
          ],
        }
      }
      if (path === '/files?limit=100') {
        return {
          data: [
            {
              id: 'file_project_archived',
              filename: 'project-archived.txt',
              purpose: 'assistants',
              content_type: 'text/plain',
              size_bytes: 12,
              downloadable: true,
              created_at: '2026-01-01T00:00:00Z',
            },
          ],
        }
      }
      if (path.includes('/events?')) return { data: [], has_more: false }
      return { data: [] }
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByRole, getByText } = render(renderSessionPage(queryClient, 'session-a'))

    await waitFor(() => {
      expect(getByRole('button', { name: /managed\.sessions\.create\.resources/ })).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByRole('button', { name: /managed\.sessions\.create\.resources/ }))
    })

    await act(async () => {
      fireEvent.click(getByRole('button', { name: 'managed.sessions.addFile' }))
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(getByText('project-archived.txt')).toBeTruthy()
    })

    const oldFileButton = getByText('project-archived.txt')

    await act(async () => {
      useProjectStore.setState({ currentProject: projectInfo('2026-01-02T00:00:00Z') })
      fireEvent.click(oldFileButton)
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith(
      '/sessions/session-a/resources',
      {
        type: 'file',
        file_id: 'file_project_archived',
        mount_path: '/workspace/project-archived.txt',
      },
      managedOptions(),
    )
  })

  it('does not add a file from an old drawer after the managed project changes to a same-id session', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/sessions/session-a') return session('session-a')
      if (path === '/sessions/session-a/resources') {
        return {
          data: [
            {
              id: 'session_resource_existing_old_project',
              type: 'file',
              file_id: 'file_existing',
              mount_path: '/workspace/existing.txt',
              access: 'read',
              created_at: '2026-01-01T00:00:00Z',
            },
          ],
        }
      }
      if (path === '/files?limit=100') {
        return {
          data: [
            {
              id: 'file_old_project',
              filename: 'old-project.txt',
              purpose: 'assistants',
              content_type: 'text/plain',
              size_bytes: 12,
              downloadable: true,
              created_at: '2026-01-01T00:00:00Z',
            },
          ],
        }
      }
      if (path.includes('/events?')) return { data: [], has_more: false }
      return { data: [] }
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByRole, getByText } = render(renderSessionPage(queryClient, 'session-a'))

    await waitFor(() => {
      expect(getByRole('button', { name: /managed\.sessions\.create\.resources/ })).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByRole('button', { name: /managed\.sessions\.create\.resources/ }))
    })

    await act(async () => {
      fireEvent.click(getByRole('button', { name: 'managed.sessions.addFile' }))
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(getByText('old-project.txt')).toBeTruthy()
    })

    const oldFileButton = getByText('old-project.txt')

    await act(async () => {
      queryClient.setQueryData(['session', 'session-a:org-a:project-b'], session('session-a'))
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      await Promise.resolve()
    })

    await act(async () => {
      fireEvent.click(oldFileButton)
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith(
      '/sessions/session-a/resources',
      {
        type: 'file',
        file_id: 'file_old_project',
        mount_path: '/workspace/old-project.txt',
      },
      managedOptions(),
    )
  })

  it('does not remove a mounted file after it leaves the current session resources', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/sessions/session-a') return session('session-a')
      if (path === '/sessions/session-a/resources') {
        return {
          data: [
            {
              id: 'session_resource_stale',
              type: 'file',
              file_id: 'file_mounted',
              mount_path: '/workspace/mounted.txt',
              access: 'read',
              created_at: '2026-01-01T00:00:00Z',
            },
          ],
        }
      }
      if (path.includes('/events?')) return { data: [], has_more: false }
      return { data: [] }
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { container, getByRole } = render(renderSessionPage(queryClient, 'session-a'))

    await waitFor(() => {
      expect(getByRole('button', { name: /managed\.sessions\.create\.resources/ })).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByRole('button', { name: /managed\.sessions\.create\.resources/ }))
    })

    const removeButton = Array.from(container.querySelectorAll('button')).find((button) =>
      button.innerHTML.includes('lucide-trash2'),
    )
    expect(removeButton).toBeTruthy()

    await act(async () => {
      queryClient.setQueryData(['session-resources', 'session-a:org-a:project-a'], { data: [] })
      fireEvent.click(removeButton!)
      await Promise.resolve()
    })

    expect(managedDeleteMock).not.toHaveBeenCalledWith(
      '/sessions/session-a/resources/session_resource_stale',
      managedOptions(),
    )
  })

  it('does not remove a mounted file after the current session is no longer idle', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/sessions/session-a') return session('session-a')
      if (path === '/sessions/session-a/resources') {
        return {
          data: [
            {
              id: 'session_resource_stale_session',
              type: 'file',
              file_id: 'file_mounted',
              mount_path: '/workspace/mounted.txt',
              access: 'read',
              created_at: '2026-01-01T00:00:00Z',
            },
          ],
        }
      }
      if (path.includes('/events?')) return { data: [], has_more: false }
      return { data: [] }
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { container, getByRole } = render(renderSessionPage(queryClient, 'session-a'))

    await waitFor(() => {
      expect(getByRole('button', { name: /managed\.sessions\.create\.resources/ })).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByRole('button', { name: /managed\.sessions\.create\.resources/ }))
    })

    const removeButton = Array.from(container.querySelectorAll('button')).find((button) =>
      button.innerHTML.includes('lucide-trash2'),
    )
    expect(removeButton).toBeTruthy()

    await act(async () => {
      queryClient.setQueryData(['session', 'session-a:org-a:project-a'], {
        ...session('session-a'),
        status: 'running',
      })
      fireEvent.click(removeButton!)
      await Promise.resolve()
    })

    expect(managedDeleteMock).not.toHaveBeenCalledWith(
      '/sessions/session-a/resources/session_resource_stale_session',
      managedOptions(),
    )
  })

  it('does not remove a mounted file from an old drawer after the managed project changes to a same-id session', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/sessions/session-a') return session('session-a')
      if (path === '/sessions/session-a/resources') {
        return {
          data: [
            {
              id: 'session_resource_old_project',
              type: 'file',
              file_id: 'file_mounted',
              mount_path: '/workspace/mounted.txt',
              access: 'read',
              created_at: '2026-01-01T00:00:00Z',
            },
          ],
        }
      }
      if (path.includes('/events?')) return { data: [], has_more: false }
      return { data: [] }
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { container, getByRole } = render(renderSessionPage(queryClient, 'session-a'))

    await waitFor(() => {
      expect(getByRole('button', { name: /managed\.sessions\.create\.resources/ })).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByRole('button', { name: /managed\.sessions\.create\.resources/ }))
    })

    const removeButton = Array.from(container.querySelectorAll('button')).find((button) =>
      button.innerHTML.includes('lucide-trash2'),
    )
    expect(removeButton).toBeTruthy()

    await act(async () => {
      queryClient.setQueryData(['session', 'session-a:org-a:project-b'], session('session-a'))
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      await Promise.resolve()
    })

    await act(async () => {
      fireEvent.click(removeButton!)
      await Promise.resolve()
    })

    expect(managedDeleteMock).not.toHaveBeenCalledWith(
      '/sessions/session-a/resources/session_resource_old_project',
      managedOptions(),
    )
  })

  it('does not invalidate resources from an add-file completion after the page unmounts', async () => {
    const addFile = deferred<Record<string, never>>()
    managedPostMock.mockReturnValueOnce(addFile.promise)
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/sessions/session-a') return session('session-a')
      if (path === '/sessions/session-a/resources') {
        return {
          data: [
            {
              id: 'session_resource_mounted',
              type: 'file',
              file_id: 'file_mounted',
              mount_path: '/workspace/mounted.txt',
              access: 'read',
              created_at: '2026-01-01T00:00:00Z',
            },
          ],
        }
      }
      if (path === '/files?limit=100') {
        return {
          data: [
            {
              id: 'file_new',
              filename: 'available.txt',
              purpose: 'assistants',
              content_type: 'text/plain',
              size_bytes: 12,
              downloadable: true,
              created_at: '2026-01-01T00:00:00Z',
            },
          ],
        }
      }
      if (path.includes('/events?')) return { data: [], has_more: false }
      return { data: [] }
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    const view = render(renderSessionPage(queryClient, 'session-a'))

    await waitFor(() => {
      expect(
        view.getByRole('button', { name: /managed\.sessions\.create\.resources/ }),
      ).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(view.getByRole('button', { name: /managed\.sessions\.create\.resources/ }))
    })

    await act(async () => {
      fireEvent.click(view.getByRole('button', { name: 'managed.sessions.addFile' }))
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(view.getByText('available.txt')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(view.getByText('available.txt'))
      await Promise.resolve()
    })

    view.unmount()

    await act(async () => {
      addFile.resolve({})
      await addFile.promise
      await Promise.resolve()
    })

    expect(invalidateSpy).not.toHaveBeenCalledWith({
      queryKey: ['session-resources', 'session-a:org-a:project-a'],
    })
  })

  it('does not clear a newer repo token draft when an older token rotation finishes', async () => {
    const rotateToken = deferred<Record<string, never>>()
    managedPatchMock.mockReturnValueOnce(rotateToken.promise)
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/sessions/session-a') return session('session-a')
      if (path === '/sessions/session-a/resources') {
        return {
          data: [
            {
              id: 'session_resource_repo',
              type: 'github_repository',
              url: 'https://github.com/example/repo',
              branch: 'main',
              mount_path: '/workspace/repo',
              mount_name: 'repo',
            },
          ],
        }
      }
      if (path.includes('/events?')) return { data: [], has_more: false }
      return { data: [] }
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByPlaceholderText, getByRole } = render(renderSessionPage(queryClient, 'session-a'))

    await waitFor(() => {
      expect(getByRole('button', { name: /managed\.sessions\.create\.repositories/ })).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByRole('button', { name: /managed\.sessions\.create\.repositories/ }))
    })

    const tokenInput = getByPlaceholderText(
      'managed.sessions.rotateTokenPlaceholder',
    ) as HTMLInputElement

    await act(async () => {
      fireEvent.input(tokenInput, { target: { value: 'old-token' } })
    })

    await act(async () => {
      fireEvent.click(getByRole('button', { name: 'managed.sessions.rotateToken' }))
      await Promise.resolve()
    })

    expect(managedPatchMock).toHaveBeenCalledWith(
      '/sessions/session-a/resources/session_resource_repo',
      { authorization_token: 'old-token' },
      managedOptions(),
    )

    await act(async () => {
      fireEvent.input(tokenInput, { target: { value: 'new-token' } })
    })

    await act(async () => {
      rotateToken.resolve({})
      await rotateToken.promise
      await Promise.resolve()
    })

    expect(tokenInput.value).toBe('new-token')
  })

  it('does not rotate a repo token after the repo leaves the current session resources', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/sessions/session-a') return session('session-a')
      if (path === '/sessions/session-a/resources') {
        return {
          data: [
            {
              id: 'session_resource_repo',
              type: 'github_repository',
              url: 'https://github.com/example/repo',
              branch: 'main',
              mount_path: '/workspace/repo',
              mount_name: 'repo',
            },
          ],
        }
      }
      if (path.includes('/events?')) return { data: [], has_more: false }
      return { data: [] }
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByPlaceholderText, getByRole } = render(renderSessionPage(queryClient, 'session-a'))

    await waitFor(() => {
      expect(getByRole('button', { name: /managed\.sessions\.create\.repositories/ })).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByRole('button', { name: /managed\.sessions\.create\.repositories/ }))
    })

    const tokenInput = getByPlaceholderText(
      'managed.sessions.rotateTokenPlaceholder',
    ) as HTMLInputElement

    await act(async () => {
      fireEvent.input(tokenInput, { target: { value: 'stale-token' } })
    })

    await act(async () => {
      queryClient.setQueryData(['session-resources', 'session-a:org-a:project-a'], { data: [] })
      fireEvent.click(getByRole('button', { name: 'managed.sessions.rotateToken' }))
      await Promise.resolve()
    })

    expect(managedPatchMock).not.toHaveBeenCalledWith(
      '/sessions/session-a/resources/session_resource_repo',
      { authorization_token: 'stale-token' },
      managedOptions(),
    )
  })

  it('does not rotate a repo token after the current session is no longer idle', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/sessions/session-a') return session('session-a')
      if (path === '/sessions/session-a/resources') {
        return {
          data: [
            {
              id: 'session_resource_repo',
              type: 'github_repository',
              url: 'https://github.com/example/repo',
              branch: 'main',
              mount_path: '/workspace/repo',
              mount_name: 'repo',
            },
          ],
        }
      }
      if (path.includes('/events?')) return { data: [], has_more: false }
      return { data: [] }
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByPlaceholderText, getByRole } = render(renderSessionPage(queryClient, 'session-a'))

    await waitFor(() => {
      expect(getByRole('button', { name: /managed\.sessions\.create\.repositories/ })).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByRole('button', { name: /managed\.sessions\.create\.repositories/ }))
    })

    const tokenInput = getByPlaceholderText(
      'managed.sessions.rotateTokenPlaceholder',
    ) as HTMLInputElement

    await act(async () => {
      fireEvent.input(tokenInput, { target: { value: 'stale-session-token' } })
    })

    await act(async () => {
      queryClient.setQueryData(['session', 'session-a:org-a:project-a'], {
        ...session('session-a'),
        status: 'running',
      })
      fireEvent.click(getByRole('button', { name: 'managed.sessions.rotateToken' }))
      await Promise.resolve()
    })

    expect(managedPatchMock).not.toHaveBeenCalledWith(
      '/sessions/session-a/resources/session_resource_repo',
      { authorization_token: 'stale-session-token' },
      managedOptions(),
    )
  })

  it('does not rotate a repo token from an old drawer after the managed project changes to a same-id session', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/sessions/session-a') return session('session-a')
      if (path === '/sessions/session-a/resources') {
        return {
          data: [
            {
              id: 'session_resource_repo_old_project',
              type: 'github_repository',
              url: 'https://github.com/example/repo',
              branch: 'main',
              mount_path: '/workspace/repo',
              mount_name: 'repo',
            },
          ],
        }
      }
      if (path.includes('/events?')) return { data: [], has_more: false }
      return { data: [] }
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByPlaceholderText, getByRole } = render(renderSessionPage(queryClient, 'session-a'))

    await waitFor(() => {
      expect(getByRole('button', { name: /managed\.sessions\.create\.repositories/ })).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByRole('button', { name: /managed\.sessions\.create\.repositories/ }))
    })

    const tokenInput = getByPlaceholderText(
      'managed.sessions.rotateTokenPlaceholder',
    ) as HTMLInputElement

    await act(async () => {
      fireEvent.input(tokenInput, { target: { value: 'old-project-token' } })
    })

    const rotateButton = getByRole('button', { name: 'managed.sessions.rotateToken' })

    await act(async () => {
      queryClient.setQueryData(['session', 'session-a:org-a:project-b'], session('session-a'))
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      await Promise.resolve()
    })

    await act(async () => {
      fireEvent.click(rotateButton)
      await Promise.resolve()
    })

    expect(managedPatchMock).not.toHaveBeenCalledWith(
      '/sessions/session-a/resources/session_resource_repo_old_project',
      { authorization_token: 'old-project-token' },
      managedOptions(),
    )
  })

  it('does not invalidate resources from a token rotation completion after the page unmounts', async () => {
    const rotateToken = deferred<Record<string, never>>()
    managedPatchMock.mockReturnValueOnce(rotateToken.promise)
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/sessions/session-a') return session('session-a')
      if (path === '/sessions/session-a/resources') {
        return {
          data: [
            {
              id: 'session_resource_repo',
              type: 'github_repository',
              url: 'https://github.com/example/repo',
              branch: 'main',
              mount_path: '/workspace/repo',
              mount_name: 'repo',
            },
          ],
        }
      }
      if (path.includes('/events?')) return { data: [], has_more: false }
      return { data: [] }
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    const view = render(renderSessionPage(queryClient, 'session-a'))

    await waitFor(() => {
      expect(
        view.getByRole('button', { name: /managed\.sessions\.create\.repositories/ }),
      ).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(view.getByRole('button', { name: /managed\.sessions\.create\.repositories/ }))
    })

    const tokenInput = view.getByPlaceholderText(
      'managed.sessions.rotateTokenPlaceholder',
    ) as HTMLInputElement

    await act(async () => {
      fireEvent.input(tokenInput, { target: { value: 'token-before-unmount' } })
    })

    await act(async () => {
      fireEvent.click(view.getByRole('button', { name: 'managed.sessions.rotateToken' }))
      await Promise.resolve()
    })

    view.unmount()

    await act(async () => {
      rotateToken.resolve({})
      await rotateToken.promise
      await Promise.resolve()
    })

    expect(invalidateSpy).not.toHaveBeenCalledWith({
      queryKey: ['session-resources', 'session-a:org-a:project-a'],
    })
  })
})
