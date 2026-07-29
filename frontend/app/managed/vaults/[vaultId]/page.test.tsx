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
  shouldRetryManagedResourceError: vi.fn(() => false),
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
  DataTable: ({
    actionMenu,
    data,
  }: {
    actionMenu?: (row: CredentialRecord) => { label: string; onClick: () => void }[]
    data: CredentialRecord[]
  }) => (
    <div>
      {data.map((credential) => (
        <div key={credential.id}>
          <span>{credential.name}</span>
          {actionMenu?.(credential).map((item) => (
            <button key={item.label} onClick={item.onClick}>
              {credential.id}:{item.label}
            </button>
          ))}
        </div>
      ))}
    </div>
  ),
  FilterBar: () => null,
  MonoId: ({ id }: { id: string }) => <span>{id}</span>,
  PageHeader: ({
    action,
    title,
  }: {
    action?: ReactNode
    breadcrumb?: { label: string; to?: string }[]
    title: string
    titleExtra?: ReactNode
  }) => (
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
  Dialog: ({ children, open }: { children: ReactNode; open: boolean }) =>
    open ? <div>{children}</div> : null,
  DialogContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogDescription: ({ children }: { children: ReactNode }) => <p>{children}</p>,
  DialogHeader: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children: ReactNode }) => <h2>{children}</h2>,
}))

vi.mock('@/components/ui/input', () => ({
  Input: ({
    autoFocus: _autoFocus,
    onChange,
    ...props
  }: React.InputHTMLAttributes<HTMLInputElement>) => (
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

import VaultDetailPage from './page'

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

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

function vault(id: string, name: string) {
  return {
    id,
    name,
    archived_at: null,
    created_at: '2026-01-01T00:00:00Z',
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

interface CredentialRecord {
  id: string
  name: string
  credential_type: string
  archived_at?: string | null
}

function credential(id: string, name: string): CredentialRecord {
  return {
    id,
    name,
    credential_type: 'static_bearer',
    archived_at: null,
  }
}

function renderVaultPage(queryClient: QueryClient, vaultId: string) {
  const params = {
    status: 'fulfilled',
    value: { vaultId },
    then: () => undefined,
  } as unknown as Promise<{ vaultId: string }>

  return (
    <QueryClientProvider client={queryClient}>
      <VaultDetailPage params={params} />
    </QueryClientProvider>
  )
}

describe('VaultDetailPage route lifecycle', () => {
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
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/vaults/vault-a') return vault('vault-a', 'Vault A')
      if (path === '/vaults/vault-b') return vault('vault-b', 'Vault B')
      if (path.includes('/credentials')) return { data: [], has_more: false }
      return { data: [] }
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

  it('hides vault and credential write actions when the current project is archived', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/vaults/vault-a') return vault('vault-a', 'Vault A')
      if (path === '/vaults/vault-a/credentials?limit=100&include_archived=false') {
        return { data: [credential('cred-a', 'Credential A')], has_more: false }
      }
      return { data: [] }
    })
    useProjectStore.setState({
      currentOrgId: 'org-a',
      currentProjectId: 'project-archived',
      currentProject: {
        id: 'project-archived',
        org_id: 'org-a',
        name: 'Archived Project',
        slug: 'project-archived',
        is_default: false,
        archived_at: '2026-01-02T00:00:00Z',
      },
      organizations: [],
      projects: [],
    })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText, queryByText } = render(renderVaultPage(queryClient, 'vault-a'))

    await waitFor(() => {
      expect(getByText('Vault A')).toBeTruthy()
      expect(getByText('Credential A')).toBeTruthy()
    })

    expect(queryByText('common.archive')).toBeNull()
    expect(queryByText('common.delete')).toBeNull()
    expect(queryByText('managed.vaults.addCredential')).toBeNull()
    expect(queryByText('cred-a:managed.vaults.credArchiveTitle')).toBeNull()
  })

  it('refetches vault detail resources after the managed project changes', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText } = render(renderVaultPage(queryClient, 'vault-a'))

    await waitFor(() => {
      expect(getByText('Vault A')).toBeTruthy()
      expect(managedGetMock).toHaveBeenCalledWith('/vaults/vault-a', managedOptions())
      expect(managedGetMock).toHaveBeenCalledWith(
        '/vaults/vault-a/credentials?limit=100&include_archived=false',
        managedOptions(),
      )
    })
    expect(managedGetMock.mock.calls.filter(([path]) => path === '/vaults/vault-a')).toHaveLength(1)
    expect(
      managedGetMock.mock.calls.filter(
        ([path]) => path === '/vaults/vault-a/credentials?limit=100&include_archived=false',
      ),
    ).toHaveLength(1)

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(managedGetMock.mock.calls.filter(([path]) => path === '/vaults/vault-a')).toHaveLength(
        2,
      )
      expect(
        managedGetMock.mock.calls.filter(
          ([path]) => path === '/vaults/vault-a/credentials?limit=100&include_archived=false',
        ),
      ).toHaveLength(2)
    })
    expect(managedGetMock).toHaveBeenCalledWith('/vaults/vault-a', managedOptions('project-b'))
    expect(managedGetMock).toHaveBeenCalledWith(
      '/vaults/vault-a/credentials?limit=100&include_archived=false',
      managedOptions('project-b'),
    )
  })

  it('does not run an archive confirmation captured for a previous route vault', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText, queryAllByRole, rerender } = render(renderVaultPage(queryClient, 'vault-a'))

    await waitFor(() => {
      expect(getByText('Vault A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('common.archive'))
    })

    await act(async () => {
      rerender(renderVaultPage(queryClient, 'vault-b'))
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(getByText('Vault B')).toBeTruthy()
    })

    const archiveButtons = queryAllByRole('button', { name: 'common.archive' })
    if (archiveButtons.length > 1) {
      await act(async () => {
        fireEvent.click(archiveButtons[archiveButtons.length - 1])
      })
    }

    expect(managedPostMock).not.toHaveBeenCalled()
  })

  it('does not close a new archive confirmation when an older archive finishes', async () => {
    const archive = deferred<Record<string, never>>()
    managedPostMock.mockReturnValueOnce(archive.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getAllByRole, getByRole, getByText } = render(renderVaultPage(queryClient, 'vault-a'))

    await waitFor(() => {
      expect(getByText('Vault A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('common.archive'))
    })

    await act(async () => {
      const archiveButtons = getAllByRole('button', { name: 'common.archive' })
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

  it('does not archive the vault after the current vault detail is no longer active', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getAllByRole, getByText } = render(renderVaultPage(queryClient, 'vault-a'))

    await waitFor(() => {
      expect(getByText('Vault A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('common.archive'))
    })

    await act(async () => {
      queryClient.setQueryData(['vault', 'org-a:project-a', 'vault-a'], {
        ...vault('vault-a', 'Vault A'),
        archived_at: '2026-01-02T00:00:00Z',
      })
      const archiveButtons = getAllByRole('button', { name: 'common.archive' })
      fireEvent.click(archiveButtons[archiveButtons.length - 1])
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith(
      '/vaults/vault-a/archive',
      {},
      managedOptions(),
    )
  })

  it('does not delete the vault after the current vault detail is no longer active', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getAllByRole, getByText } = render(renderVaultPage(queryClient, 'vault-a'))

    await waitFor(() => {
      expect(getByText('Vault A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('common.delete'))
    })

    await act(async () => {
      queryClient.setQueryData(['vault', 'org-a:project-a', 'vault-a'], {
        ...vault('vault-a', 'Vault A'),
        archived_at: '2026-01-02T00:00:00Z',
      })
      const deleteButtons = getAllByRole('button', { name: 'common.delete' })
      fireEvent.click(deleteButtons[deleteButtons.length - 1])
      await Promise.resolve()
    })

    expect(managedDeleteMock).not.toHaveBeenCalledWith('/vaults/vault-a', managedOptions())
  })

  it('does not archive a credential after it leaves the current credential list before confirmation', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/vaults/vault-a') return vault('vault-a', 'Vault A')
      if (path === '/vaults/vault-a/credentials?limit=100&include_archived=false') {
        return { data: [credential('cred-a', 'Credential A')], has_more: false }
      }
      return { data: [] }
    })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getAllByRole, getByText } = render(renderVaultPage(queryClient, 'vault-a'))

    await waitFor(() => {
      expect(getByText('Credential A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('cred-a:managed.vaults.credArchiveTitle'))
    })

    await act(async () => {
      queryClient.setQueryData(['vault-credentials', 'org-a:project-a', 'vault-a', false], {
        data: [],
        has_more: false,
      })
      const archiveButtons = getAllByRole('button', { name: 'common.archive' })
      fireEvent.click(archiveButtons[archiveButtons.length - 1])
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith(
      '/vaults/vault-a/credentials/cred-a/archive',
      {},
      managedOptions(),
    )
  })

  it('does not archive a credential after the current vault detail is no longer active', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/vaults/vault-a') return vault('vault-a', 'Vault A')
      if (path === '/vaults/vault-a/credentials?limit=100&include_archived=false') {
        return { data: [credential('cred-a', 'Credential A')], has_more: false }
      }
      return { data: [] }
    })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getAllByRole, getByText } = render(renderVaultPage(queryClient, 'vault-a'))

    await waitFor(() => {
      expect(getByText('Credential A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('cred-a:managed.vaults.credArchiveTitle'))
    })

    await act(async () => {
      queryClient.setQueryData(['vault', 'org-a:project-a', 'vault-a'], {
        ...vault('vault-a', 'Vault A'),
        archived_at: '2026-01-02T00:00:00Z',
      })
      const archiveButtons = getAllByRole('button', { name: 'common.archive' })
      fireEvent.click(archiveButtons[archiveButtons.length - 1])
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith(
      '/vaults/vault-a/credentials/cred-a/archive',
      {},
      managedOptions(),
    )
  })

  it('does not create a credential after the current vault detail is no longer active', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByPlaceholderText, getByText } = render(renderVaultPage(queryClient, 'vault-a'))

    await waitFor(() => {
      expect(getByText('Vault A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('managed.vaults.addCredential'))
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('https://mcp.example.com'), {
        target: { value: 'https://mcp-a.example.com' },
      })
    })

    await act(async () => {
      queryClient.setQueryData(['vault', 'org-a:project-a', 'vault-a'], {
        ...vault('vault-a', 'Vault A'),
        archived_at: '2026-01-02T00:00:00Z',
      })
      fireEvent.click(getByText('managed.vaults.cred.connect'))
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith(
      '/vaults/vault-a/credentials',
      {
        credential_type: 'mcp_oauth',
        mcp_server_url: 'https://mcp-a.example.com',
        name: undefined,
        token_value: '',
      },
      managedOptions(),
    )
  })

  it('does not invalidate vaults from a delete completion after the page unmounts', async () => {
    const deleteVault = deferred<Record<string, never>>()
    managedDeleteMock.mockReturnValueOnce(deleteVault.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    const { getAllByRole, getByText, unmount } = render(renderVaultPage(queryClient, 'vault-a'))

    await waitFor(() => {
      expect(getByText('Vault A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('common.delete'))
    })

    await act(async () => {
      const deleteButtons = getAllByRole('button', { name: 'common.delete' })
      fireEvent.click(deleteButtons[deleteButtons.length - 1])
      await Promise.resolve()
    })

    unmount()

    await act(async () => {
      deleteVault.resolve({})
      await Promise.resolve()
    })

    expect(invalidateSpy).not.toHaveBeenCalledWith({ queryKey: ['vaults', 'org-a:project-a'] })
  })

  it('does not archive the vault from an old confirmation after the current project is archived', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getAllByRole, getByText } = render(renderVaultPage(queryClient, 'vault-a'))

    await waitFor(() => {
      expect(getByText('Vault A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('common.archive'))
    })

    const archiveButtons = getAllByRole('button', { name: 'common.archive' })
    const oldArchiveButton = archiveButtons[archiveButtons.length - 1]

    await act(async () => {
      useProjectStore.setState({
        currentProject: projectInfo('2026-01-02T00:00:00Z'),
      })
      fireEvent.click(oldArchiveButton)
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith(
      '/vaults/vault-a/archive',
      {},
      managedOptions(),
    )
  })

  it('does not delete the vault from an old confirmation after the current project is archived', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getAllByRole, getByText } = render(renderVaultPage(queryClient, 'vault-a'))

    await waitFor(() => {
      expect(getByText('Vault A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('common.delete'))
    })

    const deleteButtons = getAllByRole('button', { name: 'common.delete' })
    const oldDeleteButton = deleteButtons[deleteButtons.length - 1]

    await act(async () => {
      useProjectStore.setState({
        currentProject: projectInfo('2026-01-02T00:00:00Z'),
      })
      fireEvent.click(oldDeleteButton)
      await Promise.resolve()
    })

    expect(managedDeleteMock).not.toHaveBeenCalledWith('/vaults/vault-a', managedOptions())
  })

  it('does not archive a credential from an old confirmation after the current project is archived', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/vaults/vault-a') return vault('vault-a', 'Vault A')
      if (path === '/vaults/vault-a/credentials?limit=100&include_archived=false') {
        return { data: [credential('cred-a', 'Credential A')], has_more: false }
      }
      return { data: [] }
    })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getAllByRole, getByText } = render(renderVaultPage(queryClient, 'vault-a'))

    await waitFor(() => {
      expect(getByText('Credential A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('cred-a:managed.vaults.credArchiveTitle'))
    })

    const archiveButtons = getAllByRole('button', { name: 'common.archive' })
    const oldArchiveButton = archiveButtons[archiveButtons.length - 1]

    await act(async () => {
      useProjectStore.setState({
        currentProject: projectInfo('2026-01-02T00:00:00Z'),
      })
      fireEvent.click(oldArchiveButton)
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith(
      '/vaults/vault-a/credentials/cred-a/archive',
      {},
      managedOptions(),
    )
  })

  it('does not create a credential from an old dialog after the current project is archived', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByPlaceholderText, getByText } = render(renderVaultPage(queryClient, 'vault-a'))

    await waitFor(() => {
      expect(getByText('Vault A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('managed.vaults.addCredential'))
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('https://mcp.example.com'), {
        target: { value: 'https://archived-project.example.com' },
      })
    })

    await act(async () => {
      useProjectStore.setState({
        currentProject: projectInfo('2026-01-02T00:00:00Z'),
      })
      fireEvent.click(getByText('managed.vaults.cred.connect'))
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith(
      '/vaults/vault-a/credentials',
      {
        credential_type: 'mcp_oauth',
        mcp_server_url: 'https://archived-project.example.com',
        name: undefined,
        token_value: '',
      },
      managedOptions(),
    )
  })

  it('does not invalidate vaults from an archive completion after the current project is archived', async () => {
    const archiveVault = deferred<Record<string, never>>()
    managedPostMock.mockReturnValueOnce(archiveVault.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    const { getAllByRole, getByText } = render(renderVaultPage(queryClient, 'vault-a'))

    await waitFor(() => {
      expect(getByText('Vault A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('common.archive'))
    })

    await act(async () => {
      const archiveButtons = getAllByRole('button', { name: 'common.archive' })
      fireEvent.click(archiveButtons[archiveButtons.length - 1])
      await Promise.resolve()
    })

    await act(async () => {
      useProjectStore.setState({
        currentProject: projectInfo('2026-01-02T00:00:00Z'),
      })
      archiveVault.resolve({})
      await Promise.resolve()
    })

    expect(invalidateSpy).not.toHaveBeenCalledWith({
      queryKey: ['vault', 'org-a:project-a', 'vault-a'],
    })
    expect(invalidateSpy).not.toHaveBeenCalledWith({ queryKey: ['vaults', 'org-a:project-a'] })
  })
})
