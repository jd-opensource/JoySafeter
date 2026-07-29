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
  managedPut: vi.fn(),
}))

vi.mock('@/lib/managed/errors', () => ({
  shouldRetryManagedResourceError: vi.fn(() => false),
  toastOperationError: vi.fn(),
}))

vi.mock('@/components/managed/shared', () => ({
  MonoId: ({ id }: { id: string }) => <span>{id}</span>,
  PageHeader: ({ action, title }: { action?: ReactNode; title: string }) => (
    <div>
      <h1>{title}</h1>
      {action}
    </div>
  ),
  RelativeTime: ({ date }: { date: string }) => <span>{date}</span>,
  ResourceErrorState: () => null,
  SecretKeySelect: ({
    disabled,
    onChange,
    value,
  }: {
    disabled?: boolean
    onChange: (value: string) => void
    value: string
  }) => (
    <input value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)} />
  ),
  SecretModelInput: ({
    disabled,
    onChange,
    value,
  }: {
    disabled?: boolean
    onChange: (value: string) => void
    value: string
  }) => (
    <input value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)} />
  ),
}))

vi.mock('@/components/ui/button', () => ({
  buttonVariants: () => '',
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

import { managedGet, managedPut } from '@/lib/api-client'
import { useProjectStore } from '@/stores/managed/project-store'

import SecretDetailPage from './page'

const managedGetMock = managedGet as unknown as ReturnType<typeof vi.fn>
const managedPutMock = managedPut as unknown as ReturnType<typeof vi.fn>

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

function secret(id: string, name: string, secretData: Record<string, string> = {}) {
  return {
    id,
    name,
    provider: 'custom',
    protocol: 'custom',
    secret_data: secretData,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-02T00:00:00Z',
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

function managedOptions(projectId = 'project-a') {
  return {
    headers: {
      'X-Org-Id': 'org-a',
      'X-Project-Id': projectId,
    },
    skipManagedContext: true,
  }
}

function renderSecretPage(queryClient: QueryClient, secretId: string) {
  const params = {
    status: 'fulfilled',
    value: { secretId },
    then: () => undefined,
  } as unknown as Promise<{ secretId: string }>

  return (
    <QueryClientProvider client={queryClient}>
      <SecretDetailPage params={params} />
    </QueryClientProvider>
  )
}

describe('SecretDetailPage managed scope lifecycle', () => {
  beforeEach(() => {
    managedGetMock.mockReset()
    managedPutMock.mockReset()
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/secrets/secret-a') return secret('secret-a', 'Secret A')
      return { data: [] }
    })
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

  it('refetches the secret after the managed project changes', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText } = render(renderSecretPage(queryClient, 'secret-a'))

    await waitFor(() => {
      expect(getByText('Secret A')).toBeTruthy()
      expect(managedGetMock).toHaveBeenCalledWith('/secrets/secret-a', managedOptions())
    })
    expect(managedGetMock.mock.calls.filter(([path]) => path === '/secrets/secret-a')).toHaveLength(
      1,
    )

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(
        managedGetMock.mock.calls.filter(([path]) => path === '/secrets/secret-a'),
      ).toHaveLength(2)
      expect(managedGetMock).toHaveBeenCalledWith('/secrets/secret-a', managedOptions('project-b'))
    })
  })

  it('does not overwrite an unsaved secret draft when refreshed secret data arrives', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/secrets/secret-a') {
        return secret('secret-a', 'Secret A', { API_KEY: 'server-original' })
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

    const view = render(renderSecretPage(queryClient, 'secret-a'))

    await waitFor(() => {
      expect(view.getByDisplayValue('server-original')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.input(view.getByDisplayValue('server-original'), {
        target: { value: 'local-draft' },
      })
    })

    await act(async () => {
      queryClient.setQueryData(
        ['secret', 'org-a:project-a', 'secret-a'],
        secret('secret-a', 'Secret A', { API_KEY: 'server-refresh' }),
      )
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(queryClient.getQueryData(['secret', 'org-a:project-a', 'secret-a'])).toMatchObject({
        secret_data: { API_KEY: 'server-refresh' },
      })
    })

    expect(view.getByDisplayValue('local-draft')).toBeTruthy()
    expect(view.queryByDisplayValue('server-refresh')).toBeNull()
  })

  it('does not save an old secret draft to a new project that has the same secret id', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/secrets/secret-a') {
        return secret('secret-a', 'Secret A', { API_KEY: 'old-project-key' })
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

    const view = render(renderSecretPage(queryClient, 'secret-a'))

    await waitFor(() => {
      expect(view.getByDisplayValue('old-project-key')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.input(view.getByDisplayValue('old-project-key'), {
        target: { value: 'old-project-local-draft' },
      })
    })

    queryClient.setQueryData(
      ['secret', 'org-a:project-b', 'secret-a'],
      secret('secret-a', 'Project B Secret', { API_KEY: 'project-b-key' }),
    )
    const saveButton = view.getByText('common.save')

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      fireEvent.click(saveButton)
      await Promise.resolve()
    })

    expect(managedPutMock).not.toHaveBeenCalled()
  })

  it('does not save after the current secret detail no longer matches the route secret', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const view = render(renderSecretPage(queryClient, 'secret-a'))

    await waitFor(() => {
      expect(view.getByText('Secret A')).toBeTruthy()
    })

    await act(async () => {
      view.getByText('managed.secrets.addPair').click()
    })

    await act(async () => {
      queryClient.setQueryData(
        ['secret', 'org-a:project-a', 'secret-a'],
        secret('secret-b', 'Secret B'),
      )
      view.getByText('common.save').click()
      await Promise.resolve()
    })

    expect(managedPutMock).not.toHaveBeenCalled()
  })

  it('does not invalidate from a save completion after the page unmounts', async () => {
    const save = deferred<unknown>()
    managedPutMock.mockReturnValueOnce(save.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    const view = render(renderSecretPage(queryClient, 'secret-a'))

    await waitFor(() => {
      expect(view.getByText('Secret A')).toBeTruthy()
    })

    await act(async () => {
      view.getByText('managed.secrets.addPair').click()
    })

    await act(async () => {
      view.getByText('common.save').click()
      await Promise.resolve()
    })

    expect(managedPutMock).toHaveBeenCalledTimes(1)
    expect(managedPutMock).toHaveBeenCalledWith(
      '/secrets/secret-a',
      expect.anything(),
      managedOptions(),
    )

    view.unmount()

    await act(async () => {
      save.resolve({})
      await save.promise
      await Promise.resolve()
    })

    expect(invalidateSpy).not.toHaveBeenCalled()
  })

  it('renders secret detail as read-only when the current project is archived', async () => {
    useProjectStore.setState({
      currentProject: projectInfo('2026-01-02T00:00:00Z'),
    })
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/secrets/secret-a') {
        return secret('secret-a', 'Secret A', { API_KEY: 'server-original' })
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

    const view = render(renderSecretPage(queryClient, 'secret-a'))

    await waitFor(() => {
      expect(view.getByDisplayValue('server-original')).toBeTruthy()
    })

    expect(view.queryByText('managed.secrets.addPair')).toBeNull()
    expect((view.getByText('common.save') as HTMLButtonElement).disabled).toBe(true)
    expect((view.getByDisplayValue('API_KEY') as HTMLInputElement).disabled).toBe(true)
    expect((view.getByDisplayValue('server-original') as HTMLInputElement).disabled).toBe(true)
  })

  it('does not save an old secret draft after the current project is archived', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/secrets/secret-a') {
        return secret('secret-a', 'Secret A', { API_KEY: 'server-original' })
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

    const view = render(renderSecretPage(queryClient, 'secret-a'))

    await waitFor(() => {
      expect(view.getByDisplayValue('server-original')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.input(view.getByDisplayValue('server-original'), {
        target: { value: 'local-draft-before-project-archive' },
      })
    })

    const saveButton = view.getByText('common.save')

    await act(async () => {
      useProjectStore.setState({
        currentProject: projectInfo('2026-01-02T00:00:00Z'),
      })
      fireEvent.click(saveButton)
      await Promise.resolve()
    })

    expect(managedPutMock).not.toHaveBeenCalled()
  })
})
