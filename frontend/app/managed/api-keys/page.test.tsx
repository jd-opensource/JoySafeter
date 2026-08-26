import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { managedGet, managedPost } from '@/lib/api-client'

let listPath = ''
const resetPagination = vi.fn()

vi.mock('@/lib/api-client', () => ({
  managedDelete: vi.fn(),
  managedGet: vi.fn(),
  managedPost: vi.fn(),
}))

vi.mock('@/hooks/managed/use-current-project-read-only', () => ({
  currentProjectAllowsWrite: () => false,
  useCurrentProjectReadOnly: () => true,
}))

vi.mock('@/hooks/managed/use-paginated-list', () => ({
  usePaginatedList: ({ path }: { path: string }) => {
    listPath = path
    return {
      data: [],
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
      reset: resetPagination,
    }
  },
}))

const projectStore = Object.assign(
  (selector: (state: Record<string, unknown>) => unknown) =>
    selector({
      currentOrgId: 'org-a',
      currentProjectId: 'project-a',
      currentProject: { id: 'project-a', capability: 'read' },
    }),
  {
    getState: () => ({
      currentOrgId: 'org-a',
      currentProjectId: 'project-a',
      currentProject: { id: 'project-a', capability: 'read' },
    }),
  },
)

vi.mock('@/stores/managed/project-store', () => ({ useProjectStore: projectStore }))

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock('@/lib/managed/errors', () => ({ toastOperationError: vi.fn() }))

vi.mock('@/components/managed/shared', () => ({
  DataTable: () => null,
  FilterBar: () => null,
  MonoId: () => null,
  PageHeader: ({ action }: { action?: ReactNode }) => <div>{action}</div>,
  RelativeTime: () => null,
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

vi.mock('@/components/ui/select', () => ({
  Select: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectTrigger: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectValue: () => null,
  SelectContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectItem: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}))

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement

describe('ApiKeysPage route scope', () => {
  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
    listPath = ''
  })

  it('uses the route project instead of the active work project', async () => {
    ;(managedGet as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: 'project-b',
      org_id: 'org-a',
      capability: 'admin',
      archived_at: null,
    })
    ;(managedPost as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: 'apikey_018f6f42-0a51-7cc4-98c8-4f6f0ca5f030',
      project_id: 'proj_018f6f42-0a51-7cc4-98c8-4f6f0ca5f024',
      name: 'Deploy key',
      key_prefix: 'jsk_live_1234',
      role: 'viewer',
      status: 'active',
      created_at: '2026-08-26T00:00:00Z',
      expires_at: null,
      revoked_at: null,
      last_used_at: null,
      raw_key: 'secret',
    })
    const { default: ApiKeysPage } = await import('./page')
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const view = render(
      <QueryClientProvider client={queryClient}>
        <ApiKeysPage projectId="project-b" />
      </QueryClientProvider>,
    )

    await waitFor(() => expect(view.getByText('manage.apiKeys.create')).toBeTruthy())
    expect(listPath).toBe('/auth/projects/project-b/api-keys')

    fireEvent.click(view.getByText('manage.apiKeys.create'))
    fireEvent.change(view.getByPlaceholderText('manage.apiKeys.namePlaceholder'), {
      target: { value: 'Deploy key' },
    })
    fireEvent.click(view.getAllByRole('button', { name: 'manage.apiKeys.create' })[1])

    await waitFor(() =>
      expect(managedPost).toHaveBeenCalledWith('/auth/projects/project-b/api-keys', {
        name: 'Deploy key',
        role: 'viewer',
      }),
    )
  })
})
