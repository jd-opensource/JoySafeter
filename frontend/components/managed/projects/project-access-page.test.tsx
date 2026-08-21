import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import type { ReactNode } from 'react'
import React from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { managedGet, managedPost } from '@/lib/api-client'

vi.mock('@/lib/api-client', () => ({
  managedDelete: vi.fn(),
  managedGet: vi.fn(),
  managedPost: vi.fn(),
}))

vi.mock('@/hooks/managed/use-paginated-list', () => ({
  usePaginatedList: () => ({
    data: [
      {
        id: 'member-1',
        user_id: 'user-1',
        email: 'member@example.com',
        display_name: 'Member',
        org_role: 'member',
        access: 'none',
        project_role: null,
      },
    ],
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
      {columns.map((column, index) => (
        <div key={index}>{column.render(data[0])}</div>
      ))}
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
    vi.clearAllMocks()
  })

  it('shows default-project guidance and row-level saving feedback', async () => {
    const grant = deferred<unknown>()
    ;(managedGet as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: 'project-a',
      name: 'Project A',
      slug: 'project-a',
      is_default: true,
    })
    ;(managedPost as unknown as ReturnType<typeof vi.fn>).mockReturnValue(grant.promise)
    const { ProjectAccessPage } = await import('./project-access-page')
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const view = render(
      <QueryClientProvider client={queryClient}>
        <ProjectAccessPage projectId="project-a" />
      </QueryClientProvider>,
    )

    await waitFor(() =>
      expect(
        view.getAllByText('manage.projectMembers.defaultProjectRestriction').length,
      ).toBeGreaterThan(0),
    )

    fireEvent.change(view.getByLabelText('project-permission'), { target: { value: 'viewer' } })
    await waitFor(() => expect(view.getByText('manage.projectMembers.saving')).toBeTruthy())

    grant.resolve({})
    await waitFor(() => expect(view.getByText('manage.projectMembers.saved')).toBeTruthy())
  })
})
