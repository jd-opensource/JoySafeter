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
    onChange,
    value,
  }: {
    onChange: (value: string) => void
    value: string
  }) => <input value={value} onChange={(event) => onChange(event.target.value)} />,
  SecretModelInput: ({
    onChange,
    value,
  }: {
    onChange: (value: string) => void
    value: string
  }) => <input value={value} onChange={(event) => onChange(event.target.value)} />,
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
      expect(managedGetMock).toHaveBeenCalledWith('/secrets/secret-a')
    })
    expect(managedGetMock.mock.calls.filter(([path]) => path === '/secrets/secret-a')).toHaveLength(1)

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(managedGetMock.mock.calls.filter(([path]) => path === '/secrets/secret-a')).toHaveLength(2)
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

    expect(managedPutMock).not.toHaveBeenCalledWith('/secrets/secret-a', expect.anything())
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

    view.unmount()

    await act(async () => {
      save.resolve({})
      await save.promise
      await Promise.resolve()
    })

    expect(invalidateSpy).not.toHaveBeenCalled()
  })
})
