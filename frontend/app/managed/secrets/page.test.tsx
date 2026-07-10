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

vi.mock('@/lib/managed/filters', () => ({
  createCreatedTimeFilter: () => ({ id: 'created', label: 'created', options: [] }),
  filterByCreatedTime: () => true,
  matchesSearch: () => true,
}))

vi.mock('@/components/managed/shared', () => ({
  ConfirmDialog: ({
    confirmLabel,
    description,
    onCancel,
    onConfirm,
    open,
    title,
  }: {
    confirmLabel?: string
    description?: ReactNode
    onCancel: () => void
    onConfirm: () => void
    open: boolean
    title: string
  }) =>
    open ? (
      <div>
        <h2>{title}</h2>
        {description}
        <button onClick={onCancel}>common.cancel</button>
        <button onClick={onConfirm}>{confirmLabel || 'common.confirm'}</button>
      </div>
    ) : null,
  DataTable: ({
    actionMenu,
    data,
  }: {
    actionMenu?: (row: SecretRecord) => { label: string; onClick: () => void }[]
    data: SecretRecord[]
  }) => (
    <div>
      {data.map((secret) => (
        <div key={secret.id}>
          <span>{secret.name}</span>
          {actionMenu?.(secret).map((item) => (
            <button key={item.label} onClick={item.onClick}>
              {secret.id}:{item.label}
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
  SecretKeySelect: () => null,
  SecretModelInput: () => null,
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
  SelectGroup: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectItem: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectLabel: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectTrigger: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectValue: () => null,
}))

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement
globalThis.localStorage = dom.window.localStorage

import { managedDelete, managedGet, managedPost } from '@/lib/api-client'
import { useProjectStore } from '@/stores/managed/project-store'

import SecretListPage from './page'

interface SecretRecord {
  id: string
  name: string
  provider: string
  protocol?: string
  is_default?: boolean
  created_at: string
}

const managedDeleteMock = managedDelete as unknown as ReturnType<typeof vi.fn>
const managedGetMock = managedGet as unknown as ReturnType<typeof vi.fn>
const managedPostMock = managedPost as unknown as ReturnType<typeof vi.fn>

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

function secret(id: string, name: string): SecretRecord {
  return {
    id,
    name,
    provider: 'claude',
    protocol: 'anthropic_messages',
    is_default: false,
    created_at: '2026-01-01T00:00:00Z',
  }
}

describe('SecretListPage delete lifecycle', () => {
  beforeEach(() => {
    managedDeleteMock.mockReset()
    managedGetMock.mockReset()
    managedPostMock.mockReset()
    managedDeleteMock.mockResolvedValue({})
    managedGetMock.mockResolvedValue({ data: [secret('secret-a', 'Secret A')], has_more: false })
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

  it('does not delete a secret target that is no longer in the current secrets list', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText, queryAllByRole } = render(
      <QueryClientProvider client={queryClient}>
        <SecretListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Secret A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('secret-a:common.delete'))
    })

    await act(async () => {
      queryClient.setQueryData(['secrets', 'org-a:project-a', '/secrets', undefined, false, 10], {
        data: [secret('secret-b', 'Secret B')],
        has_more: false,
      })
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(getByText('Secret B')).toBeTruthy()
    })

    const deleteButtons = queryAllByRole('button', { name: 'common.delete' })
    if (deleteButtons.length > 0) {
      await act(async () => {
        fireEvent.click(deleteButtons[deleteButtons.length - 1])
      })
    }

    expect(managedDeleteMock).not.toHaveBeenCalled()
  })

  it('does not delete a secret target that leaves the current secrets list during confirmation', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByRole, getByText } = render(
      <QueryClientProvider client={queryClient}>
        <SecretListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Secret A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('secret-a:common.delete'))
    })

    await act(async () => {
      queryClient.setQueryData(['secrets', 'org-a:project-a', '/secrets', undefined, false, 10], {
        data: [secret('secret-b', 'Secret B')],
        has_more: false,
      })
      fireEvent.click(getByRole('button', { name: 'common.delete' }))
      await Promise.resolve()
    })

    expect(managedDeleteMock).not.toHaveBeenCalledWith('/secrets/secret-a')
  })

  it('does not set default on a secret target that leaves the current secrets list', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText } = render(
      <QueryClientProvider client={queryClient}>
        <SecretListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Secret A')).toBeTruthy()
    })

    await act(async () => {
      queryClient.setQueryData(['secrets', 'org-a:project-a', '/secrets', undefined, false, 10], {
        data: [secret('secret-b', 'Secret B')],
        has_more: false,
      })
      fireEvent.click(getByText('secret-a:managed.secrets.setDefault'))
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith('/secrets/secret-a/default', {})
  })

  it('does not test a secret draft from old dialog state in the same turn as a project switch', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getAllByRole } = render(
      <QueryClientProvider client={queryClient}>
        <SecretListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getAllByRole('button', { name: /managed\.secrets\.new/ })[0]).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getAllByRole('button', { name: /managed\.secrets\.new/ })[0])
    })

    const testButton = getAllByRole('button', { name: /managed\.secrets\.testConnection/ })[0]

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      fireEvent.click(testButton)
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith('/secrets/test', expect.anything())
  })

  it('does not create a secret from old dialog state in the same turn as a project switch', async () => {
    managedPostMock.mockResolvedValueOnce({
      ok: true,
      provider: 'claude',
      protocol: 'anthropic_messages',
      message: 'ok',
    })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getAllByRole, getByPlaceholderText, getByText } = render(
      <QueryClientProvider client={queryClient}>
        <SecretListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getAllByRole('button', { name: /managed\.secrets\.new/ })[0]).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getAllByRole('button', { name: /managed\.secrets\.new/ })[0])
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('managed.secrets.namePlaceholder'), {
        target: { value: 'Old Project Secret' },
      })
    })

    await act(async () => {
      fireEvent.click(getAllByRole('button', { name: /managed\.secrets\.testConnection/ })[0])
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(getByText('managed.secrets.testSucceeded')).toBeTruthy()
    })

    const createButton = getAllByRole('button', { name: /common\.create/ })[0]

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      fireEvent.click(createButton)
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith('/secrets', expect.anything())
  })

  it('does not delete a secret from an old confirmation in the same turn as a project switch', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByRole, getByText } = render(
      <QueryClientProvider client={queryClient}>
        <SecretListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Secret A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('secret-a:common.delete'))
    })

    const confirmDeleteButton = getByRole('button', { name: 'common.delete' })

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      fireEvent.click(confirmDeleteButton)
      await Promise.resolve()
    })

    expect(managedDeleteMock).not.toHaveBeenCalledWith('/secrets/secret-a')
  })

  it('does not set default from an old row action in the same turn as a project switch', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText } = render(
      <QueryClientProvider client={queryClient}>
        <SecretListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Secret A')).toBeTruthy()
    })

    const setDefaultButton = getByText('secret-a:managed.secrets.setDefault')

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      fireEvent.click(setDefaultButton)
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith('/secrets/secret-a/default', {})
  })

  it('does not apply a test-connection result after the managed project changes', async () => {
    const pendingTest = deferred<{
      ok: boolean
      provider: string
      protocol: string
      message: string
    }>()
    managedPostMock.mockReturnValueOnce(pendingTest.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getAllByRole, queryByText, rerender } = render(
      <QueryClientProvider client={queryClient}>
        <SecretListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getAllByRole('button', { name: /managed\.secrets\.new/ })[0]).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getAllByRole('button', { name: /managed\.secrets\.new/ })[0])
    })

    await act(async () => {
      fireEvent.click(getAllByRole('button', { name: /managed\.secrets\.testConnection/ })[0])
      await Promise.resolve()
    })

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      rerender(
        <QueryClientProvider client={queryClient}>
          <SecretListPage />
        </QueryClientProvider>,
      )
    })

    await act(async () => {
      pendingTest.resolve({
        ok: true,
        provider: 'claude',
        protocol: 'anthropic_messages',
        message: 'ok',
      })
      await pendingTest.promise
    })

    expect(queryByText('managed.secrets.testSucceeded')).toBeNull()
  })

  it('does not close a reopened create secret dialog when an older create finishes', async () => {
    const create = deferred<Record<string, never>>()
    managedPostMock
      .mockResolvedValueOnce({
        ok: true,
        provider: 'claude',
        protocol: 'anthropic_messages',
        message: 'ok',
      })
      .mockReturnValueOnce(create.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getAllByRole, getByPlaceholderText, getByText } = render(
      <QueryClientProvider client={queryClient}>
        <SecretListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getAllByRole('button', { name: /managed\.secrets\.new/ })[0]).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getAllByRole('button', { name: /managed\.secrets\.new/ })[0])
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('managed.secrets.namePlaceholder'), {
        target: { value: 'Old Secret' },
      })
    })

    await act(async () => {
      fireEvent.click(getAllByRole('button', { name: /managed\.secrets\.testConnection/ })[0])
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(getByText('managed.secrets.testSucceeded')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getAllByRole('button', { name: /common\.create/ })[0])
      await Promise.resolve()
    })

    await act(async () => {
      fireEvent.click(getByText('dialog-close'))
    })

    await act(async () => {
      fireEvent.click(getAllByRole('button', { name: /managed\.secrets\.new/ })[0])
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('managed.secrets.namePlaceholder'), {
        target: { value: 'New Secret' },
      })
    })

    await act(async () => {
      create.resolve({})
      await Promise.resolve()
    })

    expect((getByPlaceholderText('managed.secrets.namePlaceholder') as HTMLInputElement).value).toBe(
      'New Secret',
    )
  })

  it('does not close a new delete confirmation when an older delete finishes', async () => {
    const pendingDelete = deferred<Record<string, never>>()
    managedGetMock.mockResolvedValue({
      data: [secret('secret-a', 'Secret A'), secret('secret-b', 'Secret B')],
      has_more: false,
    })
    managedDeleteMock.mockReturnValueOnce(pendingDelete.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByRole, getByText } = render(
      <QueryClientProvider client={queryClient}>
        <SecretListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Secret A')).toBeTruthy()
      expect(getByText('Secret B')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('secret-a:common.delete'))
    })

    await act(async () => {
      fireEvent.click(getByRole('button', { name: 'common.delete' }))
      await Promise.resolve()
    })

    await act(async () => {
      fireEvent.click(getByRole('button', { name: 'common.cancel' }))
    })

    await act(async () => {
      fireEvent.click(getByText('secret-b:common.delete'))
    })

    await act(async () => {
      pendingDelete.resolve({})
      await Promise.resolve()
    })

    expect(getByRole('button', { name: 'common.cancel' })).toBeTruthy()
  })

  it('does not invalidate secrets from a create completion after the page unmounts', async () => {
    const create = deferred<Record<string, never>>()
    managedPostMock
      .mockResolvedValueOnce({
        ok: true,
        provider: 'claude',
        protocol: 'anthropic_messages',
        message: 'ok',
      })
      .mockReturnValueOnce(create.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    const { getAllByRole, getByPlaceholderText, getByText, unmount } = render(
      <QueryClientProvider client={queryClient}>
        <SecretListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getAllByRole('button', { name: /managed\.secrets\.new/ })[0]).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getAllByRole('button', { name: /managed\.secrets\.new/ })[0])
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('managed.secrets.namePlaceholder'), {
        target: { value: 'Unmounted Secret' },
      })
    })

    await act(async () => {
      fireEvent.click(getAllByRole('button', { name: /managed\.secrets\.testConnection/ })[0])
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(getByText('managed.secrets.testSucceeded')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getAllByRole('button', { name: /common\.create/ })[0])
      await Promise.resolve()
    })

    unmount()

    await act(async () => {
      create.resolve({})
      await Promise.resolve()
    })

    expect(invalidateSpy).not.toHaveBeenCalledWith({ queryKey: ['secrets'] })
  })

  it('does not invalidate secrets from a delete completion after the page unmounts', async () => {
    const pendingDelete = deferred<Record<string, never>>()
    managedDeleteMock.mockReturnValueOnce(pendingDelete.promise)
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
        <SecretListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Secret A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('secret-a:common.delete'))
    })

    await act(async () => {
      fireEvent.click(getByRole('button', { name: 'common.delete' }))
      await Promise.resolve()
    })

    unmount()

    await act(async () => {
      pendingDelete.resolve({})
      await Promise.resolve()
    })

    expect(invalidateSpy).not.toHaveBeenCalledWith({ queryKey: ['secrets'] })
  })

  it('does not invalidate secrets from a set-default completion after the page unmounts', async () => {
    const setDefault = deferred<Record<string, never>>()
    managedPostMock.mockReturnValueOnce(setDefault.promise)
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
        <SecretListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Secret A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('secret-a:managed.secrets.setDefault'))
      await Promise.resolve()
    })

    unmount()

    await act(async () => {
      setDefault.resolve({})
      await Promise.resolve()
    })

    expect(invalidateSpy).not.toHaveBeenCalledWith({ queryKey: ['secrets'] })
  })
})
