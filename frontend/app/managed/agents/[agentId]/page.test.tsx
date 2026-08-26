import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, type RenderResult } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown>) =>
      key === 'managed.agents.deleteDescription'
        ? `${key}:${String(options?.triggers ?? '')}`
        : key,
  }),
}))

const routerPush = vi.fn()
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: routerPush }) }))

const managedPost = vi.fn(() => Promise.resolve({}))
const managedDelete = vi.fn(() => Promise.resolve())
const toast = vi.fn()
const AGENT_ID = 'agent_018f6f42-0a51-7cc4-98c8-4f6f0ca5f122'
const SESSION_ID = 'sess_018f6f42-0a51-7cc4-98c8-4f6f0ca5f123'
let agentPayload: Record<string, unknown>
let deletePreviewPayload = { sessions: 0, tasks: 0, versions: 0, triggers: 0 }

vi.mock('@/lib/api-client', () => ({
  managedGet: vi.fn((path: string) => {
    if (String(path).includes('/delete_preview')) return Promise.resolve(deletePreviewPayload)
    if (String(path).includes('/versions')) return Promise.resolve({ data: [] })
    if (String(path).includes('/sessions')) return Promise.resolve({ data: [] })
    return Promise.resolve(agentPayload)
  }),
  managedPost: (...args: unknown[]) => managedPost(...args),
  managedDelete: (...args: unknown[]) => managedDelete(...args),
}))
vi.mock('@/hooks/use-toast', () => ({ toast: (...args: unknown[]) => toast(...args) }))

vi.mock('@/lib/managed/agent-response-parsers', () => ({ parseAgentResponse: (x: unknown) => x }))
vi.mock('@/lib/managed/session-response-parsers', () => ({
  parseSessionCreateResponse: (x: unknown) => x,
  parseSessionListResponse: (x: unknown) => x,
}))
vi.mock('@/lib/managed/errors', () => ({
  shouldRetryManagedResourceError: () => false,
  toastOperationError: vi.fn(),
}))
vi.mock('@/lib/managed/request-scope', () => ({
  useManagedRequestScope: () => ({ key: 'scope', orgId: 'o', projectId: 'p' }),
  hasManagedRequestScope: () => true,
  managedRequestOptions: () => ({}),
  managedScopeKey: () => 'scope',
}))
vi.mock('@/stores/managed/project-store', () => ({
  useProjectStore: Object.assign(() => ({}), {
    getState: () => ({ currentOrgId: 'o', currentProjectId: 'p' }),
  }),
}))
vi.mock('@/hooks/managed/use-current-project-read-only', () => ({
  currentProjectAllowsWrite: () => true,
  useCurrentProjectReadOnly: () => false,
}))
vi.mock('@/components/managed/agent/version-diff-view', () => ({ VersionDiffView: () => null }))
vi.mock('@/components/ui/tabs', () => ({
  Tabs: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  TabsList: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  TabsTrigger: ({ children }: { children: ReactNode }) => <button type="button">{children}</button>,
  TabsContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}))
vi.mock('@/components/ui/select', () => ({
  Select: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectTrigger: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectItem: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectValue: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}))
vi.mock('@/components/ui/badge', () => ({
  Badge: ({ children }: { children: ReactNode }) => <span>{children}</span>,
}))
vi.mock('@/components/managed/shared', () => ({
  PageHeader: ({ action }: { action?: ReactNode }) => <div>{action}</div>,
  StatusBadge: () => null,
  MonoId: () => null,
  RelativeTime: () => null,
  DataTable: () => null,
  FilterBar: () => null,
  ResourceErrorState: () => <div>error</div>,
  ConfirmDialog: ({
    open,
    description,
    confirmLabel,
    onConfirm,
  }: {
    open: boolean
    description: string
    confirmLabel: string
    onConfirm: () => void
  }) =>
    open ? (
      <div>
        <div>{description}</div>
        <button type="button" onClick={onConfirm}>
          confirm:{confirmLabel}
        </button>
      </div>
    ) : null,
  withEntityRouteGuard: (Component: (props: never) => ReactNode) => Component,
}))

import AgentDetailPage from './page'

async function renderPage(): Promise<RenderResult> {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const params = Promise.resolve({ agentId: AGENT_ID })
  await params
  let view!: RenderResult
  await act(async () => {
    view = render(
      <QueryClientProvider client={queryClient}>
        <AgentDetailPage params={params} />
      </QueryClientProvider>,
    )
  })
  return view
}

describe('AgentDetailPage action toolbar', () => {
  beforeEach(() => {
    managedPost.mockReset()
    managedPost.mockResolvedValue({})
    managedDelete.mockReset()
    managedDelete.mockResolvedValue()
    routerPush.mockClear()
    toast.mockClear()
    deletePreviewPayload = { sessions: 0, tasks: 0, versions: 0, triggers: 0 }
  })

  it('shows the full toolbar for an active agent', async () => {
    agentPayload = {
      id: AGENT_ID,
      name: 'My Agent',
      archived_at: null,
      updated_at: '2026-08-07T00:00:00Z',
    }
    await renderPage()
    await waitFor(() => expect(screen.getByText('managed.agents.startSession')).toBeTruthy())
    expect(screen.getByText('common.edit')).toBeTruthy()
    expect(screen.getByText('common.archive')).toBeTruthy()
    expect(screen.getByText('common.delete')).toBeTruthy()
    expect(screen.queryByText('common.restore')).toBeNull()
  })

  it('shows only restore and delete for an archived agent', async () => {
    agentPayload = {
      id: AGENT_ID,
      name: 'My Agent',
      archived_at: '2026-08-07T00:00:00Z',
      updated_at: '2026-08-07T00:00:00Z',
    }
    await renderPage()
    await waitFor(() => expect(screen.getByText('common.restore')).toBeTruthy())
    expect(screen.getByText('common.delete')).toBeTruthy()
    expect(screen.queryByText('managed.agents.startSession')).toBeNull()
    expect(screen.queryByText('common.archive')).toBeNull()
  })

  it('calls the unarchive endpoint when restore is confirmed', async () => {
    agentPayload = {
      id: AGENT_ID,
      name: 'My Agent',
      archived_at: '2026-08-07T00:00:00Z',
      updated_at: '2026-08-07T00:00:00Z',
    }
    await renderPage()
    await waitFor(() => expect(screen.getByText('common.restore')).toBeTruthy())
    await act(async () => {
      fireEvent.click(screen.getByText('common.restore'))
    })
    await act(async () => {
      fireEvent.click(screen.getByText('confirm:common.restore'))
    })
    await waitFor(() => expect(managedPost).toHaveBeenCalled())
    expect(String(managedPost.mock.calls[0][0])).toContain(`/agents/${AGENT_ID}/unarchive`)
  })

  it('refreshes into the archived state after archive confirmation closes the dialog', async () => {
    agentPayload = {
      id: AGENT_ID,
      name: 'My Agent',
      archived_at: null,
      updated_at: '2026-08-07T00:00:00Z',
    }
    managedPost.mockImplementationOnce(async () => {
      agentPayload = {
        ...agentPayload,
        archived_at: '2026-08-08T00:00:00Z',
      }
      return {}
    })
    await renderPage()

    await waitFor(() => expect(screen.getByText('common.archive')).toBeTruthy())
    fireEvent.click(screen.getByText('common.archive'))
    fireEvent.click(screen.getByText('confirm:common.archive'))

    await waitFor(() => expect(screen.getByText('common.restore')).toBeTruthy())
    expect(toast).toHaveBeenCalledWith({ title: 'managed.agents.archiveSuccess' })
  })

  it('shows a pending state and prevents duplicate session starts', async () => {
    agentPayload = {
      id: AGENT_ID,
      name: 'My Agent',
      archived_at: null,
      updated_at: '2026-08-07T00:00:00Z',
    }
    let resolveStart!: (value: { id: string }) => void
    managedPost.mockImplementationOnce(
      () =>
        new Promise<{ id: string }>((resolve) => {
          resolveStart = resolve
        }),
    )
    await renderPage()

    fireEvent.click(await screen.findByText('managed.agents.startSession'))

    const pendingLabel = await screen.findByText('managed.agents.startingSession')
    expect(pendingLabel.closest('button')?.disabled).toBe(true)
    fireEvent.click(pendingLabel)
    expect(managedPost).toHaveBeenCalledTimes(1)

    resolveStart({ id: SESSION_ID })
    await waitFor(() => expect(routerPush).toHaveBeenCalledWith(`/managed/sessions/${SESSION_ID}`))
  })

  it('includes triggers in the permanent-delete impact preview', async () => {
    agentPayload = {
      id: AGENT_ID,
      name: 'My Agent',
      archived_at: '2026-08-07T00:00:00Z',
      updated_at: '2026-08-07T00:00:00Z',
    }
    deletePreviewPayload = { sessions: 2, tasks: 4, versions: 3, triggers: 5 }
    await renderPage()

    fireEvent.click(await screen.findByText('common.delete'))

    expect(await screen.findByText('managed.agents.deleteDescription:5')).toBeTruthy()
  })
})
