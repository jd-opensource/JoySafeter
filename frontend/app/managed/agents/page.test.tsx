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
  managedDelete: vi.fn(),
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
  DataTable: ({
    actionMenu,
    data,
  }: {
    actionMenu?: (row: AgentRecord) => { label: string; onClick: () => void }[]
    data: AgentRecord[]
  }) => (
    <div>
      {data.map((agent) => (
        <div key={agent.id}>
          <span>{agent.name}</span>
          {actionMenu?.(agent).map((item) => (
            <button key={item.label} onClick={item.onClick}>
              {agent.id}:{item.label}
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
  SkillVersionSelect: () => null,
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
  Dialog: ({ children, open }: { children: ReactNode; open: boolean }) =>
    open ? <div>{children}</div> : null,
  DialogContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogFooter: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogHeader: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children: ReactNode }) => <h1>{children}</h1>,
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

import { managedDelete, managedGet, managedPost } from '@/lib/api-client'
import { useProjectStore } from '@/stores/managed/project-store'

import AgentListPage from './page'

interface AgentRecord {
  id: string
  name: string
  model?: { id: string } | null
  engine_kind?: string | null
  archived_at?: string | null
  created_at: string
  updated_at: string
}

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

function agent(id: string, name: string): AgentRecord {
  return {
    id,
    name,
    model: { id: 'claude-sonnet' },
    engine_kind: 'claude',
    archived_at: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  }
}

describe('AgentListPage row action lifecycle', () => {
  beforeEach(() => {
    managedDeleteMock.mockReset()
    managedGetMock.mockReset()
    managedPostMock.mockReset()
    managedDeleteMock.mockResolvedValue({})
    managedGetMock.mockImplementation(async (path: string) => {
      if (path.endsWith('/delete_preview')) return { sessions: 0, tasks: 0, versions: 0 }
      return { data: [agent('agent-a', 'Agent A')], has_more: false }
    })
    managedPostMock.mockResolvedValue({})
    useProjectStore.setState({
      currentOrgId: 'org-a',
      currentProjectId: 'project-a',
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

  it('does not archive an agent from an old row action in the same turn as a project switch', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText } = render(
      <QueryClientProvider client={queryClient}>
        <AgentListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Agent A')).toBeTruthy()
    })

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      fireEvent.click(getByText('agent-a:managed.agents.archiveAgent'))
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith('/agents/agent-a/archive', {})
  })

  it('does not invalidate the current project after an older project archive finishes', async () => {
    const archive = deferred<void>()
    managedPostMock.mockReturnValueOnce(archive.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    const { getByText, rerender } = render(
      <QueryClientProvider client={queryClient}>
        <AgentListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Agent A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('agent-a:managed.agents.archiveAgent'))
      await Promise.resolve()
    })

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      rerender(
        <QueryClientProvider client={queryClient}>
          <AgentListPage />
        </QueryClientProvider>,
      )
      archive.resolve()
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(managedPostMock).toHaveBeenCalledWith('/agents/agent-a/archive', {})
    })
    expect(invalidateSpy).not.toHaveBeenCalledWith({ queryKey: ['agents'] })
  })

  it('does not invalidate agents from an archive completion after the page unmounts', async () => {
    const archive = deferred<void>()
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
        <AgentListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Agent A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('agent-a:managed.agents.archiveAgent'))
      await Promise.resolve()
    })

    unmount()

    await act(async () => {
      archive.resolve()
      await Promise.resolve()
    })

    expect(invalidateSpy).not.toHaveBeenCalledWith({ queryKey: ['agents'] })
  })

  it('does not archive an agent target that is no longer in the current agents list', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText } = render(
      <QueryClientProvider client={queryClient}>
        <AgentListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Agent A')).toBeTruthy()
    })

    await act(async () => {
      queryClient.setQueryData(['agents', 'org-a:project-a', '/agents', undefined, false, 10], {
        data: [agent('agent-b', 'Agent B')],
        has_more: false,
      })
      fireEvent.click(getByText('agent-a:managed.agents.archiveAgent'))
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith('/agents/agent-a/archive', {})
  })

  it('exposes the delete action for an active agent row', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText } = render(
      <QueryClientProvider client={queryClient}>
        <AgentListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Agent A')).toBeTruthy()
    })

    expect(getByText('agent-a:common.delete')).toBeTruthy()
  })

  it('does not request a delete preview for an agent no longer in the current agents list', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText } = render(
      <QueryClientProvider client={queryClient}>
        <AgentListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Agent A')).toBeTruthy()
    })

    await act(async () => {
      queryClient.setQueryData(['agents', 'org-a:project-a', '/agents', undefined, false, 10], {
        data: [agent('agent-b', 'Agent B')],
        has_more: false,
      })
      fireEvent.click(getByText('agent-a:common.delete'))
      await Promise.resolve()
    })

    expect(managedGetMock).not.toHaveBeenCalledWith('/agents/agent-a/delete_preview')
  })

  it('does not delete an agent target that leaves the current agents list before confirmation', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByRole, getByText } = render(
      <QueryClientProvider client={queryClient}>
        <AgentListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Agent A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('agent-a:common.delete'))
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(getByRole('button', { name: 'managed.agents.permanentlyDelete' })).toBeTruthy()
    })

    await act(async () => {
      queryClient.setQueryData(['agents', 'org-a:project-a', '/agents', undefined, false, 10], {
        data: [agent('agent-b', 'Agent B')],
        has_more: false,
      })
      fireEvent.click(getByRole('button', { name: 'managed.agents.permanentlyDelete' }))
      await Promise.resolve()
    })

    expect(managedDeleteMock).not.toHaveBeenCalledWith('/agents/agent-a')
  })
})
