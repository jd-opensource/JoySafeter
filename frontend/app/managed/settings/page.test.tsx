import { act, cleanup, fireEvent, render, within } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

const mutate = vi.fn()
const invalidateQueries = vi.fn()
const setContext = vi.fn()
const setCurrentOrg = vi.fn()
const setCurrentProject = vi.fn()
const mutationOptions: Array<{
  onSuccess?: (result: unknown, variables: Record<string, unknown>) => void
}> = []
const organizations = [
  {
    id: 'org-a',
    name: 'Organization A',
    slug: 'org-a',
    role: 'owner',
    owner_name: 'Current User',
    owner_email: 'current@example.com',
  },
  {
    id: 'org-b',
    name: 'Organization B',
    slug: 'org-b',
    role: 'member',
    owner_name: 'Shared Owner',
    owner_email: 'owner@example.com',
  },
]
const me = {
  organization: organizations[0],
  organizations: [],
}
const storedOrganizations = [
  ...organizations,
  {
    id: 'org-c',
    name: 'Organization C',
    slug: 'org-c',
    role: 'admin',
    owner_name: 'Another Owner',
    owner_email: 'another@example.com',
  },
]

vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({
    invalidateQueries,
    getQueryData: vi.fn(),
  }),
  useQuery: ({ queryKey }: { queryKey: unknown[] }) =>
    queryKey[0] === 'auth-me' ? { data: me } : { data: [], isLoading: false },
  useMutation: (options: {
    onSuccess?: (result: unknown, variables: Record<string, unknown>) => void
  }) => {
    mutationOptions.push(options)
    return { mutate, isPending: false }
  },
}))

vi.mock('@/hooks/managed/use-paginated-list', () => ({
  usePaginatedList: () => ({
    data: organizations,
    isLoading: false,
    isFetching: false,
    hasNext: false,
    hasPrev: false,
    page: 1,
    pageSize: 20,
    pageSizeOptions: [20],
    goNext: vi.fn(),
    goPrev: vi.fn(),
    goToPage: vi.fn(),
    setPageSize: vi.fn(),
    reset: vi.fn(),
  }),
}))

const projectStore = Object.assign(
  (
    selector: (state: {
      currentOrgId: string
      currentProjectId: string
      organizations: typeof storedOrganizations
    }) => unknown,
  ) =>
    selector({
      currentOrgId: 'org-a',
      currentProjectId: 'project-a',
      organizations: storedOrganizations,
    }),
  {
    getState: () => ({
      currentOrgId: 'org-a',
      currentProjectId: 'project-a',
      organizations: storedOrganizations,
      setContext,
      setCurrentOrg,
      setCurrentProject,
    }),
  },
)

vi.mock('@/stores/managed/project-store', () => ({ useProjectStore: projectStore }))

vi.mock('next/link', () => ({
  default: ({ href, children, ...props }: { href: string; children: ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}))

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock('@/components/managed/shared', () => ({
  DataTable: ({
    columns,
    data,
    actionMenu,
    mobileCard,
  }: {
    columns: Array<{ key: string; render: (row: { id: string }) => ReactNode }>
    data: Array<{ id: string }>
    actionMenu?: (row: { id: string }) => Array<{ label: string }>
    mobileCard?: (row: { id: string }) => ReactNode
  }) => (
    <div>
      <div data-testid="desktop-list">
        {data.map((row) => (
          <div key={row.id}>
            {columns.map((column) => (
              <div key={column.key}>{column.render(row)}</div>
            ))}
            {(actionMenu?.(row) ?? []).map((item) => (
              <span key={item.label}>{item.label}</span>
            ))}
          </div>
        ))}
      </div>
      <div data-testid="mobile-list">
        {data.map((row) => (
          <div key={row.id}>{mobileCard?.(row)}</div>
        ))}
      </div>
    </div>
  ),
  FilterBar: () => null,
  MonoId: ({ id }: { id: string }) => <span>{id}</span>,
  RelativeTime: () => null,
  PageHeader: ({ action }: { action?: ReactNode }) => <div>{action}</div>,
}))

vi.mock('@/components/ui/dialog', () => ({
  Dialog: ({ open, children }: { open: boolean; children: ReactNode }) =>
    open ? <div>{children}</div> : null,
  DialogContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogHeader: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children: ReactNode }) => <h2>{children}</h2>,
  DialogDescription: ({ children }: { children: ReactNode }) => <p>{children}</p>,
  DialogFooter: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}))

vi.mock('@/lib/api-client', () => ({
  managedGet: vi.fn(),
  managedPost: vi.fn(),
  managedPut: vi.fn(),
  managedDelete: vi.fn(),
}))

vi.mock('@/lib/query-client-lifecycle', () => ({ resetManagedScopeQueries: vi.fn() }))

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement

describe('OrganizationPage', () => {
  afterEach(() => {
    cleanup()
    mutate.mockClear()
    invalidateQueries.mockClear()
    setContext.mockClear()
    setCurrentOrg.mockClear()
    setCurrentProject.mockClear()
    mutationOptions.length = 0
  })

  it('links every organization to explicit detail without exposing lifecycle actions', async () => {
    const { default: OrganizationPage } = await import('./page')
    const view = render(<OrganizationPage />)

    const desktop = within(view.getByTestId('desktop-list'))
    expect(desktop.getByText('manage.organization.manage').closest('a')?.getAttribute('href')).toBe(
      '/managed/settings/organizations/org-a',
    )
    expect(desktop.getByText('manage.organization.view').closest('a')?.getAttribute('href')).toBe(
      '/managed/settings/organizations/org-b',
    )
    expect(desktop.getByText('manage.organization.switch')).toBeTruthy()
    expect(desktop.getByText('sidebar.ownedByYou')).toBeTruthy()
    expect(desktop.getByText(/Shared Owner/)).toBeTruthy()
    expect(view.queryByText('manage.organization.delete')).toBeNull()
    expect(view.queryByText('manage.organization.transferOwnership')).toBeNull()
  })

  it('keeps organization identity and explicit actions visible in the mobile layout', async () => {
    const { default: OrganizationPage } = await import('./page')
    const view = render(<OrganizationPage />)
    const mobile = within(view.getByTestId('mobile-list'))

    expect(mobile.getByText('Organization A')).toBeTruthy()
    expect(mobile.getByText('sidebar.ownedByYou')).toBeTruthy()
    expect(mobile.getByText(/Shared Owner/)).toBeTruthy()
    expect(mobile.getByText('manage.organization.switch')).toBeTruthy()
    expect(mobile.getByText('manage.organization.manage')).toBeTruthy()
    expect(mobile.getByText('manage.organization.view')).toBeTruthy()
  })

  it('preserves the complete organization switcher list after switching from a paginated list', async () => {
    const { default: OrganizationPage } = await import('./page')
    const view = render(<OrganizationPage />)
    fireEvent.click(
      within(view.getByTestId('desktop-list')).getByText('manage.organization.switch'),
    )
    const variables = mutate.mock.calls[0]?.[0] as { orgId: string; requestSeq: number }

    act(() => {
      mutationOptions[1]?.onSuccess?.(
        {
          org_id: 'org-b',
          project_id: 'project-b',
          project: {
            id: 'project-b',
            org_id: 'org-b',
            name: 'Project B',
            slug: 'project-b',
            is_default: true,
          },
          projects: [],
        },
        variables,
      )
    })

    expect(setContext).toHaveBeenCalledWith(
      'org-b',
      'project-b',
      storedOrganizations,
      [],
      expect.objectContaining({ id: 'project-b' }),
    )
  })

  it('prevents duplicate organization switch requests from rapid clicks', async () => {
    const { default: OrganizationPage } = await import('./page')
    const view = render(<OrganizationPage />)
    const switchButton = within(view.getByTestId('desktop-list')).getByText(
      'manage.organization.switch',
    )

    fireEvent.click(switchButton)
    fireEvent.click(switchButton)

    expect(mutate).toHaveBeenCalledTimes(1)
  })
})
