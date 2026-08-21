import { cleanup, fireEvent, render, waitFor, within } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

const routerPush = vi.fn()
const switchProject = vi.fn(async () => undefined)
const mutate = vi.fn()
const managedPost = vi.fn()
const mutationOptions: Array<{
  mutationFn?: (variables: { name: string; runId: number; scope: string }) => Promise<unknown>
}> = []

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: routerPush }),
}))

vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({
    getQueriesData: () => [],
    getQueryData: () => [],
    invalidateQueries: vi.fn(),
  }),
  useMutation: (options: {
    mutationFn?: (variables: { name: string; runId: number; scope: string }) => Promise<unknown>
  }) => {
    mutationOptions.push(options)
    return { mutate, isPending: false }
  },
}))

vi.mock('@/lib/api-client', () => ({ managedPost }))

vi.mock('@/hooks/managed/use-paginated-list', () => ({
  usePaginatedList: () => ({
    data: [
      {
        id: 'project-a',
        org_id: 'org-a',
        name: 'Project A',
        slug: 'project-a',
        is_default: false,
        capability: 'admin',
      },
    ],
    isLoading: false,
    isFetching: false,
    isError: false,
    error: null,
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

vi.mock('@/providers/permissions-provider', () => ({
  useUserPermissionsContext: () => ({ canAdmin: true }),
}))

vi.mock('@/hooks/managed/use-project-context', () => ({
  useProjectContext: () => ({ switchProject }),
}))

const projectStore = Object.assign(
  (
    selector: (state: {
      currentOrgId: string
      currentProjectId: string
      organizations: Array<{ id: string; project_creation_policy: 'admins_only' | 'all_members' }>
    }) => unknown,
  ) =>
    selector({
      currentOrgId: 'org-a',
      currentProjectId: 'project-current',
      organizations: [{ id: 'org-a', project_creation_policy: 'admins_only' }],
    }),
  { getState: () => ({ currentOrgId: 'org-a' }) },
)

vi.mock('@/stores/managed/project-store', () => ({
  useProjectStore: projectStore,
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
        {columns.map((column) => (
          <div key={column.key}>{column.render(data[0])}</div>
        ))}
        {(actionMenu?.(data[0]) ?? []).map((item) => (
          <span key={item.label}>{item.label}</span>
        ))}
      </div>
      <div data-testid="mobile-list">{mobileCard?.(data[0])}</div>
    </div>
  ),
  FilterBar: () => null,
  MonoId: ({ id }: { id: string }) => <span>{id}</span>,
  RelativeTime: () => null,
  StatusBadge: () => null,
  PageHeader: ({ action }: { action?: ReactNode }) => <div>{action}</div>,
  ResourceErrorState: () => null,
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

describe('ProjectsPage', () => {
  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
    routerPush.mockClear()
    switchProject.mockClear()
    mutate.mockClear()
    managedPost.mockReset()
    mutationOptions.length = 0
  })

  it('shows an explicit project management action instead of hidden row navigation', async () => {
    const { default: ProjectsPage } = await import('./page')
    const view = render(<ProjectsPage />)

    fireEvent.click(within(view.getByTestId('desktop-list')).getByText('manage.projects.manage'))
    expect(routerPush).toHaveBeenCalledWith('/managed/projects/project-a')
    expect(view.queryByText('common.archive')).toBeNull()
  })

  it('switches work context only from the explicit use action', async () => {
    const { default: ProjectsPage } = await import('./page')
    const view = render(<ProjectsPage />)

    expect(switchProject).not.toHaveBeenCalled()
    fireEvent.click(within(view.getByTestId('desktop-list')).getByText('manage.projects.use'))
    await waitFor(() => expect(switchProject).toHaveBeenCalledWith('project-a', 'org-a'))
  })

  it('asks only for a project name during creation', async () => {
    const { default: ProjectsPage } = await import('./page')
    const view = render(<ProjectsPage />)

    fireEvent.click(view.getByText('manage.projects.create'))

    expect(view.getByPlaceholderText('manage.projects.namePlaceholder')).toBeTruthy()
    expect(view.queryByPlaceholderText('manage.projects.slugPlaceholder')).toBeNull()
    expect(view.getByText('manage.projects.slugGeneratedHint')).toBeTruthy()
  })

  it('generates an ASCII URL-safe slug for a non-Latin project name', async () => {
    managedPost.mockResolvedValue({})
    vi.spyOn(Date, 'now').mockReturnValue(1_789_000_000_000)
    const { default: ProjectsPage } = await import('./page')
    const view = render(<ProjectsPage />)

    fireEvent.click(view.getByText('manage.projects.create'))
    fireEvent.change(view.getByPlaceholderText('manage.projects.namePlaceholder'), {
      target: { value: '中文项目' },
    })
    fireEvent.click(view.getAllByText('manage.projects.create').at(-1)!)

    const variables = mutate.mock.calls.at(-1)?.[0] as {
      name: string
      runId: number
      scope: string
    }
    await mutationOptions[0]?.mutationFn?.(variables)

    expect(managedPost).toHaveBeenCalledWith('/auth/projects', {
      name: '中文项目',
      slug: expect.stringMatching(/^project-[a-z0-9]+$/),
    })
  })

  it('keeps project identity and explicit actions visible in the mobile layout', async () => {
    const { default: ProjectsPage } = await import('./page')
    const view = render(<ProjectsPage />)
    const mobile = within(view.getByTestId('mobile-list'))

    expect(mobile.getByText('Project A')).toBeTruthy()
    expect(mobile.getByText('manage.projects.use')).toBeTruthy()
    expect(mobile.getByText('manage.projects.manage')).toBeTruthy()
  })
})
