import { act, cleanup, fireEvent, render, waitFor, within } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

const ORG_A = 'org_018f6f42-0a51-7cc4-98c8-4f6f0ca5f201'
const ORG_B = 'org_018f6f42-0a51-7cc4-98c8-4f6f0ca5f202'
const USER_OWNER = 'user_018f6f42-0a51-7cc4-98c8-4f6f0ca5f203'
const USER_MEMBER = 'user_018f6f42-0a51-7cc4-98c8-4f6f0ca5f204'
const USER_ADMIN = 'user_018f6f42-0a51-7cc4-98c8-4f6f0ca5f205'
const OWNER_MEMBER_ID = 'orgmem_018f6f42-0a51-7cc4-98c8-4f6f0ca5f206'
const MEMBER_ID = 'orgmem_018f6f42-0a51-7cc4-98c8-4f6f0ca5f207'
const ADMIN_MEMBER_ID = 'orgmem_018f6f42-0a51-7cc4-98c8-4f6f0ca5f208'
const FOREIGN_MEMBER_ID = 'orgmem_018f6f42-0a51-7cc4-98c8-4f6f0ca5f209'

const members = [
  {
    id: OWNER_MEMBER_ID,
    user_id: USER_OWNER,
    organization_id: ORG_A,
    user_email: 'owner@example.com',
    user_name: 'Owner',
    role: 'owner',
    joined_at: '2026-08-01T00:00:00Z',
  },
  {
    id: MEMBER_ID,
    user_id: USER_MEMBER,
    organization_id: ORG_A,
    user_email: 'member@example.com',
    user_name: 'Member',
    role: 'developer',
    joined_at: '2026-08-02T00:00:00Z',
  },
  {
    id: ADMIN_MEMBER_ID,
    user_id: USER_ADMIN,
    organization_id: ORG_A,
    user_email: 'admin@example.com',
    user_name: 'Admin',
    role: 'admin',
    joined_at: '2026-08-03T00:00:00Z',
  },
]

let cachedMemberPages: Array<[unknown, { data: typeof members }]> = [
  [['org-members'], { data: members }],
]
let currentUserId = USER_OWNER
let organizationRole = 'owner'
const invalidateQueries = vi.fn()
const paginatedListOptions = vi.fn()
const mutationOptions: Array<{
  mutationFn?: (variables: {
    email: string
    role: string
    runId: number
    scope: string
  }) => Promise<unknown>
  onSuccess?: (result: { runId: number; scope: string }) => void
}> = []

vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({
    invalidateQueries,
    getQueriesData: () => cachedMemberPages,
  }),
  useMutation: (options: { onSuccess?: (result: { runId: number; scope: string }) => void }) => {
    mutationOptions.push(options)
    return { mutate: vi.fn(), isPending: false }
  },
  useQuery: () => ({
    data: {
      id: ORG_A,
      name: 'Acme',
      slug: 'acme',
      role: organizationRole,
      project_creation_policy: 'admins_only',
    },
    isLoading: false,
  }),
}))

vi.mock('@/hooks/managed/use-paginated-list', () => ({
  usePaginatedList: (options: { queryKey: string; path: string }) => {
    paginatedListOptions(options)
    return {
      data: members,
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
    }
  },
}))

vi.mock('next/navigation', () => ({
  useParams: () => ({ organizationId: ORG_A }),
}))
vi.mock('@/lib/auth/auth-client', () => ({
  useSession: () => ({ data: { user: { id: currentUserId } } }),
}))
vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({
    t: (key: string, values?: { organization?: string }) =>
      values?.organization ? `${key}:${values.organization}` : key,
  }),
}))
vi.mock('@/lib/api-client', () => ({
  managedGet: vi.fn(),
  managedPost: vi.fn(),
  managedPut: vi.fn(),
  managedDelete: vi.fn(),
}))

vi.mock('@/components/managed/shared', () => ({
  DataTable: ({
    columns,
    data,
    mobileCard,
  }: {
    columns: Array<{ key: string; render: (row: (typeof members)[number]) => ReactNode }>
    data: typeof members
    mobileCard?: (row: (typeof members)[number]) => ReactNode
  }) => (
    <div>
      <div data-testid="desktop-headers">
        {columns.map((column) => (
          <div key={column.key}>{column.header}</div>
        ))}
      </div>
      <div data-testid="desktop-list">
        {data.map((row) => (
          <div key={row.id}>
            {columns.map((column) => (
              <div key={column.key}>{column.render(row)}</div>
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
  RelativeTime: () => null,
  PageHeader: ({
    title,
    subtitle,
    action,
  }: {
    title?: ReactNode
    subtitle?: ReactNode
    action?: ReactNode
  }) => (
    <div>
      <div>{title}</div>
      <div>{subtitle}</div>
      {action}
    </div>
  ),
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

vi.mock('@/components/ui/select', () => ({
  Select: ({
    value,
    onValueChange,
    children,
  }: {
    value: string
    onValueChange: (value: string) => void
    children: ReactNode
  }) => (
    <select
      aria-label="organization-role"
      value={value}
      onChange={(event) => onValueChange(event.target.value)}
    >
      {children}
    </select>
  ),
  SelectContent: ({ children }: { children: ReactNode }) => <>{children}</>,
  SelectItem: ({ value, children }: { value: string; children: ReactNode }) => (
    <option value={value}>{children}</option>
  ),
  SelectTrigger: () => null,
  SelectValue: () => null,
}))

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement

describe('MembersPage', () => {
  afterEach(() => {
    cleanup()
    cachedMemberPages = [[['organization-members'], { data: members }]]
    currentUserId = USER_OWNER
    organizationRole = 'owner'
    invalidateQueries.mockClear()
    paginatedListOptions.mockClear()
    mutationOptions.length = 0
  })

  it('shows an explicit management action for mutable members', async () => {
    const { default: MembersPage } = await import('./page')
    const view = render(<MembersPage />)

    expect(
      within(view.getByTestId('desktop-list')).getAllByText('manage.members.manage'),
    ).toHaveLength(2)
  })

  it('names the organization whose membership is being managed', async () => {
    const { default: MembersPage } = await import('./page')
    const view = render(<MembersPage />)

    expect(view.getByText('manage.members.subtitle:Acme')).toBeTruthy()
  })

  it('explains the organization-wide impact before promoting a member', async () => {
    const { default: MembersPage } = await import('./page')
    const view = render(<MembersPage />)

    fireEvent.click(
      within(view.getByTestId('desktop-list')).getAllByText('manage.members.manage')[0],
    )
    expect((view.getByLabelText('organization-role') as HTMLSelectElement).value).toBe('member')
    fireEvent.change(view.getByLabelText('organization-role'), { target: { value: 'admin' } })

    expect(view.getByText('manage.members.promoteAdminImpact')).toBeTruthy()
  })

  it('explains that removal revokes organization and project access', async () => {
    const { default: MembersPage } = await import('./page')
    const view = render(<MembersPage />)

    fireEvent.click(
      within(view.getByTestId('desktop-list')).getAllByText('manage.members.manage')[0],
    )
    fireEvent.click(view.getByRole('button', { name: 'manage.members.remove' }))

    expect(view.getByText('manage.members.removeAccessImpact')).toBeTruthy()
    expect(view.getAllByText('member@example.com').length).toBeGreaterThan(0)
  })

  it('explains the project-access reset before demoting an organization admin', async () => {
    const { default: MembersPage } = await import('./page')
    const view = render(<MembersPage />)

    fireEvent.click(
      within(view.getByTestId('desktop-list')).getAllByText('manage.members.manage')[1],
    )
    fireEvent.change(view.getByLabelText('organization-role'), { target: { value: 'member' } })

    expect(view.getByText('manage.members.demoteMemberImpact')).toBeTruthy()
  })

  it('keeps member identity and management visible in the mobile layout', async () => {
    const { default: MembersPage } = await import('./page')
    const view = render(<MembersPage />)
    const mobile = within(view.getByTestId('mobile-list'))

    expect(mobile.getByText('Member')).toBeTruthy()
    expect(mobile.getByText('member@example.com')).toBeTruthy()
    expect(mobile.getAllByText('manage.members.manage')).toHaveLength(2)
  })

  it('explains why the owner cannot be edited from the member list', async () => {
    const { default: MembersPage } = await import('./page')
    const view = render(<MembersPage />)

    expect(
      within(view.getByTestId('desktop-list')).getByText('manage.members.ownerProtected'),
    ).toBeTruthy()
  })

  it('does not expose self-management actions for the current administrator', async () => {
    currentUserId = USER_ADMIN
    const { default: MembersPage } = await import('./page')
    const view = render(<MembersPage />)
    const desktop = within(view.getByTestId('desktop-list'))

    expect(desktop.getAllByText('manage.members.manage')).toHaveLength(1)
    expect(desktop.getByText('manage.members.currentAccountProtected')).toBeTruthy()
  })

  it('opens management from the current organization row even when another organization is cached', async () => {
    cachedMemberPages = [
      [
        ['organization-members', ORG_B],
        { data: [{ ...members[1], id: FOREIGN_MEMBER_ID, role: 'owner' }] },
      ],
      [['organization-members', ORG_A], { data: members }],
    ]
    const { default: MembersPage } = await import('./page')
    const view = render(<MembersPage />)

    fireEvent.click(
      within(view.getByTestId('desktop-list')).getAllByText('manage.members.manage')[0],
    )

    expect(view.getByRole('heading', { name: 'manage.members.manage' })).toBeTruthy()
  })

  it('describes adding an existing account to the current organization', async () => {
    const { default: MembersPage } = await import('./page')
    const view = render(<MembersPage />)

    fireEvent.click(view.getByRole('button', { name: 'manage.members.add' }))

    expect(view.getByText('manage.members.addDescription:Acme')).toBeTruthy()
    expect(view.getByText('manage.members.roleMemberImpact')).toBeTruthy()
  })

  it('uses the canonical add-member endpoint instead of the legacy invite route', async () => {
    const { managedPost } = await import('@/lib/api-client')
    vi.mocked(managedPost).mockResolvedValue(members[1])
    const { default: MembersPage } = await import('./page')
    render(<MembersPage />)

    await mutationOptions[0]?.mutationFn?.({
      email: 'new@example.com',
      role: 'member',
      runId: 0,
      scope: ORG_A,
    })

    expect(managedPost).toHaveBeenCalledWith(`organizations/${ORG_A}/members`, {
      email: 'new@example.com',
      role: 'member',
    })
  })

  it('uses explicit organization paths for list, search, update, and removal', async () => {
    const { managedDelete, managedGet, managedPut } = await import('@/lib/api-client')
    vi.mocked(managedGet).mockResolvedValue([])
    vi.mocked(managedPut).mockResolvedValue(members[1])
    vi.mocked(managedDelete).mockResolvedValue(undefined)
    const { default: MembersPage } = await import('./page')
    const view = render(<MembersPage />)

    expect(paginatedListOptions).toHaveBeenCalledWith(
      expect.objectContaining({
        queryKey: 'organization-members',
        path: `/organizations/${ORG_A}/members`,
      }),
    )

    fireEvent.click(view.getByRole('button', { name: 'manage.members.add' }))
    fireEvent.change(view.getByPlaceholderText('user@example.com'), {
      target: { value: 'new@example.com' },
    })
    await waitFor(() =>
      expect(managedGet).toHaveBeenCalledWith(
        `organizations/${ORG_A}/member-candidates?q=new%40example.com&limit=5`,
      ),
    )

    await mutationOptions[1]?.mutationFn?.({
      userId: USER_MEMBER,
      runId: 0,
      scope: ORG_A,
    })
    expect(managedDelete).toHaveBeenCalledWith(`organizations/${ORG_A}/members/${USER_MEMBER}`)

    await mutationOptions[2]?.mutationFn?.({
      userId: USER_MEMBER,
      role: 'admin',
      runId: 0,
      scope: ORG_A,
    })
    expect(managedPut).toHaveBeenCalledWith(`organizations/${ORG_A}/members/${USER_MEMBER}`, {
      role: 'admin',
    })
  })

  it('disables adding an account already in the current organization', async () => {
    const { default: MembersPage } = await import('./page')
    const view = render(<MembersPage />)

    fireEvent.click(view.getByRole('button', { name: 'manage.members.add' }))
    fireEvent.change(view.getByPlaceholderText('user@example.com'), {
      target: { value: 'member@example.com' },
    })

    expect(
      view.getAllByRole('button', { name: 'manage.members.add' }).find((button) => button.disabled),
    ).toBeTruthy()
    expect(view.getByText('manage.members.alreadyMember')).toBeTruthy()
  })

  it('explains read-only member management to ordinary organization members', async () => {
    organizationRole = 'member'
    const { default: MembersPage } = await import('./page')
    const view = render(<MembersPage />)

    expect(view.getByText('manage.members.readOnlyExplanation')).toBeTruthy()
    expect(
      within(view.getByTestId('desktop-headers')).queryByText('managed.table.actions'),
    ).toBeNull()
  })

  it.each([0, 1, 2])(
    'refreshes ownership-transfer candidates after member mutation %s',
    async (index) => {
      const { default: MembersPage } = await import('./page')
      render(<MembersPage />)

      act(() => {
        mutationOptions[index]?.onSuccess?.({ runId: 0, scope: ORG_A })
      })

      expect(invalidateQueries).toHaveBeenCalledWith({
        queryKey: ['organization-members', ORG_A],
      })
    },
  )
})
