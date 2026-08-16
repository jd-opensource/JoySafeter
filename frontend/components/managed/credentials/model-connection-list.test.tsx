import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const scopedActionControl = { allowBegin: true }
const scopeMock = { orgId: 'o', projectId: 'p', key: 'o:p' }

vi.mock('@/lib/i18n', () => ({ useTranslation: () => ({ t: (k: string) => k }) }))
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/lib/api-client', () => ({
  managedGet: vi.fn(),
  managedPost: vi.fn(),
  managedDelete: vi.fn(),
}))
vi.mock('@/components/managed/shared', () => ({
  ConfirmDialog: ({
    open,
    confirmLabel,
    onConfirm,
  }: {
    open: boolean
    confirmLabel: string
    onConfirm: () => void
  }) => (open ? <button onClick={onConfirm}>confirm:{confirmLabel}</button> : null),
  DataTable: ({
    data,
    actionMenu,
  }: {
    data: Array<{ id: string; name: string }>
    actionMenu: (row: { id: string; name: string }) => Array<{ label: string; onClick: () => void }>
  }) => (
    <div>
      {data.map((row) => (
        <div key={row.id} data-testid={row.id}>
          <span>{row.name}</span>
          {actionMenu(row).map((item) => (
            <button key={item.label} onClick={item.onClick}>
              {item.label}
            </button>
          ))}
        </div>
      ))}
    </div>
  ),
  FilterBar: ({
    showArchived,
    onArchivedChange,
  }: {
    showArchived?: boolean
    onArchivedChange?: (value: boolean) => void
  }) =>
    onArchivedChange ? (
      <button onClick={() => onArchivedChange(!showArchived)}>
        show-archived:{String(showArchived)}
      </button>
    ) : null,
  MonoId: ({ id }: { id: string }) => <span>{id}</span>,
  RelativeTime: ({ date }: { date: string }) => <span>{date}</span>,
  ResourceErrorState: () => null,
}))
vi.mock('@/lib/managed/request-scope', () => ({
  useManagedRequestScope: () => scopeMock,
  managedRequestOptions: () => ({}),
  hasManagedRequestScope: () => true,
}))
vi.mock('@/hooks/managed/use-current-project-read-only', () => ({
  useCurrentProjectReadOnly: () => false,
  currentProjectAllowsWrite: () => true,
}))
vi.mock('@/hooks/managed/use-scoped-actions', () => ({
  useScopedActions: () => ({
    scopeRef: { current: scopeMock.key },
    requestScopeRef: { current: scopeMock },
    scope: scopeMock,
    readOnly: false,
    beginAction: () =>
      scopedActionControl.allowBegin
        ? { runId: 1, scope: scopeMock.key, requestScope: scopeMock }
        : null,
    isCurrentAction: () => true,
    scopeIsActive: () => scopedActionControl.allowBegin,
    bumpRun: () => {},
  }),
}))
vi.mock('@/hooks/managed/use-llm-catalog', () => ({
  useLlmCatalog: () => ({
    isSuccess: true,
    isError: false,
    data: { version: 'v1' },
    refetch: vi.fn(),
  }),
}))
vi.mock('@/components/managed/shared/compatible-engine-badges', () => ({
  CompatibleEngineBadges: () => null,
}))
vi.mock('./credential-list-panel', () => ({
  CredentialListPanel: ({
    data,
    actionMenu,
    showArchived,
    onArchivedChange,
  }: {
    data: Array<{ id: string; name: string }>
    actionMenu: (row: { id: string; name: string }) => Array<{ label: string; onClick: () => void }>
    showArchived?: boolean
    onArchivedChange?: (value: boolean) => void
  }) => (
    <div>
      {onArchivedChange ? (
        <button onClick={() => onArchivedChange(!showArchived)}>
          show-archived:{String(showArchived)}
        </button>
      ) : null}
      {data.map((row) => (
        <div key={row.id} data-testid={row.id}>
          <span>{row.name}</span>
          {actionMenu(row).map((item) => (
            <button key={item.label} onClick={item.onClick}>
              {item.label}
            </button>
          ))}
        </div>
      ))}
    </div>
  ),
}))

import { managedGet, managedPost } from '@/lib/api-client'

import { ModelConnectionList } from './model-connection-list'

const managedGetMock = managedGet as unknown as ReturnType<typeof vi.fn>
const managedPostMock = managedPost as unknown as ReturnType<typeof vi.fn>
const ACTIVE_ID = 'cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f041'
const ARCHIVED_ID = 'cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f042'

function modelCredential(id: string, archivedAt: string | null, isDefault = false) {
  return {
    id,
    name: archivedAt ? 'Archived model' : 'Active model',
    kind: 'model',
    provider: 'openai',
    protocol: 'responses',
    model: 'gpt-5',
    compatible_engine_ids: [],
    is_default: isDefault,
    archived_at: archivedAt,
    created_at: '2026-08-13T00:00:00Z',
    updated_at: '2026-08-13T00:00:00Z',
  }
}
function Wrap({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

describe('ModelConnectionList', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    scopedActionControl.allowBegin = true
  })

  it('requests only kind=model credentials', async () => {
    managedGetMock.mockResolvedValue({ data: [], has_more: false })
    render(
      <Wrap>
        <ModelConnectionList onCreate={() => {}} />
      </Wrap>,
    )
    await waitFor(() => {
      const cred = managedGetMock.mock.calls.find(([u]) => (u as string).startsWith('/credentials'))
      expect(cred![0]).toContain('kind=model')
      expect(cred![0]).toContain('include_archived=false')
    })
  })

  it('hides archived model connections by default and reveals them through the toggle', async () => {
    managedGetMock.mockResolvedValue({
      data: [
        modelCredential(ACTIVE_ID, null),
        modelCredential(ARCHIVED_ID, '2026-08-12T00:00:00Z'),
      ],
      has_more: false,
    })
    render(
      <Wrap>
        <ModelConnectionList onCreate={() => {}} />
      </Wrap>,
    )

    await screen.findByTestId(ACTIVE_ID)
    expect(screen.queryByTestId(ARCHIVED_ID)).toBeNull()
    fireEvent.click(screen.getByText('show-archived:false'))

    expect(await screen.findByTestId(ARCHIVED_ID)).toBeInTheDocument()
    await waitFor(() =>
      expect(
        managedGetMock.mock.calls.some(([url]) =>
          (url as string).includes('include_archived=true'),
        ),
      ).toBe(true),
    )
  })

  it('archives active model connections and restores archived ones', async () => {
    managedGetMock.mockResolvedValue({
      data: [
        modelCredential(ACTIVE_ID, null),
        modelCredential(ARCHIVED_ID, '2026-08-12T00:00:00Z'),
      ],
      has_more: false,
    })
    managedPostMock.mockResolvedValue({})
    render(
      <Wrap>
        <ModelConnectionList
          onCreate={() => {}}
          state={{ searchQuery: '', createdFilter: 'all', showArchived: true, pageSize: 10 }}
          onStateChange={() => {}}
        />
      </Wrap>,
    )

    const activeRow = await screen.findByTestId(ACTIVE_ID)
    fireEvent.click(within(activeRow).getByText('common.archive'))
    expect(managedPostMock).not.toHaveBeenCalled()
    fireEvent.click(screen.getByText('confirm:common.archive'))
    await waitFor(() =>
      expect(managedPostMock).toHaveBeenCalledWith(
        `/credentials/${ACTIVE_ID}/archive`,
        {},
        expect.anything(),
      ),
    )

    const archivedRow = screen.getByTestId(ARCHIVED_ID)
    fireEvent.click(within(archivedRow).getByText('common.restore'))
    fireEvent.click(screen.getByText('confirm:common.restore'))
    await waitFor(() =>
      expect(managedPostMock).toHaveBeenCalledWith(
        `/credentials/${ARCHIVED_ID}/restore`,
        {},
        expect.anything(),
      ),
    )
  })

  it('does not offer set-default for archived model connections', async () => {
    managedGetMock.mockResolvedValue({
      data: [modelCredential(ARCHIVED_ID, '2026-08-12T00:00:00Z')],
      has_more: false,
    })
    render(
      <Wrap>
        <ModelConnectionList
          onCreate={() => {}}
          state={{ searchQuery: '', createdFilter: 'all', showArchived: true, pageSize: 10 }}
          onStateChange={() => {}}
        />
      </Wrap>,
    )

    const archivedRow = await screen.findByTestId(ARCHIVED_ID)
    expect(within(archivedRow).queryByText('managed.secrets.setDefault')).toBeNull()
  })

  it('does not submit an old lifecycle target after the managed scope changes', async () => {
    managedGetMock.mockResolvedValue({
      data: [modelCredential(ACTIVE_ID, null)],
      has_more: false,
    })
    render(
      <Wrap>
        <ModelConnectionList onCreate={() => {}} />
      </Wrap>,
    )

    const activeRow = await screen.findByTestId(ACTIVE_ID)
    fireEvent.click(within(activeRow).getByText('common.archive'))
    scopedActionControl.allowBegin = false
    fireEvent.click(screen.getByText('confirm:common.archive'))

    expect(managedPostMock).not.toHaveBeenCalled()
  })
})
