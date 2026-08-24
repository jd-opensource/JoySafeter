/**
 * Task 13 — Capability-parity + isolation matrix (§6 acceptance gate).
 *
 * This file adds NO product code. It is the single gate proving that the split
 * `/managed/credentials` surface (models / services / mcp) preserves every
 * capability of the legacy secrets+vaults pages and enforces kind isolation,
 * using the rev4 lifecycle/list-filter capability set. Archived Model/Service
 * rows are hidden by default and become actionable only after the tab's
 * show-archived toggle is enabled.
 *
 * Guardrails honoured:
 *  - EVERY next/navigation useRouter mock returns a STABLE module-level object
 *    (routerMock). The shell and CredentialDetail have router-dependent effects;
 *    an unstable router = infinite render loop = OOM.
 *  - ALL credential/vault fixtures are full strict-parser-valid objects built
 *    from a single credential/group fixture helper and strict boundary parsers.
 *  - Heavy deps (useLlmCatalog, api-client, request-scope, ui/* primitives,
 *    PageHeader, DataTable, dialogs) are mocked rather than pulling real graphs.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// Local mirror of the shared MenuItem shape (the real type lives in the mocked
// @/components/managed/shared module; declaring it locally avoids an import
// from a module we mock — and the import/order churn that comes with it).
interface MenuItem {
  label: string
  onClick: () => void
  destructive?: boolean
  icon?: ReactNode
  separator?: boolean
}

// ── Stable navigation mock (guardrail #1) ────────────────────────────────────
const replaceMock = vi.fn()
const pushMock = vi.fn()
const routerMock = { replace: replaceMock, push: pushMock }
let searchParamsValue = new URLSearchParams('')

// Mutable, per-test toggles read by the mocked hooks below.
let readOnlyValue = false
// Stable scope object — a fresh object per render would re-fire scope-keyed
// effects (useScopedActions / McpCredentialGroupDetail) every render = infinite loop / OOM.
const scopeMock = { orgId: 'o', projectId: 'p', key: 'o:p' }

vi.mock('@/lib/i18n', () => ({ useTranslation: () => ({ t: (k: string) => k }) }))
vi.mock('next/navigation', () => ({
  useRouter: () => routerMock,
  useSearchParams: () => searchParamsValue,
}))
vi.mock('@/lib/api-client', () => ({
  managedGet: vi.fn(),
  managedPost: vi.fn(),
  managedPatch: vi.fn(),
  managedDelete: vi.fn(),
}))
vi.mock('@/lib/managed/request-scope', () => ({
  useManagedRequestScope: () => scopeMock,
  managedRequestOptions: () => ({}),
  hasManagedRequestScope: () => true,
  managedScopeKey: () => 'o:p',
}))
vi.mock('@/hooks/managed/use-current-project-read-only', () => ({
  useCurrentProjectReadOnly: () => readOnlyValue,
  currentProjectAllowsWrite: () => !readOnlyValue,
}))
// useScopedActions is used by McpCredentialGroupList. Return a STABLE object so its scope
// key never appears to change between renders (guardrail #1 for effects).
vi.mock('@/hooks/managed/use-scoped-actions', () => ({
  useScopedActions: () => ({
    scopeRef: { current: 'o:p' },
    requestScopeRef: { current: scopeMock },
    scope: scopeMock,
    readOnly: readOnlyValue,
    beginAction: () => ({ runId: 1, scope: 'o:p', requestScope: scopeMock }),
    isCurrentAction: () => true,
    scopeIsActive: () => true,
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
vi.mock('@/stores/managed/project-store', () => ({
  useProjectStore: Object.assign(() => false, {
    getState: () => ({ currentOrgId: 'o', currentProjectId: 'p' }),
  }),
}))

// Lightweight shared-primitive stubs. The DataTable stub resolves each row's
// actionMenu and renders the labels straight into the DOM (rather than driving
// the Radix dropdown, which only mounts items on open). Tests assert on those
// nodes — presence via getByTestId(`action-<label>`) and absence via
// queryByTestId — with NO module-level mutable state (keeps the
// react-hooks/immutability lint rule satisfied).
vi.mock('@/components/managed/shared', () => {
  interface StubTableProps<T> {
    data: T[]
    actionMenu?: (row: T) => MenuItem[]
    onRowClick?: (row: T) => void
    emptyMessage?: string
  }
  function DataTable<T>({ data, actionMenu, emptyMessage }: StubTableProps<T>) {
    const actionsByRow = data.map((row) => (actionMenu ? actionMenu(row) : []))
    return (
      <div data-testid="datatable" data-rows={actionsByRow.length}>
        {data.length === 0 ? <div>{emptyMessage}</div> : null}
        {actionsByRow.map((actions, i) => (
          <div key={i} data-testid={`row-${i}`} data-action-count={actions.length}>
            {actions.length === 0 ? (
              <span data-testid={`row-${i}-no-actions`} />
            ) : (
              actions.map((a) => (
                <button key={a.label} data-testid={`action-${a.label}`} onClick={a.onClick}>
                  {a.label}
                </button>
              ))
            )}
          </div>
        ))}
      </div>
    )
  }
  const PageHeader = ({
    title,
    action,
    breadcrumb,
  }: {
    title: string
    action?: ReactNode
    breadcrumb?: { label: string; to?: string }[]
  }) => (
    <div data-testid="page-header">
      <span>{title}</span>
      {(breadcrumb ?? []).map((c, i) =>
        c.to ? (
          <a key={i} data-testid="breadcrumb-link" href={c.to}>
            {c.label}
          </a>
        ) : null,
      )}
      <div data-testid="page-action">{action}</div>
    </div>
  )
  const FilterBar = ({
    showArchived,
    onArchivedChange,
  }: {
    showArchived?: boolean
    onArchivedChange?: (v: boolean) => void
  }) => (
    <div data-testid="filter-bar">
      {onArchivedChange ? (
        <button data-testid="show-archived-toggle" onClick={() => onArchivedChange(!showArchived)}>
          toggle-archived
        </button>
      ) : null}
    </div>
  )
  const passthrough = ({ children }: { children?: ReactNode }) => <div>{children}</div>
  return {
    DataTable,
    PageHeader,
    FilterBar,
    MonoId: ({ id }: { id: string }) => <span>{id}</span>,
    RelativeTime: () => <span>time</span>,
    StatusBadge: ({ status }: { status: string }) => <span>{status}</span>,
    ResourceErrorState: ({ onBack }: { onBack?: () => void }) => (
      <button data-testid="error-back" onClick={onBack}>
        error
      </button>
    ),
    ConfirmDialog: ({ open, title }: { open: boolean; title: string }) =>
      open ? <div data-testid={`dialog-${title}`} /> : null,
    FormFieldLabel: passthrough,
  }
})
vi.mock('@/components/managed/shared/compatible-engine-badges', () => ({
  CompatibleEngineBadges: () => null,
}))
vi.mock('./credential-list-panel', () => ({
  CredentialListPanel: ({
    data,
    actionMenu,
    createAction,
    showArchived,
    onArchivedChange,
    emptyState,
  }: {
    data: Array<{ id?: string }>
    actionMenu?: (row: { id?: string }) => MenuItem[]
    createAction?: { label: string; onClick: () => void }
    showArchived?: boolean
    onArchivedChange?: (value: boolean) => void
    emptyState?: { title: string }
  }) => {
    const actionsByRow = data.map((row) => (actionMenu ? actionMenu(row) : []))
    return (
      <div data-testid="datatable" data-rows={actionsByRow.length}>
        {createAction ? <button onClick={createAction.onClick}>{createAction.label}</button> : null}
        {onArchivedChange ? (
          <button
            data-testid="show-archived-toggle"
            onClick={() => onArchivedChange(!showArchived)}
          >
            toggle-archived
          </button>
        ) : null}
        {data.length === 0 ? <div>{emptyState?.title}</div> : null}
        {actionsByRow.map((actions, index) => (
          <div key={index} data-testid={`row-${index}`} data-action-count={actions.length}>
            {actions.length === 0 ? (
              <span data-testid={`row-${index}-no-actions`} />
            ) : (
              actions.map((action) => (
                <button
                  key={action.label}
                  data-testid={`action-${action.label}`}
                  onClick={action.onClick}
                >
                  {action.label}
                </button>
              ))
            )}
          </div>
        ))}
      </div>
    )
  },
}))
vi.mock('@/components/managed/llm/llm-catalog-page-state', () => ({
  LlmCatalogPageState: ({ state }: { state: string }) => <div>catalog:{state}</div>,
}))
// Minimal <Button> that renders its children (so add-labels are queryable text).
vi.mock('@/components/ui/button', () => ({
  Button: ({ children, onClick }: { children?: ReactNode; onClick?: () => void }) => (
    <button onClick={onClick}>{children}</button>
  ),
}))
vi.mock('@/components/ui/badge', () => ({
  Badge: ({ children }: { children?: ReactNode }) => <span>{children}</span>,
}))
vi.mock('@/components/ui/input', () => ({
  Input: (props: Record<string, unknown>) => <input {...props} />,
}))
vi.mock('@/components/ui/alert', () => ({
  Alert: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  AlertDescription: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
}))
vi.mock('@/components/ui/tabs', () => ({
  // Expose the shell's onValueChange via an inline test control (closure over
  // the prop — no outer mutable state). Clicking it exercises goToTab → push.
  Tabs: ({
    children,
    onValueChange,
  }: {
    children: ReactNode
    value: string
    onValueChange: (v: string) => void
  }) => (
    <div>
      <button data-testid="goto-services" onClick={() => onValueChange('services')}>
        goto-services
      </button>
      {children}
    </div>
  ),
  TabsList: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  TabsTrigger: ({ children, value }: { children: ReactNode; value: string }) => (
    <button data-tab={value}>{children}</button>
  ),
}))
// Shell children/dialogs stubbed so shell routing tests stay light.
vi.mock('./credential-kind-chooser', () => ({
  CredentialKindChooser: ({ open }: { open: boolean }) => (open ? <div>chooser-open</div> : null),
}))
vi.mock('./create-standalone-credential-dialog', () => ({
  CreateStandaloneCredentialDialog: ({ open }: { open: boolean }) =>
    open ? <div>secret-dialog</div> : null,
}))
vi.mock('./create-credential-group-dialog', () => ({
  CreateCredentialGroupDialog: ({ open }: { open: boolean }) =>
    open ? <div>vault-dialog</div> : null,
}))
vi.mock('./create-mcp-member-dialog', () => ({
  CreateMcpMemberDialog: ({ open }: { open: boolean }) =>
    open ? <div data-testid="add-credential-dialog">add-credential</div> : null,
}))
// NOTE: model-connection-detail / service-credential-detail are intentionally
// NOT mocked — the kind-correct-back tests render the REAL detail components,
// and the orphan-guard test uses kind=mcp so CredentialDetail never dispatches
// to them.

import { managedGet } from '@/lib/api-client'

import { CredentialDetail } from './credential-detail'
import { CredentialManagementShell } from './credential-management-shell'
import { McpCredentialGroupDetail } from './mcp-credential-group-detail'
import { McpCredentialGroupList } from './mcp-credential-group-list'
import { ModelConnectionDetail } from './model-connection-detail'
import { ModelConnectionList } from './model-connection-list'
import { ServiceCredentialDetail } from './service-credential-detail'
import { ServiceCredentialList } from './service-credential-list'

const managedGetMock = managedGet as unknown as ReturnType<typeof vi.fn>

const CRED = 'cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f001'
const GROUP = 'credgrp_018f6f42-0a51-7cc4-98c8-4f6f0ca5f040'

// Full strict-parser-valid Credential fixture (guardrail #2). Every key present;
// no extras — parseCredentialResponse uses `.strict()` zod.
function secretBase(overrides: Record<string, unknown> = {}) {
  return {
    id: CRED,
    name: 'x',
    kind: 'model',
    provider: null,
    protocol: null,
    model: null,
    compatible_engine_ids: [],
    is_default: false,
    mcp_server_url: null,
    group_id: null,
    auth_scheme: null,
    archived_at: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    data: {},
    ...overrides,
  }
}
// Vault fixture (parseVaultResponse is a plain cast, but keep it realistic).
function vaultBase(overrides: Record<string, unknown> = {}) {
  return {
    id: GROUP,
    name: 'v',
    description: null,
    archived_at: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}
// CredentialDetail passed directly to a *Detail component (already parsed shape).
function secretDetail(overrides: Record<string, unknown> = {}) {
  return { ...secretBase(overrides) } as never
}

function Wrap({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

/** Resolve the list page after its (catalog-gated) query settles. When
 *  `expectRows` is set, wait until the DataTable stub reflects that many rows
 *  (the async query has resolved and DataTable re-rendered). */
async function renderList(node: ReactNode, expectRows = 0) {
  const utils = render(<Wrap>{node}</Wrap>)
  await waitFor(() => expect(utils.getByTestId('datatable')).toBeTruthy())
  if (expectRows > 0) {
    await waitFor(() =>
      expect(utils.getByTestId('datatable').getAttribute('data-rows')).toBe(String(expectRows)),
    )
  }
  return utils
}

const credUrls = () => managedGetMock.mock.calls.map(([u]) => u as string)
const calledCatalog = () => credUrls().some((u) => u.startsWith('/llm/catalog'))

beforeEach(() => {
  managedGetMock.mockReset()
  replaceMock.mockClear()
  pushMock.mockClear()
  searchParamsValue = new URLSearchParams('')
  readOnlyValue = false
})

// ─────────────────────────────────────────────────────────────────────────────
// Isolation
// ─────────────────────────────────────────────────────────────────────────────
describe('isolation', () => {
  it('ModelConnectionList fetches only kind=model', async () => {
    managedGetMock.mockResolvedValue({ data: [], has_more: false })
    await renderList(<ModelConnectionList onCreate={() => {}} />)
    await waitFor(() =>
      expect(credUrls().some((u) => u.startsWith('/credentials') && u.includes('kind=model'))).toBe(
        true,
      ),
    )
  })

  it('ServiceCredentialList fetches only kind=service and never the LLM catalog', async () => {
    managedGetMock.mockResolvedValue({ data: [], has_more: false })
    await renderList(<ServiceCredentialList onCreate={() => {}} />)
    await waitFor(() =>
      expect(
        credUrls().some((u) => u.startsWith('/credentials') && u.includes('kind=service')),
      ).toBe(true),
    )
    expect(calledCatalog()).toBe(false)
  })

  it('McpCredentialGroupList lists /credential-groups and never the LLM catalog', async () => {
    managedGetMock.mockResolvedValue({ data: [], has_more: false })
    await renderList(<McpCredentialGroupList onCreate={() => {}} />)
    await waitFor(() =>
      expect(credUrls().some((u) => u.startsWith('/credential-groups'))).toBe(true),
    )
    expect(calledCatalog()).toBe(false)
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// Reader role — all three tabs + shell
// ─────────────────────────────────────────────────────────────────────────────
describe('reader role', () => {
  beforeEach(() => {
    readOnlyValue = true
  })

  it('ModelConnectionList: no add button, row yields no actions', async () => {
    managedGetMock.mockResolvedValue({ data: [secretBase({ kind: 'model' })], has_more: false })
    const { queryByText, getByTestId } = await renderList(
      <ModelConnectionList onCreate={() => {}} />,
      1,
    )
    expect(queryByText('managed.credentials.addModelConnection')).toBeNull()
    expect(getByTestId('row-0').getAttribute('data-action-count')).toBe('0')
    expect(getByTestId('row-0-no-actions')).toBeTruthy()
  })

  it('ServiceCredentialList: no add button, row yields no actions', async () => {
    managedGetMock.mockResolvedValue({ data: [secretBase({ kind: 'service' })], has_more: false })
    const { queryByText, getByTestId } = await renderList(
      <ServiceCredentialList onCreate={() => {}} />,
      1,
    )
    expect(queryByText('managed.credentials.addServiceCredential')).toBeNull()
    expect(getByTestId('row-0').getAttribute('data-action-count')).toBe('0')
  })

  it('McpCredentialGroupList: no add button, row yields no actions', async () => {
    managedGetMock.mockResolvedValue({ data: [vaultBase()], has_more: false })
    const { queryByText, getByTestId } = await renderList(
      <McpCredentialGroupList onCreate={() => {}} />,
      1,
    )
    expect(queryByText('managed.credentials.newMcpCredentialGroup')).toBeNull()
    expect(getByTestId('row-0').getAttribute('data-action-count')).toBe('0')
  })

  it('shell renders no global "New" button when read-only', async () => {
    searchParamsValue = new URLSearchParams('tab=models')
    managedGetMock.mockResolvedValue({ data: [], has_more: false })
    const { queryByText } = render(
      <Wrap>
        <CredentialManagementShell />
      </Wrap>,
    )
    await waitFor(() => expect(queryByText('managed.credentials.new')).toBeNull())
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// Per-kind capability sets (REV3 — assert legal active/archived actions)
// ─────────────────────────────────────────────────────────────────────────────
describe('model capability', () => {
  it('active non-default model row exposes set-default + archive + delete, but no test-connection', async () => {
    managedGetMock.mockResolvedValue({
      data: [secretBase({ kind: 'model', is_default: false })],
      has_more: false,
    })
    const { getByTestId, queryByTestId, queryAllByTestId } = await renderList(
      <ModelConnectionList onCreate={() => {}} />,
      1,
    )
    expect(getByTestId('action-managed.llm.setAsProtocolDefault')).toBeTruthy()
    expect(getByTestId('action-common.archive')).toBeTruthy()
    expect(getByTestId('action-common.delete')).toBeTruthy()
    expect(queryByTestId('action-managed.credentials.groups.archiveCredentialGroup')).toBeNull()
    // No test-connection action of any label form.
    expect(
      queryAllByTestId(/^action-/).some((n) =>
        (n.getAttribute('data-testid') ?? '').toLowerCase().includes('test'),
      ),
    ).toBe(false)
  })

  it('default model row: no set-default offered (already default), still deletable', async () => {
    managedGetMock.mockResolvedValue({
      data: [secretBase({ kind: 'model', is_default: true })],
      has_more: false,
    })
    const { getByTestId, queryByTestId } = await renderList(
      <ModelConnectionList onCreate={() => {}} />,
      1,
    )
    expect(queryByTestId('action-managed.llm.setAsProtocolDefault')).toBeNull()
    expect(getByTestId('action-common.delete')).toBeTruthy()
  })

  it('archived model row exposes restore + delete and never set-default', async () => {
    managedGetMock.mockResolvedValue({
      data: [secretBase({ kind: 'model', archived_at: '2026-08-12T00:00:00Z' })],
      has_more: false,
    })
    const { getByTestId, queryByTestId } = await renderList(
      <ModelConnectionList onCreate={() => {}} />,
    )
    expect(getByTestId('datatable').getAttribute('data-rows')).toBe('0')
    fireEvent.click(getByTestId('show-archived-toggle'))
    await waitFor(() => expect(getByTestId('datatable').getAttribute('data-rows')).toBe('1'))
    expect(getByTestId('action-common.restore')).toBeTruthy()
    expect(getByTestId('action-common.delete')).toBeTruthy()
    expect(queryByTestId('action-managed.llm.setAsProtocolDefault')).toBeNull()
    expect(queryByTestId('action-common.archive')).toBeNull()
  })
})

describe('service capability', () => {
  it('active service row exposes archive + delete and no set-default', async () => {
    managedGetMock.mockResolvedValue({
      data: [secretBase({ kind: 'service' })],
      has_more: false,
    })
    const { getByTestId, queryByTestId } = await renderList(
      <ServiceCredentialList onCreate={() => {}} />,
      1,
    )
    expect(getByTestId('action-common.archive')).toBeTruthy()
    expect(getByTestId('action-common.delete')).toBeTruthy()
    expect(queryByTestId('action-managed.llm.setAsProtocolDefault')).toBeNull()
    expect(queryByTestId('action-managed.credentials.groups.archiveCredentialGroup')).toBeNull()
  })

  it('archived service row exposes restore + delete and no archive', async () => {
    managedGetMock.mockResolvedValue({
      data: [secretBase({ kind: 'service', archived_at: '2026-08-12T00:00:00Z' })],
      has_more: false,
    })
    const { getByTestId, queryByTestId } = await renderList(
      <ServiceCredentialList onCreate={() => {}} />,
    )
    expect(getByTestId('datatable').getAttribute('data-rows')).toBe('0')
    fireEvent.click(getByTestId('show-archived-toggle'))
    await waitFor(() => expect(getByTestId('datatable').getAttribute('data-rows')).toBe('1'))
    expect(getByTestId('action-common.restore')).toBeTruthy()
    expect(getByTestId('action-common.delete')).toBeTruthy()
    expect(queryByTestId('action-common.archive')).toBeNull()
  })
})

describe('mcp capability', () => {
  it('active vault row exposes archive + delete', async () => {
    managedGetMock.mockResolvedValue({
      data: [vaultBase({ archived_at: null })],
      has_more: false,
    })
    const { getByTestId } = await renderList(<McpCredentialGroupList onCreate={() => {}} />, 1)
    expect(getByTestId('action-managed.credentials.groups.archiveCredentialGroup')).toBeTruthy()
    expect(getByTestId('action-common.delete')).toBeTruthy()
  })

  it('opens the archive dialog even when the paginated query cache lookup misses the row', async () => {
    managedGetMock.mockResolvedValue({
      data: [vaultBase({ archived_at: null })],
      has_more: false,
    })
    const { getByTestId } = await renderList(<McpCredentialGroupList onCreate={() => {}} />, 1)
    const cacheSpy = vi.spyOn(QueryClient.prototype, 'getQueriesData').mockReturnValue([])

    fireEvent.click(getByTestId('action-managed.credentials.groups.archiveCredentialGroup'))

    expect(getByTestId('dialog-managed.credentials.groups.archiveTitle')).toBeTruthy()
    cacheSpy.mockRestore()
  })

  it('archived vault row is hidden by default and exposes no actions', async () => {
    managedGetMock.mockResolvedValue({
      data: [vaultBase({ archived_at: '2026-02-01T00:00:00Z' })],
      has_more: false,
    })
    const { getByTestId } = await renderList(<McpCredentialGroupList onCreate={() => {}} />)
    // Archived vaults are filtered out when show-archived is off, so no rows.
    expect(getByTestId('datatable').getAttribute('data-rows')).toBe('0')
  })

  it('McpCredentialGroupDetail renders member controls for an active writable group', async () => {
    managedGetMock.mockImplementation(async (url: string) =>
      url.includes('/members')
        ? {
            data: [
              secretBase({
                kind: 'mcp',
                group_id: GROUP,
                name: 'm1',
                mcp_server_url: 'https://x',
                auth_scheme: 'static_bearer',
              }),
            ],
            has_more: false,
          }
        : vaultBase({ archived_at: null }),
    )
    const { getByText, getByTestId } = render(
      <Wrap>
        <McpCredentialGroupDetail credentialGroupId={GROUP as never} />
      </Wrap>,
    )
    // Add-Credential control (writer, active vault).
    await waitFor(() => expect(getByText('managed.credentials.groups.addCredential')).toBeTruthy())
    // Member row exposes the credential-archive action.
    await waitFor(() =>
      expect(getByTestId('action-managed.credentials.groups.credArchiveTitle')).toBeTruthy(),
    )
    // Show-archived toggle present.
    expect(getByTestId('show-archived-toggle')).toBeTruthy()
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// Detail kind-invariant (orphan guard — Blocker B3)
// ─────────────────────────────────────────────────────────────────────────────
describe('detail kind-invariant', () => {
  it('orphan mcp credential (no group_id) shows orphan copy and does NOT redirect', async () => {
    managedGetMock.mockResolvedValue(secretBase({ kind: 'mcp', group_id: null }))
    const { getByText } = render(
      <Wrap>
        <CredentialDetail credentialId={CRED as never} />
      </Wrap>,
    )
    await waitFor(() => expect(getByText('managed.credentials.orphanCredential')).toBeTruthy())
    expect(replaceMock).not.toHaveBeenCalled()
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// Routing (shell)
// ─────────────────────────────────────────────────────────────────────────────
describe('routing', () => {
  it('default (no ?tab=) renders the models list', async () => {
    searchParamsValue = new URLSearchParams('')
    managedGetMock.mockResolvedValue({ data: [], has_more: false })
    render(
      <Wrap>
        <CredentialManagementShell />
      </Wrap>,
    )
    // Models list issues the kind=model fetch; the other tabs are not mounted.
    await waitFor(() =>
      expect(credUrls().some((u) => u.startsWith('/credentials') && u.includes('kind=model'))).toBe(
        true,
      ),
    )
    expect(credUrls().some((u) => u.includes('kind=service'))).toBe(false)
    expect(credUrls().some((u) => u.startsWith('/credential-groups'))).toBe(false)
  })

  it('illegal ?tab= is normalized to models via router.replace', async () => {
    searchParamsValue = new URLSearchParams('tab=bogus')
    managedGetMock.mockResolvedValue({ data: [], has_more: false })
    render(
      <Wrap>
        <CredentialManagementShell />
      </Wrap>,
    )
    await waitFor(() =>
      expect((replaceMock.mock.calls.at(-1)?.[0] as string) ?? '').toContain('tab=models'),
    )
  })

  it('a real tab change triggers router.push', async () => {
    searchParamsValue = new URLSearchParams('tab=models')
    managedGetMock.mockResolvedValue({ data: [], has_more: false })
    const { getByTestId } = render(
      <Wrap>
        <CredentialManagementShell />
      </Wrap>,
    )
    // The mocked Tabs exposes an inline control wired to the shell's
    // onValueChange; clicking it drives goToTab('services') → router.push.
    fireEvent.click(getByTestId('goto-services'))
    await waitFor(() =>
      expect(pushMock.mock.calls.some(([u]) => (u as string).includes('tab=services'))).toBe(true),
    )
  })

  it('create=service is consumed, tab remains present after create is stripped', async () => {
    searchParamsValue = new URLSearchParams('tab=models&create=service')
    managedGetMock.mockResolvedValue({ data: [], has_more: false })
    render(
      <Wrap>
        <CredentialManagementShell />
      </Wrap>,
    )
    await waitFor(() => expect(replaceMock).toHaveBeenCalled())
    const url = replaceMock.mock.calls.at(-1)![0] as string
    expect(url).not.toContain('create=')
    expect(url).toContain('tab=services')
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// Kind-correct back (breadcrumb targets)
// ─────────────────────────────────────────────────────────────────────────────
describe('kind-correct back', () => {
  it('ModelConnectionDetail breadcrumb back target is ?tab=models', async () => {
    const { getAllByTestId } = render(
      <Wrap>
        <ModelConnectionDetail
          credential={secretDetail({ kind: 'model', provider: null, protocol: null })}
        />
      </Wrap>,
    )
    await waitFor(() =>
      expect(
        getAllByTestId('breadcrumb-link').some(
          (a) => a.getAttribute('href') === '/managed/credentials?tab=models',
        ),
      ).toBe(true),
    )
  })

  it('ServiceCredentialDetail breadcrumb back target is ?tab=services', async () => {
    const { getAllByTestId } = render(
      <Wrap>
        <ServiceCredentialDetail credential={secretDetail({ kind: 'service' })} />
      </Wrap>,
    )
    await waitFor(() =>
      expect(
        getAllByTestId('breadcrumb-link').some(
          (a) => a.getAttribute('href') === '/managed/credentials?tab=services',
        ),
      ).toBe(true),
    )
  })

  it('McpCredentialGroupDetail breadcrumb back target is ?tab=mcp', async () => {
    managedGetMock.mockImplementation(async (url: string) =>
      url.includes('/members') ? { data: [], has_more: false } : vaultBase({ archived_at: null }),
    )
    const { getAllByTestId } = render(
      <Wrap>
        <McpCredentialGroupDetail credentialGroupId={GROUP as never} />
      </Wrap>,
    )
    await waitFor(() =>
      expect(
        getAllByTestId('breadcrumb-link').some(
          (a) => a.getAttribute('href') === '/managed/credentials?tab=mcp',
        ),
      ).toBe(true),
    )
  })
})
