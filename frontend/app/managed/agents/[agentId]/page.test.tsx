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
  managedDelete: vi.fn(),
  managedGet: vi.fn(),
  managedPost: vi.fn(),
}))

vi.mock('@/lib/managed/errors', () => ({
  shouldRetryManagedResourceError: vi.fn(() => false),
  toastOperationError: vi.fn(),
}))

vi.mock('@/components/managed/agent/version-diff-view', () => ({
  VersionDiffView: () => null,
}))

vi.mock('@/components/managed/shared', () => ({
  ActionMenu: ({ items }: { items: { label: string; onClick: () => void }[] }) => (
    <div>
      {items.map((item) => (
        <button key={item.label} onClick={item.onClick}>
          {item.label}
        </button>
      ))}
    </div>
  ),
  ConfirmDialog: ({
    confirmLabel,
    onCancel,
    onConfirm,
    open,
    title,
  }: {
    confirmLabel: string
    onCancel: () => void
    onConfirm: () => void
    open: boolean
    title: string
  }) =>
    open ? (
      <div>
        <h2>{title}</h2>
        <button onClick={onCancel}>common.cancel</button>
        <button onClick={onConfirm}>{confirmLabel}</button>
      </div>
    ) : null,
  DataTable: <T extends { id?: string }>({
    actionMenu,
    data = [],
  }: {
    actionMenu?: (row: T) => { label: string; onClick: () => void }[]
    data?: T[]
  }) => (
    <div>
      {data.map((row, index) => (
        <div key={row.id ?? index}>
          {actionMenu?.(row).map((item) => (
            <button key={item.label} onClick={item.onClick}>
              {row.id ?? index}:{item.label}
            </button>
          ))}
        </div>
      ))}
    </div>
  ),
  FilterBar: () => null,
  MonoId: ({ id }: { id: string }) => <span>{id}</span>,
  PageHeader: ({
    action,
    title,
  }: {
    action?: ReactNode
    breadcrumb?: { label: string; to?: string }[]
    title: string
    titleExtra?: ReactNode
  }) => (
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

vi.mock('@/components/ui/select', () => ({
  Select: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectItem: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectTrigger: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectValue: ({ children }: { children?: ReactNode }) => <span>{children}</span>,
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

import { managedDelete, managedGet, managedPost } from '@/lib/api-client'
import { useProjectStore } from '@/stores/managed/project-store'

import AgentDetailPage from './page'

const managedGetMock = managedGet as unknown as ReturnType<typeof vi.fn>
const managedDeleteMock = managedDelete as unknown as ReturnType<typeof vi.fn>
const managedPostMock = managedPost as unknown as ReturnType<typeof vi.fn>

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

function agent(id: string, name: string) {
  return {
    id,
    name,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-02T00:00:00Z',
    version: 1,
  }
}

function renderAgentPage(queryClient: QueryClient, agentId: string) {
  const params = {
    status: 'fulfilled',
    value: { agentId },
    then: () => undefined,
  } as unknown as Promise<{ agentId: string }>

  return (
    <QueryClientProvider client={queryClient}>
      <AgentDetailPage params={params} />
    </QueryClientProvider>
  )
}

describe('AgentDetailPage route lifecycle', () => {
  beforeEach(() => {
    pushMock.mockReset()
    managedDeleteMock.mockReset()
    managedGetMock.mockReset()
    managedPostMock.mockReset()
    managedDeleteMock.mockResolvedValue({})
    managedPostMock.mockResolvedValue({})
    useProjectStore.setState({
      currentOrgId: 'org-a',
      currentProjectId: 'project-a',
      organizations: [],
      projects: [],
    })
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/agents/agent-a') return agent('agent-a', 'Agent A')
      if (path === '/agents/agent-b') return agent('agent-b', 'Agent B')
      if (path.endsWith('/sessions')) return { data: [] }
      if (path.endsWith('/versions')) return { data: [] }
      return { data: [] }
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

  it('refetches agent detail resources after the managed project changes', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText } = render(renderAgentPage(queryClient, 'agent-a'))

    await waitFor(() => {
      expect(getByText('Agent A')).toBeTruthy()
      expect(managedGetMock).toHaveBeenCalledWith('/agents/agent-a')
      expect(managedGetMock).toHaveBeenCalledWith('/agents/agent-a/sessions')
      expect(managedGetMock).toHaveBeenCalledWith('/agents/agent-a/versions')
    })
    expect(managedGetMock.mock.calls.filter(([path]) => path === '/agents/agent-a')).toHaveLength(1)
    expect(
      managedGetMock.mock.calls.filter(([path]) => path === '/agents/agent-a/sessions'),
    ).toHaveLength(1)
    expect(
      managedGetMock.mock.calls.filter(([path]) => path === '/agents/agent-a/versions'),
    ).toHaveLength(1)

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(managedGetMock.mock.calls.filter(([path]) => path === '/agents/agent-a')).toHaveLength(2)
      expect(
        managedGetMock.mock.calls.filter(([path]) => path === '/agents/agent-a/sessions'),
      ).toHaveLength(2)
      expect(
        managedGetMock.mock.calls.filter(([path]) => path === '/agents/agent-a/versions'),
      ).toHaveLength(2)
    })
  })

  it('does not run an archive confirmation captured for a previous route agent', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText, queryAllByRole, rerender } = render(renderAgentPage(queryClient, 'agent-a'))

    await waitFor(() => {
      expect(getByText('Agent A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('common.archive'))
    })

    await act(async () => {
      rerender(renderAgentPage(queryClient, 'agent-b'))
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(getByText('Agent B')).toBeTruthy()
    })

    const archiveButtons = queryAllByRole('button', { name: 'common.archive' })
    const confirmButton = archiveButtons[archiveButtons.length - 1]
    if (archiveButtons.length > 1 && confirmButton) {
      await act(async () => {
        fireEvent.click(confirmButton)
      })
    }

    expect(managedPostMock).not.toHaveBeenCalledWith('/agents/agent-a/archive', {})
  })

  it('does not invalidate from an archive completion after the route agent changes', async () => {
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

    const { getAllByRole, getByText, rerender } = render(renderAgentPage(queryClient, 'agent-a'))

    await waitFor(() => {
      expect(getByText('Agent A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('common.archive'))
    })

    await act(async () => {
      const archiveButtons = getAllByRole('button', { name: 'common.archive' })
      fireEvent.click(archiveButtons[archiveButtons.length - 1])
      await Promise.resolve()
    })

    await act(async () => {
      rerender(renderAgentPage(queryClient, 'agent-b'))
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(getByText('Agent B')).toBeTruthy()
    })

    await act(async () => {
      archive.resolve({})
      await Promise.resolve()
    })

    expect(invalidateSpy).not.toHaveBeenCalledWith({
      queryKey: ['agent', 'org-a:project-a', 'agent-a'],
    })
  })

  it('does not archive the agent after the current agent detail is no longer active', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getAllByRole, getByText } = render(renderAgentPage(queryClient, 'agent-a'))

    await waitFor(() => {
      expect(getByText('Agent A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('common.archive'))
    })

    await act(async () => {
      queryClient.setQueryData(['agent', 'org-a:project-a', 'agent-a'], {
        ...agent('agent-a', 'Agent A'),
        archived_at: '2026-01-02T00:00:00Z',
      })
      const archiveButtons = getAllByRole('button', { name: 'common.archive' })
      fireEvent.click(archiveButtons[archiveButtons.length - 1])
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith('/agents/agent-a/archive', {})
  })

  it('does not invalidate session list from a session archive completion after the route agent changes', async () => {
    const archive = deferred<Record<string, never>>()
    managedPostMock.mockReturnValueOnce(archive.promise)
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/agents/agent-a') return agent('agent-a', 'Agent A')
      if (path === '/agents/agent-b') return agent('agent-b', 'Agent B')
      if (path === '/agents/agent-a/sessions') {
        return {
          data: [
            {
              id: 'session-a',
              title: 'Session A',
              status: 'completed',
              created_at: '2026-01-03T00:00:00Z',
              agent: { version: 1 },
            },
          ],
        }
      }
      if (path.endsWith('/sessions')) return { data: [] }
      if (path.endsWith('/versions')) return { data: [] }
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

    const { getByText, rerender } = render(renderAgentPage(queryClient, 'agent-a'))

    await waitFor(() => {
      expect(getByText('session-a:common.archive')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('session-a:common.archive'))
      await Promise.resolve()
    })

    await act(async () => {
      rerender(renderAgentPage(queryClient, 'agent-b'))
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(getByText('Agent B')).toBeTruthy()
    })

    await act(async () => {
      archive.resolve({})
      await Promise.resolve()
    })

    expect(invalidateSpy).not.toHaveBeenCalledWith({
      queryKey: ['agent-sessions', 'org-a:project-a', 'agent-a'],
      exact: false,
    })
  })

  it('does not archive a session after it leaves the current agent session list', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/agents/agent-a') return agent('agent-a', 'Agent A')
      if (path === '/agents/agent-a/sessions') {
        return {
          data: [
            {
              id: 'session-a',
              title: 'Session A',
              status: 'completed',
              created_at: '2026-01-03T00:00:00Z',
              agent: { version: 1 },
            },
          ],
        }
      }
      if (path.endsWith('/sessions')) return { data: [] }
      if (path.endsWith('/versions')) return { data: [] }
      return { data: [] }
    })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText } = render(renderAgentPage(queryClient, 'agent-a'))

    await waitFor(() => {
      expect(getByText('session-a:common.archive')).toBeTruthy()
    })

    await act(async () => {
      queryClient.setQueryData(['agent-sessions', 'org-a:project-a', 'agent-a', false], [])
      fireEvent.click(getByText('session-a:common.archive'))
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith('/sessions/session-a/archive', {})
  })

  it('does not archive a session after the current agent detail is no longer active', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/agents/agent-a') return agent('agent-a', 'Agent A')
      if (path === '/agents/agent-a/sessions') {
        return {
          data: [
            {
              id: 'session-a',
              title: 'Session A',
              status: 'completed',
              created_at: '2026-01-03T00:00:00Z',
              agent: { version: 1 },
            },
          ],
        }
      }
      if (path.endsWith('/sessions')) return { data: [] }
      if (path.endsWith('/versions')) return { data: [] }
      return { data: [] }
    })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText } = render(renderAgentPage(queryClient, 'agent-a'))

    await waitFor(() => {
      expect(getByText('session-a:common.archive')).toBeTruthy()
    })

    await act(async () => {
      queryClient.setQueryData(['agent', 'org-a:project-a', 'agent-a'], {
        ...agent('agent-a', 'Agent A'),
        archived_at: '2026-01-02T00:00:00Z',
      })
      fireEvent.click(getByText('session-a:common.archive'))
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith('/sessions/session-a/archive', {})
  })

  it('does not start a session after the current agent detail is no longer active', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText } = render(renderAgentPage(queryClient, 'agent-a'))

    await waitFor(() => {
      expect(getByText('Agent A')).toBeTruthy()
    })

    await act(async () => {
      queryClient.setQueryData(['agent', 'org-a:project-a', 'agent-a'], {
        ...agent('agent-a', 'Agent A'),
        archived_at: '2026-01-02T00:00:00Z',
      })
      fireEvent.click(getByText('managed.agents.startSession'))
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith('/sessions', { agent: 'agent-a' })
  })

  it('does not navigate from a start-session completion after the managed project changes', async () => {
    let resolveSession!: (value: { id: string }) => void
    managedPostMock.mockImplementation(
      () =>
        new Promise<{ id: string }>((resolve) => {
          resolveSession = resolve
        }),
    )
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText } = render(renderAgentPage(queryClient, 'agent-a'))

    await waitFor(() => {
      expect(getByText('Agent A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('managed.agents.startSession'))
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(managedPostMock).toHaveBeenCalledWith('/sessions', { agent: 'agent-a' })
    })

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      resolveSession({ id: 'session-from-project-a' })
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(pushMock).not.toHaveBeenCalledWith('/managed/sessions/session-from-project-a')
  })

  it('does not navigate from a start-session completion after the page unmounts', async () => {
    const start = deferred<{ id: string }>()
    managedPostMock.mockReturnValueOnce(start.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText, unmount } = render(renderAgentPage(queryClient, 'agent-a'))

    await waitFor(() => {
      expect(getByText('Agent A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('managed.agents.startSession'))
      await Promise.resolve()
    })

    unmount()

    await act(async () => {
      start.resolve({ id: 'session-after-unmount' })
      await Promise.resolve()
    })

    expect(pushMock).not.toHaveBeenCalledWith('/managed/sessions/session-after-unmount')
  })

  it('does not invalidate from an archive completion after the page unmounts', async () => {
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

    const { getAllByRole, getByText, unmount } = render(renderAgentPage(queryClient, 'agent-a'))

    await waitFor(() => {
      expect(getByText('Agent A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('common.archive'))
    })

    await act(async () => {
      const archiveButtons = getAllByRole('button', { name: 'common.archive' })
      fireEvent.click(archiveButtons[archiveButtons.length - 1])
      await Promise.resolve()
    })

    unmount()

    await act(async () => {
      archive.resolve({})
      await Promise.resolve()
    })

    expect(invalidateSpy).not.toHaveBeenCalledWith({
      queryKey: ['agent', 'org-a:project-a', 'agent-a'],
    })
  })

  it('exposes the delete action for an active agent detail', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText } = render(renderAgentPage(queryClient, 'agent-a'))

    await waitFor(() => {
      expect(getByText('Agent A')).toBeTruthy()
    })

    expect(getByText('common.delete')).toBeTruthy()
  })

  it('does not request a delete preview after the current agent detail is no longer active', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText } = render(renderAgentPage(queryClient, 'agent-a'))

    await waitFor(() => {
      expect(getByText('Agent A')).toBeTruthy()
    })

    await act(async () => {
      queryClient.setQueryData(['agent', 'org-a:project-a', 'agent-a'], {
        ...agent('agent-a', 'Agent A'),
        archived_at: '2026-01-02T00:00:00Z',
      })
      fireEvent.click(getByText('common.delete'))
      await Promise.resolve()
    })

    expect(managedGetMock).not.toHaveBeenCalledWith('/agents/agent-a/delete_preview')
  })

  it('does not delete after the current agent detail is no longer active', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByRole, getByText } = render(renderAgentPage(queryClient, 'agent-a'))

    await waitFor(() => {
      expect(getByText('Agent A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('common.delete'))
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(getByRole('button', { name: 'managed.agents.permanentlyDelete' })).toBeTruthy()
    })

    await act(async () => {
      queryClient.setQueryData(['agent', 'org-a:project-a', 'agent-a'], {
        ...agent('agent-a', 'Agent A'),
        archived_at: '2026-01-02T00:00:00Z',
      })
      fireEvent.click(getByRole('button', { name: 'managed.agents.permanentlyDelete' }))
      await Promise.resolve()
    })

    expect(managedDeleteMock).not.toHaveBeenCalledWith('/agents/agent-a')
  })
})
