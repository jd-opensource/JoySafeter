import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({ t: (key: string, _params?: unknown) => key }),
}))

vi.mock('@/lib/api-client', () => ({
  managedDelete: vi.fn(),
  managedGet: vi.fn(),
  managedPost: vi.fn(),
}))

vi.mock('@/providers/permissions-provider', () => ({
  useUserPermissionsContext: () => ({ canEdit: true }),
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
    actionMenu?: (row: ApiKeyRecord) => { label: string; onClick: () => void }[]
    data: ApiKeyRecord[]
  }) => (
    <div>
      {data.map((apiKey) => (
        <div key={apiKey.id}>
          <span>{apiKey.name}</span>
          {actionMenu?.(apiKey).map((item) => (
            <button key={item.label} onClick={item.onClick}>
              {apiKey.id}:{item.label}
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
  DialogDescription: ({ children }: { children: ReactNode }) => <p>{children}</p>,
  DialogFooter: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogHeader: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children: ReactNode }) => <h2>{children}</h2>,
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

vi.mock('@/components/ui/select', () => ({
  Select: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectItem: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectTrigger: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectValue: () => null,
}))

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement
globalThis.localStorage = dom.window.localStorage
globalThis.navigator.clipboard = {
  writeText: vi.fn(),
} as unknown as Clipboard

import { managedDelete, managedGet, managedPost } from '@/lib/api-client'
import { useProjectStore } from '@/stores/managed/project-store'

import ApiKeysPage from './page'

interface ApiKeyRecord {
  id: string
  project_id: string
  name: string
  key_prefix: string
  role: string
  created_at?: string
  last_used_at?: string
}

const managedDeleteMock = managedDelete as unknown as ReturnType<typeof vi.fn>
const managedGetMock = managedGet as unknown as ReturnType<typeof vi.fn>
const managedPostMock = managedPost as unknown as ReturnType<typeof vi.fn>

function apiKey(id: string, name: string): ApiKeyRecord {
  return {
    id,
    project_id: 'project-a',
    name,
    key_prefix: id.slice(0, 6),
    role: 'developer',
    created_at: '2026-01-01T00:00:00Z',
  }
}

function renderApiKeysPage(queryClient: QueryClient) {
  return render(
    <QueryClientProvider client={queryClient}>
      <ApiKeysPage />
    </QueryClientProvider>,
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

describe('ApiKeysPage object lifecycle', () => {
  beforeEach(() => {
    managedDeleteMock.mockReset()
    managedGetMock.mockReset()
    managedPostMock.mockReset()
    managedDeleteMock.mockResolvedValue({})
    managedGetMock.mockResolvedValue([])
    managedPostMock.mockResolvedValue({ raw_key: 'raw-project-a-key' })
    useProjectStore.setState({
      currentOrgId: 'org-a',
      currentProjectId: 'project-a',
      organizations: [],
      projects: [],
    })
  })

  afterEach(() => {
    cleanup()
    vi.useRealTimers()
    vi.restoreAllMocks()
    useProjectStore.setState({
      currentOrgId: null,
      currentProjectId: null,
      organizations: [],
      projects: [],
    })
    localStorage.clear()
  })

  it('does not keep a newly created raw key visible after the managed project changes', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getAllByRole, getByPlaceholderText, queryByText, rerender } =
      renderApiKeysPage(queryClient)

    await act(async () => {
      fireEvent.click(getAllByRole('button', { name: /manage\.apiKeys\.create/ })[0])
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('manage.apiKeys.namePlaceholder'), {
        target: { value: 'Project A key' },
      })
    })

    await act(async () => {
      fireEvent.click(getAllByRole('button', { name: /manage\.apiKeys\.create/ })[1])
    })

    await waitFor(() => {
      expect(queryByText('raw-project-a-key')).toBeTruthy()
    })

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      rerender(
        <QueryClientProvider client={queryClient}>
          <ApiKeysPage />
        </QueryClientProvider>,
      )
    })

    expect(queryByText('raw-project-a-key')).toBeNull()
  })

  it('keeps raw key copy feedback visible for two seconds after the latest copy', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getAllByRole, getByPlaceholderText, getByText } = renderApiKeysPage(queryClient)

    await act(async () => {
      fireEvent.click(getAllByRole('button', { name: /manage\.apiKeys\.create/ })[0])
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('manage.apiKeys.namePlaceholder'), {
        target: { value: 'Project A key' },
      })
    })

    await act(async () => {
      fireEvent.click(getAllByRole('button', { name: /manage\.apiKeys\.create/ })[1])
    })

    const rawKey = getByText('raw-project-a-key')
    const copyButton = rawKey.parentElement?.querySelector('button') as HTMLButtonElement
    expect(copyButton).toBeTruthy()

    vi.useFakeTimers()

    await act(async () => {
      fireEvent.click(copyButton)
    })

    expect(copyButton.querySelector('.lucide-check')).toBeTruthy()

    await act(async () => {
      vi.advanceTimersByTime(1000)
      fireEvent.click(copyButton)
    })

    await act(async () => {
      vi.advanceTimersByTime(1500)
    })

    expect(copyButton.querySelector('.lucide-check')).toBeTruthy()
  })

  it('does not show a raw key when create finishes after the managed project changes', async () => {
    const pendingCreate = deferred<{ raw_key: string }>()
    managedPostMock.mockReturnValueOnce(pendingCreate.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getAllByRole, getByPlaceholderText, queryByText, rerender } =
      renderApiKeysPage(queryClient)

    await act(async () => {
      fireEvent.click(getAllByRole('button', { name: /manage\.apiKeys\.create/ })[0])
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('manage.apiKeys.namePlaceholder'), {
        target: { value: 'Project A key' },
      })
    })

    await act(async () => {
      fireEvent.click(getAllByRole('button', { name: /manage\.apiKeys\.create/ })[1])
      await Promise.resolve()
    })

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      rerender(
        <QueryClientProvider client={queryClient}>
          <ApiKeysPage />
        </QueryClientProvider>,
      )
    })

    await act(async () => {
      pendingCreate.resolve({ raw_key: 'raw-project-a-key' })
      await pendingCreate.promise
    })

    expect(queryByText('raw-project-a-key')).toBeNull()
  })

  it('does not create an api key from an old create dialog after the managed project changes in the same tick', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getAllByRole, getByPlaceholderText } = renderApiKeysPage(queryClient)

    await act(async () => {
      fireEvent.click(getAllByRole('button', { name: /manage\.apiKeys\.create/ })[0])
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('manage.apiKeys.namePlaceholder'), {
        target: { value: 'Project A production deploy key' },
      })
    })

    const oldCreateButton = getAllByRole('button', { name: /manage\.apiKeys\.create/ })[1]

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      fireEvent.click(oldCreateButton)
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith('/auth/api-keys', {
      name: 'Project A production deploy key',
      role: 'developer',
    })
  })

  it('does not close a reopened create dialog when an older api key create finishes', async () => {
    const pendingCreate = deferred<{ raw_key: string }>()
    managedPostMock.mockReturnValueOnce(pendingCreate.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getAllByRole, getByPlaceholderText, getByText } = renderApiKeysPage(queryClient)

    await act(async () => {
      fireEvent.click(getAllByRole('button', { name: /manage\.apiKeys\.create/ })[0])
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('manage.apiKeys.namePlaceholder'), {
        target: { value: 'Old key' },
      })
    })

    await act(async () => {
      fireEvent.click(getAllByRole('button', { name: /manage\.apiKeys\.create/ })[1])
      await Promise.resolve()
    })

    await act(async () => {
      fireEvent.click(getByText('dialog-close'))
    })

    await act(async () => {
      fireEvent.click(getAllByRole('button', { name: /manage\.apiKeys\.create/ })[0])
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('manage.apiKeys.namePlaceholder'), {
        target: { value: 'New key' },
      })
    })

    await act(async () => {
      pendingCreate.resolve({ raw_key: 'raw-old-key' })
      await Promise.resolve()
    })

    expect((getByPlaceholderText('manage.apiKeys.namePlaceholder') as HTMLInputElement).value).toBe(
      'New key',
    )
  })

  it('does not revoke a key that is no longer in the current keys list', async () => {
    const keyA = apiKey('key-a', 'Project A key')
    const keyB = apiKey('key-b', 'Project B key')
    managedGetMock.mockResolvedValue([keyA])

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText, queryByText } = renderApiKeysPage(queryClient)

    await waitFor(() => {
      expect(getByText('Project A key')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('key-a:manage.apiKeys.revoke'))
    })

    await act(async () => {
      queryClient.setQueryData(['api-keys', 'org-a', 'project-a'], [keyB])
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(getByText('Project B key')).toBeTruthy()
    })

    const revokeButton = queryByText('manage.apiKeys.revoke')
    if (revokeButton) {
      await act(async () => {
        fireEvent.click(revokeButton)
      })
    }

    expect(managedDeleteMock).not.toHaveBeenCalled()
  })

  it('does not revoke a key that leaves the current keys list during confirmation', async () => {
    const keyA = apiKey('key-a', 'Project A key')
    const keyB = apiKey('key-b', 'Project B key')
    managedGetMock.mockResolvedValue([keyA])

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText } = renderApiKeysPage(queryClient)

    await waitFor(() => {
      expect(getByText('Project A key')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('key-a:manage.apiKeys.revoke'))
    })

    await act(async () => {
      queryClient.setQueryData(['api-keys', 'org-a', 'project-a'], [keyB])
      fireEvent.click(getByText('manage.apiKeys.revoke'))
      await Promise.resolve()
    })

    expect(managedDeleteMock).not.toHaveBeenCalledWith('/auth/api-keys/key-a')
  })

  it('does not revoke an old project api key after the managed project changes in the same tick', async () => {
    const keyA = apiKey('key-a', 'Project A deploy key')
    managedGetMock.mockResolvedValue([keyA])

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText } = renderApiKeysPage(queryClient)

    await waitFor(() => {
      expect(getByText('Project A deploy key')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('key-a:manage.apiKeys.revoke'))
    })

    const oldRevokeButton = getByText('manage.apiKeys.revoke')

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      fireEvent.click(oldRevokeButton)
      await Promise.resolve()
    })

    expect(managedDeleteMock).not.toHaveBeenCalledWith('/auth/api-keys/key-a')
  })

  it('does not invalidate api keys from a revoke completion after the managed project changes', async () => {
    const keyA = apiKey('key-a', 'Project A key')
    const pendingRevoke = deferred<Record<string, never>>()
    managedGetMock.mockResolvedValue([keyA])
    managedDeleteMock.mockReturnValueOnce(pendingRevoke.promise)

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    const { getByText, rerender } = renderApiKeysPage(queryClient)

    await waitFor(() => {
      expect(getByText('Project A key')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('key-a:manage.apiKeys.revoke'))
    })

    await act(async () => {
      fireEvent.click(getByText('manage.apiKeys.revoke'))
      await Promise.resolve()
    })

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      rerender(
        <QueryClientProvider client={queryClient}>
          <ApiKeysPage />
        </QueryClientProvider>,
      )
    })

    await act(async () => {
      pendingRevoke.resolve({})
      await Promise.resolve()
    })

    expect(invalidateSpy).not.toHaveBeenCalledWith({ queryKey: ['api-keys'] })
  })

  it('does not invalidate api keys from a create completion after the page unmounts', async () => {
    const pendingCreate = deferred<{ raw_key: string }>()
    managedPostMock.mockReturnValueOnce(pendingCreate.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    const { getAllByRole, getByPlaceholderText, unmount } = renderApiKeysPage(queryClient)

    await act(async () => {
      fireEvent.click(getAllByRole('button', { name: /manage\.apiKeys\.create/ })[0])
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('manage.apiKeys.namePlaceholder'), {
        target: { value: 'Unmounted key' },
      })
    })

    await act(async () => {
      fireEvent.click(getAllByRole('button', { name: /manage\.apiKeys\.create/ })[1])
      await Promise.resolve()
    })

    unmount()

    await act(async () => {
      pendingCreate.resolve({ raw_key: 'raw-unmounted-key' })
      await Promise.resolve()
    })

    expect(invalidateSpy).not.toHaveBeenCalledWith({ queryKey: ['api-keys'] })
  })

  it('does not invalidate api keys from a revoke completion after the page unmounts', async () => {
    const keyA = apiKey('key-a', 'Project A key')
    const pendingRevoke = deferred<Record<string, never>>()
    managedGetMock.mockResolvedValue([keyA])
    managedDeleteMock.mockReturnValueOnce(pendingRevoke.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    const { getByText, unmount } = renderApiKeysPage(queryClient)

    await waitFor(() => {
      expect(getByText('Project A key')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('key-a:manage.apiKeys.revoke'))
    })

    await act(async () => {
      fireEvent.click(getByText('manage.apiKeys.revoke'))
      await Promise.resolve()
    })

    unmount()

    await act(async () => {
      pendingRevoke.resolve({})
      await Promise.resolve()
    })

    expect(invalidateSpy).not.toHaveBeenCalledWith({ queryKey: ['api-keys'] })
  })
})
