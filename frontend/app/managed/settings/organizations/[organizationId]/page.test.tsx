import { cleanup, render } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

const ORG_A = 'org_018f6f42-0a51-7cc4-98c8-4f6f0ca5f101'
const ORG_B = 'org_018f6f42-0a51-7cc4-98c8-4f6f0ca5f102'
const USER_OWNER = 'user_018f6f42-0a51-7cc4-98c8-4f6f0ca5f103'
const USER_MEMBER = 'user_018f6f42-0a51-7cc4-98c8-4f6f0ca5f104'
const MEMBER_ID = 'orgmem_018f6f42-0a51-7cc4-98c8-4f6f0ca5f105'

const managedGet = vi.fn()
const managedPut = vi.fn()
const managedPost = vi.fn()
const managedDelete = vi.fn()
const invalidateQueries = vi.fn()
const routerPush = vi.fn()
const mutationOptions: Array<{
  mutationFn?: (variables: Record<string, string>) => Promise<unknown>
}> = []
let organizationRole = 'owner'
let currentOrgId = ORG_A

const organization = () => ({
  id: ORG_B,
  name: 'Organization B',
  slug: 'organization-b',
  role: organizationRole,
  project_creation_policy: 'admins_only' as const,
  created_at: '2026-08-01T00:00:00Z',
})

vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ invalidateQueries }),
  useQuery: ({ queryKey }: { queryKey: unknown[] }) =>
    queryKey[0] === 'organization-detail'
      ? { data: organization(), isLoading: false }
      : {
          data: {
            data: [
              {
                id: MEMBER_ID,
                user_id: USER_MEMBER,
                organization_id: ORG_B,
                role: 'member',
                user_name: 'Member',
                user_email: 'member@example.com',
              },
            ],
          },
          isLoading: false,
        },
  useMutation: (options: {
    mutationFn?: (variables: Record<string, string>) => Promise<unknown>
  }) => {
    mutationOptions.push(options)
    return { mutate: vi.fn(), isPending: false }
  },
}))

vi.mock('next/navigation', () => ({
  useParams: () => ({ organizationId: ORG_B }),
  useRouter: () => ({ push: routerPush }),
}))

vi.mock('@/stores/managed/project-store', () => ({
  useProjectStore: (selector: (state: { currentOrgId: string }) => unknown) =>
    selector({ currentOrgId }),
}))

vi.mock('@/lib/auth/auth-client', () => ({
  useSession: () => ({ data: { user: { id: USER_OWNER } } }),
}))

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock('@/lib/api-client', () => ({ managedGet, managedPut, managedPost, managedDelete }))

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
    <select value={value} onChange={(event) => onValueChange(event.target.value)}>
      {children}
    </select>
  ),
  SelectContent: ({ children }: { children: ReactNode }) => <>{children}</>,
  SelectItem: ({ value, children }: { value: string; children: ReactNode }) => (
    <option value={value}>{children}</option>
  ),
  SelectTrigger: ({ children }: { children: ReactNode }) => <>{children}</>,
  SelectValue: () => null,
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

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement

describe('OrganizationOverviewPage', () => {
  afterEach(() => {
    cleanup()
    organizationRole = 'owner'
    currentOrgId = ORG_A
    mutationOptions.length = 0
    vi.clearAllMocks()
  })

  it('edits the route organization without switching active context', async () => {
    const { default: OrganizationOverviewPage } = await import('./page')
    const view = render(<OrganizationOverviewPage />)

    expect(view.getByDisplayValue('Organization B')).toBeTruthy()
    expect(view.getByText('manage.organization.projectCreationPolicy')).toBeTruthy()
    expect(view.getByText('common.save')).toBeTruthy()

    await mutationOptions[0]?.mutationFn?.({
      name: 'Renamed Organization',
      projectCreationPolicy: 'all_members',
    })
    expect(managedPut).toHaveBeenCalledWith(`organizations/${ORG_B}`, {
      name: 'Renamed Organization',
      project_creation_policy: 'all_members',
    })
    expect(managedPost).not.toHaveBeenCalledWith('auth/switch-context', expect.anything())
  })

  it('keeps transfer and deletion in an owner-only advanced section', async () => {
    const { default: OrganizationOverviewPage } = await import('./page')
    const view = render(<OrganizationOverviewPage />)

    expect(view.getByText('manage.organization.advanced')).toBeTruthy()
    expect(view.getByText('manage.organization.transferOwnership')).toBeTruthy()
    expect(view.getByText('manage.organization.delete')).toBeTruthy()

    await mutationOptions[1]?.mutationFn?.({ userId: USER_MEMBER })
    expect(managedPost).toHaveBeenCalledWith(`organizations/${ORG_B}/transfer-ownership`, {
      new_owner_user_id: USER_MEMBER,
    })
    await mutationOptions[2]?.mutationFn?.({})
    expect(managedDelete).toHaveBeenCalledWith(`organizations/${ORG_B}`)
  })

  it('shows ordinary members a read-only overview', async () => {
    organizationRole = 'member'
    const { default: OrganizationOverviewPage } = await import('./page')
    const view = render(<OrganizationOverviewPage />)

    expect(view.getByText('manage.organization.detail.readOnlySettings')).toBeTruthy()
    expect(view.queryByText('common.save')).toBeNull()
    expect(view.queryByText('manage.organization.advanced')).toBeNull()
  })

  it('explains why the active organization cannot be deleted', async () => {
    currentOrgId = ORG_B
    const { default: OrganizationOverviewPage } = await import('./page')
    const view = render(<OrganizationOverviewPage />)

    expect(view.getByText('manage.organization.detail.deleteCurrentFirst')).toBeTruthy()
    expect(view.getByRole('button', { name: 'manage.organization.delete' })).toBeDisabled()
  })
})
