import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const replaceMock = vi.fn()
const pushMock = vi.fn()
// Real Next useRouter() returns a STABLE reference; a fresh object per render would
// re-fire the shell's router-dependent effects every render (infinite loop / OOM).
const routerMock = { replace: replaceMock, push: pushMock }
let searchParamsValue = new URLSearchParams('')

vi.mock('@/lib/i18n', () => ({ useTranslation: () => ({ t: (k: string) => k }) }))
vi.mock('next/navigation', () => ({
  useRouter: () => routerMock,
  useSearchParams: () => searchParamsValue,
}))
vi.mock('./model-connection-list', () => ({
  ModelConnectionList: ({
    onCreate,
    state,
    onStateChange,
  }: {
    onCreate: () => void
    state?: {
      searchQuery: string
      createdFilter: string
      showArchived: boolean
      pageSize: number
    }
    onStateChange?: (state: {
      searchQuery: string
      createdFilter: string
      showArchived: boolean
      pageSize: number
    }) => void
  }) => (
    <div>
      <button onClick={onCreate}>model-add</button>
      <input
        aria-label="model-search"
        value={state?.searchQuery ?? ''}
        onChange={(event) =>
          onStateChange?.({
            searchQuery: event.target.value,
            createdFilter: state?.createdFilter ?? 'all',
            showArchived: state?.showArchived ?? false,
            pageSize: state?.pageSize ?? 10,
          })
        }
      />
      <button
        onClick={() =>
          onStateChange?.({
            searchQuery: state?.searchQuery ?? '',
            createdFilter: state?.createdFilter ?? 'all',
            showArchived: state?.showArchived ?? false,
            pageSize: 25,
          })
        }
      >
        model-page-size:{state?.pageSize ?? 10}
      </button>
      <button
        onClick={() =>
          onStateChange?.({
            searchQuery: state?.searchQuery ?? '',
            createdFilter: state?.createdFilter ?? 'all',
            showArchived: !(state?.showArchived ?? false),
            pageSize: state?.pageSize ?? 10,
          })
        }
      >
        model-show-archived:{String(state?.showArchived ?? false)}
      </button>
    </div>
  ),
}))
vi.mock('./service-credential-list', () => ({
  ServiceCredentialList: ({
    onCreate,
    state,
    onStateChange,
  }: {
    onCreate: () => void
    state?: {
      searchQuery: string
      createdFilter: string
      showArchived: boolean
      pageSize: number
    }
    onStateChange?: (state: {
      searchQuery: string
      createdFilter: string
      showArchived: boolean
      pageSize: number
    }) => void
  }) => (
    <div>
      <button onClick={onCreate}>service-add</button>
      <button
        onClick={() =>
          onStateChange?.({
            searchQuery: state?.searchQuery ?? '',
            createdFilter: state?.createdFilter ?? 'all',
            showArchived: !(state?.showArchived ?? false),
            pageSize: state?.pageSize ?? 10,
          })
        }
      >
        service-show-archived:{String(state?.showArchived ?? false)}
      </button>
    </div>
  ),
}))
vi.mock('./mcp-credential-group-list', () => ({
  McpCredentialGroupList: ({ onCreate }: { onCreate: () => void }) => (
    <button onClick={onCreate}>vault-add</button>
  ),
}))
vi.mock('./credential-kind-chooser', () => ({
  CredentialKindChooser: ({ open }: { open: boolean }) => (open ? <div>chooser-open</div> : null),
}))
vi.mock('./create-standalone-credential-dialog', () => ({
  CreateStandaloneCredentialDialog: ({
    open,
    initialKind,
    lockKind,
  }: {
    open: boolean
    initialKind?: string
    lockKind?: boolean
  }) => (open ? <div>{`secret-dialog:${initialKind}:${String(lockKind)}`}</div> : null),
}))
vi.mock('./create-credential-group-dialog', () => ({
  CreateCredentialGroupDialog: ({ open }: { open: boolean }) =>
    open ? <div>vault-dialog</div> : null,
}))
vi.mock('@/components/ui/tabs', () => ({
  Tabs: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  TabsList: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  TabsTrigger: ({ children, value }: { children: ReactNode; value: string }) => (
    <button data-tab={value}>{children}</button>
  ),
}))

import { useProjectStore } from '@/stores/managed/project-store'

import { CredentialManagementShell } from './credential-management-shell'

function setProject(
  projectId: string,
  capability: 'read' | 'write' | 'admin' = 'write',
  archivedAt: string | null = null,
) {
  useProjectStore.setState({
    currentOrgId: 'org-a',
    currentProjectId: projectId,
    currentProject: {
      id: projectId,
      org_id: 'org-a',
      name: projectId,
      slug: projectId,
      is_default: true,
      capability,
      archived_at: archivedAt,
    },
    organizations: [],
    projects: [],
  })
}

function Wrap({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

describe('CredentialManagementShell', () => {
  beforeEach(() => {
    replaceMock.mockClear()
    pushMock.mockClear()
    searchParamsValue = new URLSearchParams('')
    setProject('project-a')
  })

  it('normalizes an illegal tab to models via replace', async () => {
    searchParamsValue = new URLSearchParams('tab=bogus')
    render(
      <Wrap>
        <CredentialManagementShell />
      </Wrap>,
    )
    await waitFor(() =>
      expect((replaceMock.mock.calls.at(-1)?.[0] as string) ?? '').toContain('tab=models'),
    )
  })

  it('consumes create=credential-group: opens the group dialog and normalizes tab=mcp', async () => {
    searchParamsValue = new URLSearchParams('tab=models&create=credential-group')
    const { getByText } = render(
      <Wrap>
        <CredentialManagementShell />
      </Wrap>,
    )
    await waitFor(() => expect(getByText('vault-dialog')).toBeTruthy())
    const url = replaceMock.mock.calls.at(-1)![0] as string
    expect(url).toContain('tab=mcp')
    expect(url).not.toContain('create=')
  })

  it('accepts legacy create=vault only as an input compatibility alias', async () => {
    searchParamsValue = new URLSearchParams('tab=models&create=vault')
    const { getByText } = render(
      <Wrap>
        <CredentialManagementShell />
      </Wrap>,
    )
    await waitFor(() => expect(getByText('vault-dialog')).toBeTruthy())
    const url = replaceMock.mock.calls.at(-1)![0] as string
    expect(url).toContain('tab=mcp')
    expect(url).not.toContain('create=')
  })

  it('consumes create=service: opens generic secret dialog locked', async () => {
    searchParamsValue = new URLSearchParams('tab=models&create=service')
    const { getByText } = render(
      <Wrap>
        <CredentialManagementShell />
      </Wrap>,
    )
    await waitFor(() => expect(getByText('secret-dialog:generic:true')).toBeTruthy())
  })

  it('opens a create flow when create=* appears after the shell is already mounted', async () => {
    searchParamsValue = new URLSearchParams('tab=models')
    const view = render(
      <Wrap>
        <CredentialManagementShell />
      </Wrap>,
    )

    searchParamsValue = new URLSearchParams('tab=models&create=service')
    view.rerender(
      <Wrap>
        <CredentialManagementShell />
      </Wrap>,
    )

    await waitFor(() => expect(screen.getByText('secret-dialog:generic:true')).toBeInTheDocument())
    const url = replaceMock.mock.calls.at(-1)![0] as string
    expect(url).toContain('tab=services')
    expect(url).not.toContain('create=')
  })

  it('does NOT open a create dialog from create=* for a read-only project', async () => {
    setProject('project-a', 'read')
    searchParamsValue = new URLSearchParams('tab=services&create=service')
    const { queryByText } = render(
      <Wrap>
        <CredentialManagementShell />
      </Wrap>,
    )
    await waitFor(() => expect(replaceMock).toHaveBeenCalled())
    expect(queryByText('secret-dialog:generic:true')).toBeNull()
    expect(replaceMock.mock.calls.at(-1)![0] as string).not.toContain('create=')
  })

  it('does not render a generic create action that adds a second decision step', () => {
    render(
      <Wrap>
        <CredentialManagementShell />
      </Wrap>,
    )
    expect(screen.queryByRole('button', { name: 'managed.credentials.new' })).toBeNull()
    expect(screen.getByText('model-add')).toBeInTheDocument()
  })

  it('per-tab Add on services tab opens generic locked dialog', async () => {
    searchParamsValue = new URLSearchParams('tab=services')
    const { getByText } = render(
      <Wrap>
        <CredentialManagementShell />
      </Wrap>,
    )
    fireEvent.click(getByText('service-add'))
    await waitFor(() => expect(getByText('secret-dialog:generic:true')).toBeTruthy())
  })

  it('preserves each tab search and page size when the list unmounts', () => {
    searchParamsValue = new URLSearchParams('tab=models')
    const view = render(
      <Wrap>
        <CredentialManagementShell />
      </Wrap>,
    )

    fireEvent.change(screen.getByRole('textbox', { name: 'model-search' }), {
      target: { value: 'openai' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'model-page-size:10' }))

    searchParamsValue = new URLSearchParams('tab=services')
    view.rerender(
      <Wrap>
        <CredentialManagementShell />
      </Wrap>,
    )
    searchParamsValue = new URLSearchParams('tab=models')
    view.rerender(
      <Wrap>
        <CredentialManagementShell />
      </Wrap>,
    )

    expect(screen.getByRole('textbox', { name: 'model-search' })).toHaveValue('openai')
    expect(screen.getByRole('button', { name: 'model-page-size:25' })).toBeInTheDocument()
  })

  it('preserves show-archived independently for each tab when lists unmount', () => {
    searchParamsValue = new URLSearchParams('tab=models')
    const view = render(
      <Wrap>
        <CredentialManagementShell />
      </Wrap>,
    )

    fireEvent.click(screen.getByRole('button', { name: 'model-show-archived:false' }))

    searchParamsValue = new URLSearchParams('tab=services')
    view.rerender(
      <Wrap>
        <CredentialManagementShell />
      </Wrap>,
    )
    expect(screen.getByRole('button', { name: 'service-show-archived:false' })).toBeInTheDocument()

    searchParamsValue = new URLSearchParams('tab=models')
    view.rerender(
      <Wrap>
        <CredentialManagementShell />
      </Wrap>,
    )
    expect(screen.getByRole('button', { name: 'model-show-archived:true' })).toBeInTheDocument()
  })
})
