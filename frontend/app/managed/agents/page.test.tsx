import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, type RenderResult } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const routerPush = vi.fn()
const managedPost = vi.fn()
const toast = vi.fn()
let actionRun = 0
let agentRows: Array<Record<string, unknown>> = []
let projectReadOnly = false

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({
    t: (key: string, values?: Record<string, unknown>) =>
      values ? `${key}:${JSON.stringify(values)}` : key,
  }),
}))
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: routerPush }) }))
vi.mock('@/hooks/managed/use-paginated-list', () => ({
  usePaginatedList: () => ({
    data: agentRows,
    isLoading: false,
    isFetching: false,
    isError: false,
    error: null,
    hasNext: false,
    hasPrev: false,
    page: 1,
    pageSize: 10,
    pageSizeOptions: [10, 25, 50],
    goNext: vi.fn(),
    goPrev: vi.fn(),
    goToPage: vi.fn(),
    setPageSize: vi.fn(),
  }),
}))
vi.mock('@/hooks/managed/use-scoped-actions', () => ({
  useScopedActions: ({ onReset }: { onReset?: () => void } = {}) => {
    void onReset
    return {
      scopeRef: { current: 'scope' },
      requestScopeRef: { current: { key: 'scope', orgId: 'org', projectId: 'project' } },
      scope: { key: 'scope', orgId: 'org', projectId: 'project' },
      readOnly: projectReadOnly,
      beginAction: () => ({
        runId: ++actionRun,
        scope: 'scope',
        requestScope: { key: 'scope', orgId: 'org', projectId: 'project' },
      }),
      isCurrentAction: (runId: number) => runId === actionRun,
      scopeIsActive: () => true,
      bumpRun: () => {
        actionRun += 1
      },
    }
  },
}))
vi.mock('@/hooks/managed/use-current-project-read-only', () => ({
  currentProjectAllowsWrite: () => !projectReadOnly,
}))
vi.mock('@/lib/api-client', () => ({
  managedGet: vi.fn(),
  managedPost: (...args: unknown[]) => managedPost(...args),
  managedDelete: vi.fn(),
}))
vi.mock('@/hooks/use-toast', () => ({ toast: (...args: unknown[]) => toast(...args) }))
vi.mock('@/lib/managed/agent-response-parsers', () => ({
  parseAgentResponse: (value: unknown) => value,
}))
vi.mock('./components/create-agent-dialog', () => ({ CreateAgentDialog: () => null }))
vi.mock('@/components/managed/shared/action-menu', () => ({
  ActionMenu: ({
    items,
    disabled,
  }: {
    items: Array<{ label: string; onClick: () => void }>
    disabled?: boolean
  }) => (
    <div>
      {items.map((item) => (
        <button key={item.label} type="button" disabled={disabled} onClick={item.onClick}>
          {item.label}
        </button>
      ))}
    </div>
  ),
}))
vi.mock('@/components/managed/shared', async () => {
  const actual = await vi.importActual<typeof import('@/components/managed/shared')>(
    '@/components/managed/shared',
  )
  return {
    ...actual,
    PageHeader: ({ action }: { action?: ReactNode }) => <div>{action}</div>,
    FilterBar: () => null,
    StatusBadge: ({ status }: { status: string }) => <span>{status}</span>,
    MonoId: ({ id }: { id: string }) => <span>{id}</span>,
    RelativeTime: ({ date }: { date: string }) => <span>{date}</span>,
    ResourceErrorState: () => <div>error</div>,
    ConfirmDialog: ({
      open,
      confirmLabel,
      onConfirm,
    }: {
      open: boolean
      confirmLabel?: string
      onConfirm: () => void
    }) =>
      open ? (
        <button type="button" onClick={onConfirm}>
          confirm:{confirmLabel}
        </button>
      ) : null,
  }
})

import AgentListPage from './page'

function renderPage(): RenderResult {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(['agents', 'scope', '/agents'], { data: agentRows })
  return render(
    <QueryClientProvider client={queryClient}>
      <AgentListPage />
    </QueryClientProvider>,
  )
}

describe('AgentListPage', () => {
  beforeEach(() => {
    routerPush.mockClear()
    managedPost.mockReset()
    toast.mockReset()
    actionRun = 0
    projectReadOnly = false
    agentRows = [
      {
        id: 'agent_018f6f42-0a51-7cc4-98c8-4f6f0ca5f122',
        name: 'Research Agent',
        model: { id: 'GPT-4.1' },
        engine_kind: 'pi',
        archived_at: null,
        created_at: '2026-08-07T00:00:00Z',
        updated_at: '2026-08-08T00:00:00Z',
      },
    ]
  })

  it('shows the engine as secondary model information instead of a separate column', () => {
    renderPage()

    expect(screen.getByText('managed.table.model / managed.agents.engineKind')).toBeTruthy()
    expect(screen.getByText('GPT-4.1')).toBeTruthy()
    expect(screen.getByText('managed.agents.engineKind: Pi')).toBeTruthy()
    expect(screen.queryByText('managed.table.engineKind')).toBeNull()
  })

  it('shows high-frequency list actions without exposing permanent delete', () => {
    renderPage()

    expect(screen.getByText('managed.agents.viewDetails')).toBeTruthy()
    expect(screen.getByText('managed.agents.startSession')).toBeTruthy()
    expect(screen.getByText('common.edit')).toBeTruthy()
    expect(screen.getByText('common.archive')).toBeTruthy()
    expect(screen.queryByText('common.delete')).toBeNull()
  })

  it('creates a session and navigates when the list start action is used', async () => {
    const sessionId = 'sess_018f6f42-0a51-7cc4-98c8-4f6f0ca5f123'
    managedPost.mockResolvedValue({ id: sessionId })
    renderPage()

    fireEvent.click(screen.getByText('managed.agents.startSession'))

    await waitFor(() => expect(routerPush).toHaveBeenCalledWith(`/managed/sessions/${sessionId}`))
  })

  it('shows only view and restore actions for archived agents', () => {
    agentRows = [
      {
        ...agentRows[0],
        archived_at: '2026-08-09T00:00:00Z',
      },
    ]
    renderPage()

    expect(screen.getByText('managed.agents.viewDetails')).toBeTruthy()
    expect(screen.getByText('common.restore')).toBeTruthy()
    expect(screen.queryByText('managed.agents.startSession')).toBeNull()
    expect(screen.queryByText('common.edit')).toBeNull()
    expect(screen.queryByText('common.archive')).toBeNull()
    expect(screen.queryByText('common.delete')).toBeNull()
  })

  it('confirms and restores an archived agent from the list', async () => {
    const agentId = String(agentRows[0].id)
    agentRows = [
      {
        ...agentRows[0],
        archived_at: '2026-08-09T00:00:00Z',
      },
    ]
    managedPost.mockResolvedValue({ status: 'active' })
    renderPage()

    fireEvent.click(screen.getByText('common.restore'))
    fireEvent.click(screen.getByText('confirm:common.restore'))

    await waitFor(() =>
      expect(managedPost).toHaveBeenCalledWith(
        `/agents/${agentId}/unarchive`,
        {},
        expect.anything(),
      ),
    )
  })

  it('requires confirmation before archiving an active agent', async () => {
    const agentId = String(agentRows[0].id)
    managedPost.mockResolvedValue({ status: 'archived' })
    renderPage()

    fireEvent.click(screen.getByText('common.archive'))
    expect(managedPost).not.toHaveBeenCalled()

    fireEvent.click(screen.getByText('confirm:common.archive'))
    await waitFor(() =>
      expect(managedPost).toHaveBeenCalledWith(`/agents/${agentId}/archive`, {}, expect.anything()),
    )
  })

  it('offers undo after an agent is archived', async () => {
    const agentId = String(agentRows[0].id)
    managedPost.mockResolvedValue({ status: 'ok' })
    renderPage()

    fireEvent.click(screen.getByText('common.archive'))
    fireEvent.click(screen.getByText('confirm:common.archive'))

    await waitFor(() => expect(toast).toHaveBeenCalled())
    const toastOptions = toast.mock.calls[0][0] as {
      action?: { props: { onClick: () => Promise<void> } }
    }
    expect(toastOptions.action).toBeTruthy()

    await act(async () => {
      await toastOptions.action?.props.onClick()
    })

    await waitFor(() =>
      expect(managedPost).toHaveBeenCalledWith(
        `/agents/${agentId}/unarchive`,
        {},
        expect.anything(),
      ),
    )
  })

  it('shows row-level progress and disables other mutations while a session starts', async () => {
    let resolveSession!: (value: { id: string }) => void
    managedPost.mockReturnValue(
      new Promise<{ id: string }>((resolve) => {
        resolveSession = resolve
      }),
    )
    renderPage()

    fireEvent.click(screen.getByText('managed.agents.startSession'))

    expect(screen.getByText('managed.agents.startingSession')).toBeTruthy()
    expect(screen.getByText('common.edit').closest('button')?.disabled).toBe(true)
    expect(screen.getByText('common.archive').closest('button')?.disabled).toBe(true)

    await act(async () => {
      resolveSession({ id: 'sess_018f6f42-0a51-7cc4-98c8-4f6f0ca5f123' })
    })
  })
})
