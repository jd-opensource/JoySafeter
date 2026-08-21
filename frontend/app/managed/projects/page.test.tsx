import { cleanup, fireEvent, render } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

const routerPush = vi.fn()

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: routerPush }),
}))

vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({
    getQueriesData: () => [],
    getQueryData: () => [],
    invalidateQueries: vi.fn(),
  }),
  useMutation: () => ({ mutate: vi.fn(), isPending: false }),
}))

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

const projectStore = Object.assign(
  (selector: (state: { currentOrgId: string }) => unknown) => selector({ currentOrgId: 'org-a' }),
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
    data,
    onRowClick,
    actionMenu,
  }: {
    data: Array<{ id: string }>
    onRowClick?: (row: { id: string }) => void
    actionMenu?: (row: { id: string }) => Array<{ label: string }>
  }) => (
    <div>
      <button type="button" onClick={() => onRowClick?.(data[0])}>
        project-row
      </button>
      {(actionMenu?.(data[0]) ?? []).map((item) => (
        <span key={item.label}>{item.label}</span>
      ))}
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
    routerPush.mockClear()
  })

  it('opens project settings from the row and keeps only lifecycle shortcuts', async () => {
    const { default: ProjectsPage } = await import('./page')
    const view = render(<ProjectsPage />)

    fireEvent.click(view.getByText('project-row'))
    expect(routerPush).toHaveBeenCalledWith('/managed/projects/project-a')
    expect(view.getByText('common.archive')).toBeTruthy()
    expect(view.queryByText('common.edit')).toBeNull()
    expect(view.queryByText('manage.projects.members')).toBeNull()
    expect(view.queryByText('manage.projects.pauseTriggers')).toBeNull()
    expect(view.queryByText('manage.projects.setDefault')).toBeNull()
  })

  it('asks only for a project name during creation', async () => {
    const { default: ProjectsPage } = await import('./page')
    const view = render(<ProjectsPage />)

    fireEvent.click(view.getByText('manage.projects.create'))

    expect(view.getByPlaceholderText('manage.projects.namePlaceholder')).toBeTruthy()
    expect(view.queryByPlaceholderText('manage.projects.slugPlaceholder')).toBeNull()
    expect(view.getByText('manage.projects.slugGeneratedHint')).toBeTruthy()
  })
})
