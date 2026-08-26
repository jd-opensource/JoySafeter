import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import type { ReactNode } from 'react'
import React from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { managedGet, managedPost } from '@/lib/api-client'
import {
  ORGANIZATION_MEMBER_ID,
  OTHER_ORGANIZATION_ID,
  PROJECT_ID,
  USER_ID,
} from '@/test-utils/entity-ids'

let organizationMembers = [
  {
    id: ORGANIZATION_MEMBER_ID,
    user_id: USER_ID,
    email: 'member@example.com',
    display_name: 'Member',
    org_role: 'member',
    access: 'default',
    project_role: null,
  },
]

vi.mock('@/lib/api-client', () => ({
  managedDelete: vi.fn(),
  managedGet: vi.fn(),
  managedPost: vi.fn(),
}))

vi.mock('@/hooks/managed/use-paginated-list', () => ({
  usePaginatedList: () => ({
    data: organizationMembers,
    isLoading: false,
    isFetching: false,
    isError: false,
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

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock('@/lib/managed/errors', () => ({
  toastOperationError: vi.fn(),
}))

vi.mock('@/components/managed/shared', () => ({
  DataTable: ({
    columns,
    data,
  }: {
    columns: Array<{ render: (row: unknown) => ReactNode }>
    data: unknown[]
  }) => (
    <div>
      {data.map((row, rowIndex) =>
        columns.map((column, columnIndex) => (
          <div key={`${rowIndex}-${columnIndex}`}>{column.render(row)}</div>
        )),
      )}
    </div>
  ),
  FilterBar: () => null,
  PageHeader: () => null,
}))

vi.mock('@/components/ui/select', () => ({
  Select: ({
    value,
    onValueChange,
    disabled,
    children,
  }: {
    value: string
    onValueChange: (value: string) => void
    disabled?: boolean
    children: ReactNode
  }) => (
    <select
      aria-label="project-permission"
      value={value}
      disabled={disabled}
      onChange={(event) => onValueChange(event.target.value)}
    >
      {children}
    </select>
  ),
  SelectTrigger: () => null,
  SelectValue: () => null,
  SelectContent: ({ children }: { children: ReactNode }) => <>{children}</>,
  SelectItem: ({
    value,
    disabled,
    children,
  }: {
    value: string
    disabled?: boolean
    children: ReactNode
  }) => (
    <option value={value} disabled={disabled}>
      {children}
    </option>
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

vi.mock('next/link', () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}))

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

describe('ProjectAccessPage', () => {
  afterEach(() => {
    cleanup()
    organizationMembers = [
      {
        id: ORGANIZATION_MEMBER_ID,
        user_id: USER_ID,
        email: 'member@example.com',
        display_name: 'Member',
        org_role: 'member',
        access: 'default',
        project_role: null,
      },
    ]
    vi.clearAllMocks()
  })

  it('shows default-project guidance and row-level saving feedback', async () => {
    const grant = deferred<unknown>()
    ;(managedGet as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: PROJECT_ID,
      org_id: OTHER_ORGANIZATION_ID,
      name: 'Project A',
      slug: 'project-a',
      is_default: true,
    })
    ;(managedPost as unknown as ReturnType<typeof vi.fn>).mockReturnValue(grant.promise)
    const { ProjectAccessPage } = await import('./project-access-page')
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const view = render(
      <QueryClientProvider client={queryClient}>
        <ProjectAccessPage projectId={PROJECT_ID} />
      </QueryClientProvider>,
    )

    await waitFor(() =>
      expect(
        view.getAllByText('manage.projectMembers.defaultProjectRestriction').length,
      ).toBeGreaterThan(0),
    )
    expect(view.getByText('manage.projectMembers.accessDefault')).toBeTruthy()

    fireEvent.change(view.getByLabelText('project-permission'), { target: { value: 'editor' } })
    await waitFor(() => expect(view.getByText('manage.projectMembers.saving')).toBeTruthy())

    grant.resolve({})
    await waitFor(() => expect(view.getByText('manage.projectMembers.saved')).toBeTruthy())
  })

  it('links empty project access to the owning organization member page', async () => {
    organizationMembers = []
    ;(managedGet as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: PROJECT_ID,
      org_id: OTHER_ORGANIZATION_ID,
      name: 'Project A',
      slug: 'project-a',
      is_default: false,
    })
    const { ProjectAccessPage } = await import('./project-access-page')
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const view = render(
      <QueryClientProvider client={queryClient}>
        <ProjectAccessPage projectId={PROJECT_ID} />
      </QueryClientProvider>,
    )

    await waitFor(() =>
      expect(
        view.getByText('manage.projectMembers.manageMembers').closest('a')?.getAttribute('href'),
      ).toBe(`/managed/settings/organizations/${OTHER_ORGANIZATION_ID}/members`),
    )
  })
})
