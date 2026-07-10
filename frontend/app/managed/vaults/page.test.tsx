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
  managedDelete: vi.fn(),
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
  DataTable: ({
    actionMenu,
    data,
  }: {
    actionMenu?: (row: VaultRecord) => { label: string; onClick: () => void }[]
    data: VaultRecord[]
  }) => (
    <div>
      {data.map((vault) => (
        <div key={vault.id}>
          <span>{vault.name}</span>
          {actionMenu?.(vault).map((item) => (
            <button key={item.label} onClick={item.onClick}>
              {vault.id}:{item.label}
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
    open,
  }: {
    children: ReactNode
    onOpenChange?: (open: boolean) => void
    open: boolean
  }) => (open ? <div>{children}</div> : null),
  DialogContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogDescription: ({ children }: { children: ReactNode }) => <p>{children}</p>,
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

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement
globalThis.localStorage = dom.window.localStorage

import { managedDelete, managedGet, managedPost } from '@/lib/api-client'
import { useProjectStore } from '@/stores/managed/project-store'

import VaultListPage from './page'

interface VaultRecord {
  id: string
  name: string
  archived_at?: string | null
  created_at: string
}

const managedGetMock = managedGet as unknown as ReturnType<typeof vi.fn>
const managedDeleteMock = managedDelete as unknown as ReturnType<typeof vi.fn>
const managedPostMock = managedPost as unknown as ReturnType<typeof vi.fn>

function vault(id: string, name: string): VaultRecord {
  return {
    id,
    name,
    archived_at: null,
    created_at: '2026-01-01T00:00:00Z',
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

describe('VaultListPage object lifecycle', () => {
  beforeEach(() => {
    managedDeleteMock.mockReset()
    managedGetMock.mockReset()
    managedPostMock.mockReset()
    managedDeleteMock.mockResolvedValue({})
    managedGetMock.mockResolvedValue({ data: [vault('vault-a', 'Vault A')], has_more: false })
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

  it('does not archive a vault target that is no longer in the current vault list', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText, queryAllByRole } = render(
      <QueryClientProvider client={queryClient}>
        <VaultListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Vault A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('vault-a:managed.vaults.archiveVault'))
    })

    await act(async () => {
      queryClient.setQueryData(['vaults', 'org-a:project-a', '/vaults', undefined, false, 10], {
        data: [vault('vault-b', 'Vault B')],
        has_more: false,
      })
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(getByText('Vault B')).toBeTruthy()
    })

    const archiveButtons = queryAllByRole('button', { name: 'common.archive' })
    if (archiveButtons.length > 0) {
      await act(async () => {
        fireEvent.click(archiveButtons[archiveButtons.length - 1])
      })
    }

    expect(managedPostMock).not.toHaveBeenCalledWith('/vaults/vault-a/archive', {})
  })

  it('does not close a new archive confirmation when an older archive finishes', async () => {
    const archive = deferred<Record<string, never>>()
    managedGetMock.mockResolvedValue({
      data: [vault('vault-a', 'Vault A'), vault('vault-b', 'Vault B')],
      has_more: false,
    })
    managedPostMock.mockReturnValueOnce(archive.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByRole, getByText } = render(
      <QueryClientProvider client={queryClient}>
        <VaultListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Vault A')).toBeTruthy()
      expect(getByText('Vault B')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('vault-a:managed.vaults.archiveVault'))
    })

    await act(async () => {
      fireEvent.click(getByRole('button', { name: 'common.archive' }))
      await Promise.resolve()
    })

    await act(async () => {
      fireEvent.click(getByRole('button', { name: 'common.cancel' }))
    })

    await act(async () => {
      fireEvent.click(getByText('vault-b:managed.vaults.archiveVault'))
    })

    await act(async () => {
      archive.resolve({})
      await Promise.resolve()
    })

    expect(getByRole('button', { name: 'common.cancel' })).toBeTruthy()
  })

  it('does not invalidate vaults from an archive completion after the page unmounts', async () => {
    const archive = deferred<Record<string, never>>()
    managedPostMock.mockReturnValueOnce(archive.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    const { getByRole, getByText, unmount } = render(
      <QueryClientProvider client={queryClient}>
        <VaultListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Vault A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('vault-a:managed.vaults.archiveVault'))
    })

    await act(async () => {
      fireEvent.click(getByRole('button', { name: 'common.archive' }))
      await Promise.resolve()
    })

    unmount()

    await act(async () => {
      archive.resolve({})
      await Promise.resolve()
    })

    expect(invalidateSpy).not.toHaveBeenCalledWith({ queryKey: ['vaults'] })
  })

  it('does not archive an old project vault after the managed project changes in the same tick', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByRole, getByText } = render(
      <QueryClientProvider client={queryClient}>
        <VaultListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Vault A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('vault-a:managed.vaults.archiveVault'))
    })

    const oldArchiveButton = getByRole('button', { name: 'common.archive' })

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      fireEvent.click(oldArchiveButton)
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith('/vaults/vault-a/archive', {})
  })

  it('exposes the delete action for an active vault row', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText } = render(
      <QueryClientProvider client={queryClient}>
        <VaultListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Vault A')).toBeTruthy()
    })

    expect(getByText('vault-a:common.delete')).toBeTruthy()
  })

  it('does not delete a vault target that leaves the current vault list before confirmation', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByRole, getByText } = render(
      <QueryClientProvider client={queryClient}>
        <VaultListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Vault A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('vault-a:common.delete'))
    })

    await act(async () => {
      queryClient.setQueryData(['vaults', 'org-a:project-a', '/vaults', undefined, false, 10], {
        data: [vault('vault-b', 'Vault B')],
        has_more: false,
      })
      fireEvent.click(getByRole('button', { name: 'common.delete' }))
      await Promise.resolve()
    })

    expect(managedDeleteMock).not.toHaveBeenCalledWith('/vaults/vault-a')
  })

  it('does not delete an old project vault after the managed project changes in the same tick', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByRole, getByText } = render(
      <QueryClientProvider client={queryClient}>
        <VaultListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Vault A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('vault-a:common.delete'))
    })

    const oldDeleteButton = getByRole('button', { name: 'common.delete' })

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      fireEvent.click(oldDeleteButton)
      await Promise.resolve()
    })

    expect(managedDeleteMock).not.toHaveBeenCalledWith('/vaults/vault-a')
  })

  it('does not archive a vault target that leaves the current vault list during confirmation', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByRole, getByText } = render(
      <QueryClientProvider client={queryClient}>
        <VaultListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Vault A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('vault-a:managed.vaults.archiveVault'))
    })

    await act(async () => {
      queryClient.setQueryData(['vaults', 'org-a:project-a', '/vaults', undefined, false, 10], {
        data: [vault('vault-b', 'Vault B')],
        has_more: false,
      })
      fireEvent.click(getByRole('button', { name: 'common.archive' }))
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith('/vaults/vault-a/archive', {})
  })
})
