import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: vi.fn(),
  }),
}))

vi.mock('react-markdown', () => ({
  default: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}))

vi.mock('remark-gfm', () => ({
  default: () => null,
}))

vi.mock('@/lib/i18n', () => ({
  i18n: { language: 'en' },
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock('@/lib/api-client', () => ({
  extractErrorFromResponse: vi.fn(async () => new Error('mock api error')),
  managedDelete: vi.fn(),
  managedGet: vi.fn(),
  managedPost: vi.fn(),
}))

vi.mock('@/lib/managed/errors', () => ({
  shouldRetryManagedResourceError: vi.fn(),
  toastOperationError: vi.fn(),
}))

vi.mock('@/components/managed/shared', () => ({
  ConfirmDialog: ({
    confirmLabel,
    onCancel,
    onConfirm,
    open,
    title,
  }: {
    confirmLabel: string
    onCancel: () => void
    onConfirm: () => void
    open: boolean
    title: string
  }) =>
    open ? (
      <div>
        <h2>{title}</h2>
        <button onClick={onCancel}>common.cancel</button>
        <button onClick={onConfirm}>{confirmLabel}</button>
      </div>
    ) : null,
  MonoId: ({ id }: { id: string }) => <span>{id}</span>,
  PageHeader: ({ action, title }: { action?: ReactNode; title: string }) => (
    <div>
      <h1>{title}</h1>
      {action}
    </div>
  ),
  RelativeTime: ({ date }: { date: string }) => <span>{date}</span>,
  ResourceErrorState: ({ resource }: { resource: string }) => <div>{resource}</div>,
  StatusBadge: ({ status }: { status: string }) => <span>{status}</span>,
}))

vi.mock('@/components/ui/button', () => ({
  Button: ({
    children,
    disabled,
    onClick,
    title,
    type = 'button',
  }: {
    children: ReactNode
    disabled?: boolean
    onClick?: () => void
    title?: string
    type?: 'button' | 'submit' | 'reset'
  }) => (
    <button type={type} disabled={disabled} onClick={onClick} title={title}>
      {children}
    </button>
  ),
}))

vi.mock('@/components/ui/dialog', () => ({
  Dialog: ({ children, open }: { children: ReactNode; open: boolean }) =>
    open ? <div>{children}</div> : null,
  DialogContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogFooter: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogHeader: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children: ReactNode }) => <h2>{children}</h2>,
}))

vi.mock('@/components/ui/dropdown-menu', () => ({
  DropdownMenu: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DropdownMenuContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DropdownMenuItem: ({ children, onClick }: { children: ReactNode; onClick?: () => void }) => (
    <button onClick={onClick}>{children}</button>
  ),
  DropdownMenuTrigger: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}))

vi.mock('@/components/ui/input', () => ({
  Input: ({ onChange, ...props }: React.InputHTMLAttributes<HTMLInputElement>) => (
    <input
      {...props}
      onChange={onChange}
      onInput={onChange as React.FormEventHandler<HTMLInputElement>}
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

import { managedDelete, managedGet, managedPost } from '@/lib/api-client'
import { useProjectStore } from '@/stores/managed/project-store'
import type { MemoryStore } from '@/types/managed'

import MemoryStoreDetailPage from './page'

const managedGetMock = managedGet as unknown as ReturnType<typeof vi.fn>
const managedPostMock = managedPost as unknown as ReturnType<typeof vi.fn>
const managedDeleteMock = managedDelete as unknown as ReturnType<typeof vi.fn>

function managedOptions(projectId = 'project-a') {
  return {
    headers: {
      'X-Org-Id': 'org-a',
      'X-Project-Id': projectId,
    },
    skipManagedContext: true,
  }
}

interface Memory {
  id: string
  path: string
  content: string
  content_size_bytes: number
  metadata: Record<string, string>
  created_at: string
  updated_at: string
}

function store(overrides: Partial<MemoryStore>): MemoryStore {
  return {
    id: 'store-default',
    name: 'Default Store',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

function memory(overrides: Partial<Memory>): Memory {
  return {
    id: 'mem-default',
    path: 'default.md',
    content: 'default content',
    content_size_bytes: 15,
    metadata: {},
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

function projectInfo(archivedAt: string | null = null) {
  return {
    id: 'project-a',
    org_id: 'org-a',
    name: 'Project A',
    slug: 'project-a',
    is_default: true,
    archived_at: archivedAt,
  }
}

function renderPage(storeId: string, queryClient: QueryClient) {
  const params = {
    status: 'fulfilled',
    value: { storeId },
    then: () => undefined,
  } as unknown as Promise<{ storeId: string }>

  return (
    <QueryClientProvider client={queryClient}>
      <MemoryStoreDetailPage params={params} />
    </QueryClientProvider>
  )
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

describe('MemoryStoreDetailPage object lifecycle', () => {
  beforeEach(() => {
    managedDeleteMock.mockReset()
    managedGetMock.mockReset()
    managedPostMock.mockReset()
    managedDeleteMock.mockResolvedValue({})
    managedPostMock.mockResolvedValue({})
    useProjectStore.setState({
      currentOrgId: 'org-a',
      currentProjectId: 'project-a',
      currentProject: projectInfo(null),
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
      currentProject: null,
      organizations: [],
      projects: [],
    })
    localStorage.clear()
  })

  it('refetches store detail resources after the managed project changes', async () => {
    const storeA = store({ id: 'store-a', name: 'Store A' })

    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/memory_stores/store-a') return storeA
      if (path === '/memory_stores/store-a/memories?limit=100&view=full') return []
      return { data: [] }
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText } = render(renderPage('store-a', queryClient))

    await waitFor(() => {
      expect(getByText('Store A')).toBeTruthy()
      expect(managedGetMock).toHaveBeenCalledWith('/memory_stores/store-a', managedOptions())
      expect(managedGetMock).toHaveBeenCalledWith(
        '/memory_stores/store-a/memories?limit=100&view=full',
        managedOptions(),
      )
    })
    expect(
      managedGetMock.mock.calls.filter(([path]) => path === '/memory_stores/store-a'),
    ).toHaveLength(1)
    expect(
      managedGetMock.mock.calls.filter(
        ([path]) => path === '/memory_stores/store-a/memories?limit=100&view=full',
      ),
    ).toHaveLength(1)

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(
        managedGetMock.mock.calls.filter(([path]) => path === '/memory_stores/store-a'),
      ).toHaveLength(2)
      expect(
        managedGetMock.mock.calls.filter(
          ([path]) => path === '/memory_stores/store-a/memories?limit=100&view=full',
        ),
      ).toHaveLength(2)
    })
    expect(managedGetMock).toHaveBeenCalledWith(
      '/memory_stores/store-a',
      managedOptions('project-b'),
    )
    expect(managedGetMock).toHaveBeenCalledWith(
      '/memory_stores/store-a/memories?limit=100&view=full',
      managedOptions('project-b'),
    )
  })

  it('does not keep a selected memory from the previous store when the route store changes', async () => {
    const storeA = store({ id: 'store-a', name: 'Store A' })
    const storeB = store({ id: 'store-b', name: 'Store B' })
    const memoryA = memory({
      id: 'mem-a',
      path: 'old.md',
      content: 'old content',
      content_size_bytes: 11,
    })

    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/memory_stores/store-a') return storeA
      if (path === '/memory_stores/store-b') return storeB
      if (path === '/memory_stores/store-a/memories?limit=100&view=full') return [memoryA]
      if (path === '/memory_stores/store-b/memories?limit=100&view=full') return []
      return { data: [] }
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText, getByTitle, queryByText, rerender } = render(
      renderPage('store-a', queryClient),
    )

    await waitFor(() => {
      expect(getByText('old.md')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('old.md'))
    })

    await waitFor(() => {
      expect(getByTitle('Edit')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByTitle('Edit'))
    })

    await act(async () => {
      rerender(renderPage('store-b', queryClient))
    })

    await waitFor(() => {
      expect(getByText('Store B')).toBeTruthy()
    })

    const staleSave = queryByText('common.save')
    if (staleSave) {
      await act(async () => {
        fireEvent.click(staleSave)
      })
    }

    expect(managedPostMock).not.toHaveBeenCalled()
    expect(queryByText('old.md')).toBeNull()
    expect(getByText('managed.memoryStores.selectMemory')).toBeTruthy()
  })

  it('does not save a selected memory after it leaves the current memory list', async () => {
    const storeA = store({ id: 'store-a', name: 'Store A' })
    const memoryA = memory({
      id: 'mem-a',
      path: 'old.md',
      content: 'old content',
      content_size_bytes: 11,
    })

    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/memory_stores/store-a') return storeA
      if (path === '/memory_stores/store-a/memories?limit=100&view=full') return [memoryA]
      return { data: [] }
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText, getByTitle, queryByText } = render(renderPage('store-a', queryClient))

    await waitFor(() => {
      expect(getByText('old.md')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('old.md'))
    })

    await act(async () => {
      fireEvent.click(getByTitle('Edit'))
    })

    await act(async () => {
      queryClient.setQueryData(['memory-store-memories', 'org-a:project-a', 'store-a'], [])
      const save = queryByText('common.save')
      if (save) {
        fireEvent.click(save)
      }
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith(
      '/memory_stores/store-a/memories/mem-a',
      { content: 'old content' },
      managedOptions(),
    )
    await waitFor(() => {
      expect(getByText('managed.memoryStores.selectMemory')).toBeTruthy()
    })
  })

  it('does not save a memory after the current store detail is no longer active', async () => {
    const storeA = store({ id: 'store-a', name: 'Store A' })
    const memoryA = memory({
      id: 'mem-a',
      path: 'old.md',
      content: 'old content',
      content_size_bytes: 11,
    })

    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/memory_stores/store-a') return storeA
      if (path === '/memory_stores/store-a/memories?limit=100&view=full') return [memoryA]
      return { data: [] }
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText, getByTitle } = render(renderPage('store-a', queryClient))

    await waitFor(() => {
      expect(getByText('old.md')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('old.md'))
    })

    await act(async () => {
      fireEvent.click(getByTitle('Edit'))
    })

    await act(async () => {
      queryClient.setQueryData(['memory-store', 'org-a:project-a', 'store-a'], {
        ...storeA,
        archived_at: '2026-01-02T00:00:00Z',
      })
      fireEvent.click(getByText('common.save'))
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith(
      '/memory_stores/store-a/memories/mem-a',
      { content: 'old content' },
      managedOptions(),
    )
  })

  it('does not delete a memory after it leaves the current memory list before confirmation', async () => {
    const storeA = store({ id: 'store-a', name: 'Store A' })
    const memoryA = memory({
      id: 'mem-a',
      path: 'old.md',
      content: 'old content',
      content_size_bytes: 11,
    })

    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/memory_stores/store-a') return storeA
      if (path === '/memory_stores/store-a/memories?limit=100&view=full') return [memoryA]
      return { data: [] }
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { container, getAllByText, getByText } = render(renderPage('store-a', queryClient))

    await waitFor(() => {
      expect(getByText('old.md')).toBeTruthy()
    })

    const deleteButtons = Array.from(container.querySelectorAll('button')).filter((button) =>
      button.className.includes('hover:text-destructive'),
    )
    expect(deleteButtons.length).toBeGreaterThan(0)

    await act(async () => {
      fireEvent.click(deleteButtons[0])
      await new Promise((resolve) => setTimeout(resolve, 0))
    })

    await waitFor(() => {
      expect(getByText('managed.memoryStores.deleteMemory')).toBeTruthy()
    })

    await act(async () => {
      queryClient.setQueryData(['memory-store-memories', 'org-a:project-a', 'store-a'], [])
      const deleteActions = getAllByText('common.delete')
      fireEvent.click(deleteActions[deleteActions.length - 1])
      await Promise.resolve()
    })

    expect(managedDeleteMock).not.toHaveBeenCalledWith(
      '/memory_stores/store-a/memories/mem-a',
      managedOptions(),
    )
  })

  it('does not delete a memory after the current store detail is no longer active', async () => {
    const storeA = store({ id: 'store-a', name: 'Store A' })
    const memoryA = memory({
      id: 'mem-a',
      path: 'old.md',
      content: 'old content',
      content_size_bytes: 11,
    })

    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/memory_stores/store-a') return storeA
      if (path === '/memory_stores/store-a/memories?limit=100&view=full') return [memoryA]
      return { data: [] }
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { container, getAllByText, getByText } = render(renderPage('store-a', queryClient))

    await waitFor(() => {
      expect(getByText('old.md')).toBeTruthy()
    })

    const deleteButtons = Array.from(container.querySelectorAll('button')).filter((button) =>
      button.className.includes('hover:text-destructive'),
    )
    expect(deleteButtons.length).toBeGreaterThan(0)

    await act(async () => {
      fireEvent.click(deleteButtons[0])
      await new Promise((resolve) => setTimeout(resolve, 0))
    })

    await waitFor(() => {
      expect(getByText('managed.memoryStores.deleteMemory')).toBeTruthy()
    })

    await act(async () => {
      queryClient.setQueryData(['memory-store', 'org-a:project-a', 'store-a'], {
        ...storeA,
        archived_at: '2026-01-02T00:00:00Z',
      })
      const deleteActions = getAllByText('common.delete')
      fireEvent.click(deleteActions[deleteActions.length - 1])
      await Promise.resolve()
    })

    expect(managedDeleteMock).not.toHaveBeenCalledWith(
      '/memory_stores/store-a/memories/mem-a',
      managedOptions(),
    )
  })

  it('does not reopen a delayed memory delete confirmation after the route store changes', async () => {
    const storeA = store({ id: 'store-a', name: 'Store A' })
    const storeB = store({ id: 'store-b', name: 'Store B' })
    const memoryA = memory({
      id: 'mem-a',
      path: 'old.md',
      content: 'old content',
      content_size_bytes: 11,
    })

    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/memory_stores/store-a') return storeA
      if (path === '/memory_stores/store-b') return storeB
      if (path === '/memory_stores/store-a/memories?limit=100&view=full') return [memoryA]
      if (path === '/memory_stores/store-b/memories?limit=100&view=full') return []
      return { data: [] }
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { container, getByText, queryByText, rerender } = render(
      renderPage('store-a', queryClient),
    )

    await waitFor(() => {
      expect(getByText('old.md')).toBeTruthy()
    })

    const deleteButtons = Array.from(container.querySelectorAll('button')).filter((button) =>
      button.className.includes('hover:text-destructive'),
    )
    expect(deleteButtons.length).toBeGreaterThan(0)

    fireEvent.click(deleteButtons[0])

    await act(async () => {
      rerender(renderPage('store-b', queryClient))
      await new Promise((resolve) => setTimeout(resolve, 0))
    })

    await waitFor(() => {
      expect(getByText('Store B')).toBeTruthy()
    })

    expect(queryByText('managed.memoryStores.deleteMemory')).toBeNull()
  })

  it('does not close a reopened create memory dialog when an older create finishes', async () => {
    const storeA = store({ id: 'store-a', name: 'Store A' })
    const create = deferred<Record<string, never>>()
    managedPostMock.mockReturnValueOnce(create.promise)

    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/memory_stores/store-a') return storeA
      if (path === '/memory_stores/store-a/memories?limit=100&view=full') return []
      return { data: [] }
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByPlaceholderText, getByText } = render(renderPage('store-a', queryClient))

    await waitFor(() => {
      expect(getByText('Store A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('managed.memoryStores.addMemory'))
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('notes/ideas.md'), {
        target: { value: 'old.md' },
      })
      fireEvent.input(getByPlaceholderText('managed.memoryStores.memContentPlaceholder'), {
        target: { value: 'old content' },
      })
    })

    await act(async () => {
      fireEvent.click(getByText('common.create'))
      await Promise.resolve()
    })

    await act(async () => {
      fireEvent.click(getByText('common.cancel'))
    })

    await act(async () => {
      fireEvent.click(getByText('managed.memoryStores.addMemory'))
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('notes/ideas.md'), {
        target: { value: 'new.md' },
      })
      fireEvent.input(getByPlaceholderText('managed.memoryStores.memContentPlaceholder'), {
        target: { value: 'new content' },
      })
    })

    await act(async () => {
      create.resolve({})
      await Promise.resolve()
    })

    expect((getByPlaceholderText('notes/ideas.md') as HTMLInputElement).value).toBe('new.md')
  })

  it('does not create a memory after the current store detail is no longer active', async () => {
    const storeA = store({ id: 'store-a', name: 'Store A' })

    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/memory_stores/store-a') return storeA
      if (path === '/memory_stores/store-a/memories?limit=100&view=full') return []
      return { data: [] }
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByPlaceholderText, getByText } = render(renderPage('store-a', queryClient))

    await waitFor(() => {
      expect(getByText('Store A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('managed.memoryStores.addMemory'))
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('notes/ideas.md'), {
        target: { value: 'notes/race.md' },
      })
      fireEvent.input(getByPlaceholderText('managed.memoryStores.memContentPlaceholder'), {
        target: { value: 'content written before archive' },
      })
    })

    await act(async () => {
      queryClient.setQueryData(['memory-store', 'org-a:project-a', 'store-a'], {
        ...storeA,
        archived_at: '2026-01-02T00:00:00Z',
      })
      fireEvent.click(getByText('common.create'))
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith(
      '/memory_stores/store-a/memories',
      {
        path: 'notes/race.md',
        content: 'content written before archive',
      },
      managedOptions(),
    )
  })

  it('does not leave a reopened memory edit when an older save finishes', async () => {
    const storeA = store({ id: 'store-a', name: 'Store A' })
    const memoryA = memory({
      id: 'mem-a',
      path: 'notes.md',
      content: 'initial content',
      content_size_bytes: 15,
    })
    const save = deferred<Record<string, never>>()
    managedPostMock.mockReturnValueOnce(save.promise)

    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/memory_stores/store-a') return storeA
      if (path === '/memory_stores/store-a/memories?limit=100&view=full') return [memoryA]
      return { data: [] }
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByDisplayValue, getByText, getByTitle } = render(renderPage('store-a', queryClient))

    await waitFor(() => {
      expect(getByText('notes.md')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('notes.md'))
    })

    await act(async () => {
      fireEvent.click(getByTitle('Edit'))
    })

    await act(async () => {
      fireEvent.input(getByDisplayValue('initial content'), {
        target: { value: 'old saved content' },
      })
    })

    await act(async () => {
      fireEvent.click(getByText('common.save'))
      await Promise.resolve()
    })

    await act(async () => {
      fireEvent.click(getByText('common.cancel'))
    })

    await act(async () => {
      fireEvent.click(getByTitle('Edit'))
    })

    await act(async () => {
      fireEvent.input(getByDisplayValue('initial content'), {
        target: { value: 'new draft content' },
      })
    })

    await act(async () => {
      save.resolve({})
      await Promise.resolve()
    })

    expect((getByDisplayValue('new draft content') as HTMLTextAreaElement).value).toBe(
      'new draft content',
    )
  })

  it('does not close a new archive confirmation when an older archive finishes', async () => {
    const storeA = store({ id: 'store-a', name: 'Store A' })
    const archive = deferred<Record<string, never>>()
    managedPostMock.mockReturnValueOnce(archive.promise)

    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/memory_stores/store-a') return storeA
      if (path === '/memory_stores/store-a/memories?limit=100&view=full') return []
      return { data: [] }
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getAllByRole, getByRole, getByText } = render(renderPage('store-a', queryClient))

    await waitFor(() => {
      expect(getByText('Store A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('common.archive'))
    })

    await act(async () => {
      const archiveButtons = getAllByRole('button', { name: /common\.archive/ })
      fireEvent.click(archiveButtons[archiveButtons.length - 1])
      await Promise.resolve()
    })

    await act(async () => {
      fireEvent.click(getByRole('button', { name: 'common.cancel' }))
    })

    await act(async () => {
      fireEvent.click(getByText('common.archive'))
    })

    await act(async () => {
      archive.resolve({})
      await Promise.resolve()
    })

    expect(getByRole('button', { name: 'common.cancel' })).toBeTruthy()
  })

  it('does not archive the memory store after the current store detail is no longer active', async () => {
    const storeA = store({ id: 'store-a', name: 'Store A' })

    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/memory_stores/store-a') return storeA
      if (path === '/memory_stores/store-a/memories?limit=100&view=full') return []
      return { data: [] }
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getAllByRole, getByText } = render(renderPage('store-a', queryClient))

    await waitFor(() => {
      expect(getByText('Store A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('common.archive'))
    })

    await act(async () => {
      queryClient.setQueryData(['memory-store', 'org-a:project-a', 'store-a'], {
        ...storeA,
        archived_at: '2026-01-02T00:00:00Z',
      })
      const archiveButtons = getAllByRole('button', { name: /common\.archive/ })
      fireEvent.click(archiveButtons[archiveButtons.length - 1])
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith(
      '/memory_stores/store-a/archive',
      {},
      managedOptions(),
    )
  })

  it('does not delete the memory store after the current store detail is no longer active', async () => {
    const storeA = store({ id: 'store-a', name: 'Store A' })

    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/memory_stores/store-a') return storeA
      if (path === '/memory_stores/store-a/memories?limit=100&view=full') return []
      return { data: [] }
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getAllByText, getByText } = render(renderPage('store-a', queryClient))

    await waitFor(() => {
      expect(getByText('Store A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('common.delete'))
    })

    await act(async () => {
      queryClient.setQueryData(['memory-store', 'org-a:project-a', 'store-a'], {
        ...storeA,
        archived_at: '2026-01-02T00:00:00Z',
      })
      const deleteActions = getAllByText('common.delete')
      fireEvent.click(deleteActions[deleteActions.length - 1])
      await Promise.resolve()
    })

    expect(managedDeleteMock).not.toHaveBeenCalledWith('/memory_stores/store-a', managedOptions())
  })

  it('does not invalidate memory stores from a delete completion after the page unmounts', async () => {
    const storeA = store({ id: 'store-a', name: 'Store A' })
    const deleteStore = deferred<Record<string, never>>()
    managedDeleteMock.mockReturnValueOnce(deleteStore.promise)

    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/memory_stores/store-a') return storeA
      if (path === '/memory_stores/store-a/memories?limit=100&view=full') return []
      return { data: [] }
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    const { getAllByRole, getByText, unmount } = render(renderPage('store-a', queryClient))

    await waitFor(() => {
      expect(getByText('Store A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('common.delete'))
    })

    await act(async () => {
      const deleteButtons = getAllByRole('button', { name: /common\.delete/ })
      fireEvent.click(deleteButtons[deleteButtons.length - 1])
      await Promise.resolve()
    })

    unmount()

    await act(async () => {
      deleteStore.resolve({})
      await Promise.resolve()
    })

    expect(invalidateSpy).not.toHaveBeenCalledWith({
      queryKey: ['memory-stores', 'org-a:project-a'],
    })
  })

  it('hides project write actions when the current project is archived', async () => {
    useProjectStore.setState({
      currentProject: projectInfo('2026-01-02T00:00:00Z'),
    })
    const storeA = store({ id: 'store-a', name: 'Store A' })
    const memoryA = memory({
      id: 'mem-a',
      path: 'notes.md',
      content: 'initial content',
      content_size_bytes: 15,
    })

    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/memory_stores/store-a') return storeA
      if (path === '/memory_stores/store-a/memories?limit=100&view=full') return [memoryA]
      return { data: [] }
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { container, getByText, queryByText, queryByTitle } = render(
      renderPage('store-a', queryClient),
    )

    await waitFor(() => {
      expect(getByText('Store A')).toBeTruthy()
      expect(getByText('notes.md')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('notes.md'))
    })

    expect(queryByText('managed.memoryStores.addMemory')).toBeNull()
    expect(queryByText('common.archive')).toBeNull()
    expect(queryByText('common.delete')).toBeNull()
    expect(queryByTitle('Edit')).toBeNull()
    expect(
      Array.from(container.querySelectorAll('button')).filter((button) =>
        button.className.includes('hover:text-destructive'),
      ),
    ).toHaveLength(0)
  })

  it('does not save a memory from old edit controls after the current project is archived', async () => {
    const storeA = store({ id: 'store-a', name: 'Store A' })
    const memoryA = memory({
      id: 'mem-a',
      path: 'notes.md',
      content: 'initial content',
      content_size_bytes: 15,
    })

    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/memory_stores/store-a') return storeA
      if (path === '/memory_stores/store-a/memories?limit=100&view=full') return [memoryA]
      return { data: [] }
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByDisplayValue, getByText, getByTitle } = render(renderPage('store-a', queryClient))

    await waitFor(() => {
      expect(getByText('notes.md')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('notes.md'))
    })

    await act(async () => {
      fireEvent.click(getByTitle('Edit'))
    })

    await act(async () => {
      fireEvent.input(getByDisplayValue('initial content'), {
        target: { value: 'content written before project archive' },
      })
    })

    const saveButton = getByText('common.save')

    await act(async () => {
      useProjectStore.setState({
        currentProject: projectInfo('2026-01-02T00:00:00Z'),
      })
      fireEvent.click(saveButton)
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith(
      '/memory_stores/store-a/memories/mem-a',
      { content: 'content written before project archive' },
      managedOptions(),
    )
  })

  it('does not create a memory from an old create dialog after the current project is archived', async () => {
    const storeA = store({ id: 'store-a', name: 'Store A' })

    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/memory_stores/store-a') return storeA
      if (path === '/memory_stores/store-a/memories?limit=100&view=full') return []
      return { data: [] }
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByPlaceholderText, getByText } = render(renderPage('store-a', queryClient))

    await waitFor(() => {
      expect(getByText('Store A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('managed.memoryStores.addMemory'))
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('notes/ideas.md'), {
        target: { value: 'notes/project-archived.md' },
      })
      fireEvent.input(getByPlaceholderText('managed.memoryStores.memContentPlaceholder'), {
        target: { value: 'content written before project archive' },
      })
    })

    const createButton = getByText('common.create')

    await act(async () => {
      useProjectStore.setState({
        currentProject: projectInfo('2026-01-02T00:00:00Z'),
      })
      fireEvent.click(createButton)
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith(
      '/memory_stores/store-a/memories',
      {
        path: 'notes/project-archived.md',
        content: 'content written before project archive',
      },
      managedOptions(),
    )
  })

  it('does not archive the memory store from an old confirmation after the current project is archived', async () => {
    const storeA = store({ id: 'store-a', name: 'Store A' })

    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/memory_stores/store-a') return storeA
      if (path === '/memory_stores/store-a/memories?limit=100&view=full') return []
      return { data: [] }
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getAllByRole, getByText } = render(renderPage('store-a', queryClient))

    await waitFor(() => {
      expect(getByText('Store A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('common.archive'))
    })

    const archiveButtons = getAllByRole('button', { name: /common\.archive/ })
    const confirmArchive = archiveButtons[archiveButtons.length - 1]

    await act(async () => {
      useProjectStore.setState({
        currentProject: projectInfo('2026-01-02T00:00:00Z'),
      })
      fireEvent.click(confirmArchive)
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith(
      '/memory_stores/store-a/archive',
      {},
      managedOptions(),
    )
  })

  it('does not delete the memory store from an old confirmation after the current project is archived', async () => {
    const storeA = store({ id: 'store-a', name: 'Store A' })

    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/memory_stores/store-a') return storeA
      if (path === '/memory_stores/store-a/memories?limit=100&view=full') return []
      return { data: [] }
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getAllByText, getByText } = render(renderPage('store-a', queryClient))

    await waitFor(() => {
      expect(getByText('Store A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('common.delete'))
    })

    const deleteActions = getAllByText('common.delete')
    const confirmDelete = deleteActions[deleteActions.length - 1]

    await act(async () => {
      useProjectStore.setState({
        currentProject: projectInfo('2026-01-02T00:00:00Z'),
      })
      fireEvent.click(confirmDelete)
      await Promise.resolve()
    })

    expect(managedDeleteMock).not.toHaveBeenCalledWith('/memory_stores/store-a', managedOptions())
  })

  it('does not delete a memory from an old confirmation after the current project is archived', async () => {
    const storeA = store({ id: 'store-a', name: 'Store A' })
    const memoryA = memory({
      id: 'mem-a',
      path: 'notes.md',
      content: 'initial content',
      content_size_bytes: 15,
    })

    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/memory_stores/store-a') return storeA
      if (path === '/memory_stores/store-a/memories?limit=100&view=full') return [memoryA]
      return { data: [] }
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { container, getAllByText, getByText } = render(renderPage('store-a', queryClient))

    await waitFor(() => {
      expect(getByText('notes.md')).toBeTruthy()
    })

    const deleteButtons = Array.from(container.querySelectorAll('button')).filter((button) =>
      button.className.includes('hover:text-destructive'),
    )
    expect(deleteButtons.length).toBeGreaterThan(0)

    await act(async () => {
      fireEvent.click(deleteButtons[0])
      await new Promise((resolve) => setTimeout(resolve, 0))
    })

    await waitFor(() => {
      expect(getByText('managed.memoryStores.deleteMemory')).toBeTruthy()
    })

    const deleteActions = getAllByText('common.delete')
    const confirmDelete = deleteActions[deleteActions.length - 1]

    await act(async () => {
      useProjectStore.setState({
        currentProject: projectInfo('2026-01-02T00:00:00Z'),
      })
      fireEvent.click(confirmDelete)
      await Promise.resolve()
    })

    expect(managedDeleteMock).not.toHaveBeenCalledWith(
      '/memory_stores/store-a/memories/mem-a',
      managedOptions(),
    )
  })
})
