import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({ t: (key: string, _params?: unknown) => key }),
}))

vi.mock('@/lib/api-client', () => ({
  managedGet: vi.fn(),
  managedPost: vi.fn(),
}))

vi.mock('@/lib/managed/errors', () => ({
  toastOperationError: vi.fn(),
}))

vi.mock('@/lib/managed/filters', () => ({
  createCreatedTimeFilter: () => ({ id: 'created', label: 'created', options: [] }),
  filterByCreatedTime: () => true,
  matchesSearch: () => true,
}))

vi.mock('@/components/managed/shared', () => ({
  DataTable: ({
    actionMenu,
    data,
  }: {
    actionMenu?: (row: MemoryStoreRecord) => { label: string; onClick: () => void }[]
    data: MemoryStoreRecord[]
  }) => (
    <div>
      {data.map((store) => (
        <div key={store.id}>
          <span>{store.name}</span>
          {actionMenu?.(store).map((item) => (
            <button key={item.label} onClick={item.onClick}>
              {store.id}:{item.label}
            </button>
          ))}
        </div>
      ))}
    </div>
  ),
  FilterBar: () => null,
  MonoId: ({ id }: { id: string }) => <span>{id}</span>,
  PageHeader: ({ title, action }: { title: string; action?: ReactNode }) => (
    <div>
      <h1>{title}</h1>
      {action}
    </div>
  ),
  RelativeTime: ({ date }: { date: string }) => <span>{date}</span>,
  ResourceErrorState: () => null,
  StatusBadge: ({ status }: { status: string }) => <span>{status}</span>,
}))

vi.mock('@/components/ui/button', () => ({
  Button: ({
    children,
    disabled,
    onClick,
    type = 'button',
  }: {
    children: ReactNode
    disabled?: boolean
    onClick?: () => void
    type?: 'button' | 'submit' | 'reset'
  }) => (
    <button type={type} disabled={disabled} onClick={onClick}>
      {children}
    </button>
  ),
}))

vi.mock('@/components/ui/dialog', () => ({
  Dialog: ({
    children,
    onOpenChange,
    open,
  }: {
    children: ReactNode
    onOpenChange?: (open: boolean) => void
    open: boolean
  }) =>
    open ? (
      <div>
        {children}
        <button onClick={() => onOpenChange?.(false)}>dialog-close</button>
      </div>
    ) : null,
  DialogContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogFooter: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogHeader: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children: ReactNode }) => <h2>{children}</h2>,
}))

vi.mock('@/components/ui/input', () => ({
  Input: ({ onChange, onKeyDown, ...props }: React.InputHTMLAttributes<HTMLInputElement>) => (
    <input
      {...props}
      onChange={onChange}
      onInput={onChange as React.FormEventHandler<HTMLInputElement>}
      onKeyDown={onKeyDown}
    />
  ),
}))

vi.mock('@/components/ui/textarea', () => ({
  Textarea: ({ onChange, ...props }: React.TextareaHTMLAttributes<HTMLTextAreaElement>) => (
    <textarea
      {...props}
      onChange={onChange}
      onInput={onChange as React.FormEventHandler<HTMLTextAreaElement>}
    />
  ),
}))

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement
globalThis.localStorage = dom.window.localStorage

import { managedGet, managedPost } from '@/lib/api-client'
import { useProjectStore } from '@/stores/managed/project-store'

import MemoryStoreListPage from './page'

interface MemoryStoreRecord {
  id: string
  name: string
  description?: string | null
  archived_at?: string | null
  created_at: string
  updated_at: string
}

const managedGetMock = managedGet as unknown as ReturnType<typeof vi.fn>
const managedPostMock = managedPost as unknown as ReturnType<typeof vi.fn>

function memoryStore(id: string, name: string): MemoryStoreRecord {
  return {
    id,
    name,
    description: null,
    archived_at: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

describe('MemoryStoreListPage object lifecycle', () => {
  beforeEach(() => {
    managedGetMock.mockReset()
    managedPostMock.mockReset()
    managedGetMock.mockResolvedValue({
      data: [memoryStore('memstore_a', 'Project A Store')],
      has_more: false,
    })
    managedPostMock.mockResolvedValue({})
    useProjectStore.setState({
      currentOrgId: 'org-a',
      currentProjectId: 'project-a',
      organizations: [],
      projects: [],
    })
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
    useProjectStore.setState({
      currentOrgId: null,
      currentProjectId: null,
      organizations: [],
      projects: [],
    })
    localStorage.clear()
  })

  it('does not archive a memory store from an old row action in the same turn as a project switch', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText } = render(
      <QueryClientProvider client={queryClient}>
        <MemoryStoreListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Project A Store')).toBeTruthy()
    })

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      fireEvent.click(getByText('memstore_a:managed.memoryStores.archiveStore'))
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith('memory_stores/a/archive')
  })

  it('does not invalidate memory stores from an archive completion after the managed project changes', async () => {
    const archive = deferred<Record<string, never>>()
    const initialList = deferred<{ data: MemoryStoreRecord[]; has_more: boolean }>()
    managedGetMock.mockReturnValueOnce(initialList.promise)
    managedPostMock.mockReturnValueOnce(archive.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    const { getByText, rerender } = render(
      <QueryClientProvider client={queryClient}>
        <MemoryStoreListPage />
      </QueryClientProvider>,
    )

    await act(async () => {
      initialList.resolve({
        data: [memoryStore('memstore_a', 'Project A Store')],
        has_more: false,
      })
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(getByText('Project A Store')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('memstore_a:managed.memoryStores.archiveStore'))
      await Promise.resolve()
    })

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      rerender(
        <QueryClientProvider client={queryClient}>
          <MemoryStoreListPage />
        </QueryClientProvider>,
      )
    })

    await act(async () => {
      archive.resolve({})
      await Promise.resolve()
    })

    expect(invalidateSpy).not.toHaveBeenCalledWith({ queryKey: ['memory-stores'] })
  })

  it('does not invalidate memory stores from an archive completion after the page unmounts', async () => {
    const archive = deferred<Record<string, never>>()
    const initialList = deferred<{ data: MemoryStoreRecord[]; has_more: boolean }>()
    managedGetMock.mockReturnValueOnce(initialList.promise)
    managedPostMock.mockReturnValueOnce(archive.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    const { getByText, unmount } = render(
      <QueryClientProvider client={queryClient}>
        <MemoryStoreListPage />
      </QueryClientProvider>,
    )

    await act(async () => {
      initialList.resolve({
        data: [memoryStore('memstore_a', 'Project A Store')],
        has_more: false,
      })
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(getByText('Project A Store')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('memstore_a:managed.memoryStores.archiveStore'))
      await Promise.resolve()
    })

    unmount()

    await act(async () => {
      archive.resolve({})
      await Promise.resolve()
    })

    expect(invalidateSpy).not.toHaveBeenCalledWith({ queryKey: ['memory-stores'] })
  })

  it('does not archive a memory store target that is no longer in the current store list', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText } = render(
      <QueryClientProvider client={queryClient}>
        <MemoryStoreListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Project A Store')).toBeTruthy()
    })

    await act(async () => {
      queryClient.setQueryData(
        ['memory-stores', 'org-a:project-a', '/memory_stores', undefined, false, 10],
        {
          data: [memoryStore('memstore_b', 'Project B Store')],
          has_more: false,
        },
      )
      fireEvent.click(getByText('memstore_a:managed.memoryStores.archiveStore'))
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith('memory_stores/a/archive')
  })
})
