import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/i18n', () => ({
  i18n: { language: 'en' },
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock('@/lib/api-client', () => ({
  extractErrorFromResponse: vi.fn(async () => new Error('mock api error')),
  managedPost: vi.fn(),
}))

vi.mock('@/lib/managed/errors', () => ({
  toastOperationError: vi.fn(),
}))

vi.mock('@/lib/utils/url-validation', () => ({
  validateUrlScheme: () => null,
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

vi.mock('@/components/ui/dialog', () => ({
  Dialog: ({ children, open }: { children: ReactNode; open: boolean }) =>
    open ? <div>{children}</div> : null,
  DialogContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogDescription: ({ children }: { children: ReactNode }) => <p>{children}</p>,
  DialogHeader: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children: ReactNode }) => <h1>{children}</h1>,
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
globalThis.HTMLFormElement = dom.window.HTMLFormElement
globalThis.localStorage = dom.window.localStorage
globalThis.alert = vi.fn()

import { managedPost } from '@/lib/api-client'
import { useProjectStore } from '@/stores/managed/project-store'

import { CreateCredentialDialog } from './create-credential-dialog'

const managedPostMock = managedPost as unknown as ReturnType<typeof vi.fn>

function managedOptions() {
  return {
    headers: {
      'X-Org-Id': 'org-a',
      'X-Project-Id': 'project-a',
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

function renderDialog(
  vaultId: string,
  queryClient: QueryClient,
  onOpenChange: (open: boolean) => void = () => {},
) {
  return (
    <QueryClientProvider client={queryClient}>
      <CreateCredentialDialog
        open
        onOpenChange={onOpenChange}
        vaultId={vaultId}
        queryKey={['vault-credentials', vaultId]}
      />
    </QueryClientProvider>
  )
}

describe('CreateCredentialDialog object lifecycle', () => {
  beforeEach(() => {
    managedPostMock.mockReset()
    managedPostMock.mockResolvedValue({ id: 'cred-created' })
    useProjectStore.setState({
      currentOrgId: 'org-a',
      currentProjectId: 'project-a',
      currentProject: {
        id: 'project-a',
        org_id: 'org-a',
        name: 'Project A',
        slug: 'project-a',
        is_default: true,
        archived_at: null,
      },
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

  it('does not submit credential draft data to a different vault after vault id changes', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByPlaceholderText, getByText, rerender } = render(
      renderDialog('vault-a', queryClient),
    )

    await act(async () => {
      fireEvent.input(getByPlaceholderText('managed.vaults.cred.namePlaceholder'), {
        target: { value: 'Vault A Credential' },
      })
      fireEvent.input(getByPlaceholderText('https://mcp.example.com'), {
        target: { value: 'https://mcp-a.example.com' },
      })
    })

    await act(async () => {
      rerender(renderDialog('vault-b', queryClient))
    })

    await act(async () => {
      fireEvent.click(getByText('managed.vaults.cred.connect'))
    })

    expect(managedPostMock).not.toHaveBeenCalled()
  })

  it('does not invalidate credentials from a create completion after vault id changes', async () => {
    const create = deferred<{ id: string }>()
    managedPostMock.mockReturnValueOnce(create.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    const { getByPlaceholderText, getByText, rerender } = render(
      renderDialog('vault-a', queryClient),
    )

    await act(async () => {
      fireEvent.input(getByPlaceholderText('https://mcp.example.com'), {
        target: { value: 'https://mcp-a.example.com' },
      })
    })

    await act(async () => {
      fireEvent.click(getByText('managed.vaults.cred.connect'))
      await Promise.resolve()
    })

    expect(managedPostMock).toHaveBeenCalledWith(
      '/vaults/vault-a/credentials',
      expect.objectContaining({
        credential_type: 'mcp_oauth',
        mcp_server_url: 'https://mcp-a.example.com',
      }),
      managedOptions(),
    )

    await act(async () => {
      rerender(renderDialog('vault-b', queryClient))
      create.resolve({ id: 'cred-created-in-vault-a' })
      await Promise.resolve()
    })

    expect(invalidateSpy).not.toHaveBeenCalled()
  })

  it('does not invalidate credentials from a create completion after the dialog unmounts', async () => {
    const create = deferred<{ id: string }>()
    managedPostMock.mockReturnValueOnce(create.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')
    const onOpenChange = vi.fn()

    const view = render(renderDialog('vault-a', queryClient, onOpenChange))

    await act(async () => {
      fireEvent.input(view.getByPlaceholderText('https://mcp.example.com'), {
        target: { value: 'https://mcp-a.example.com' },
      })
    })

    await act(async () => {
      fireEvent.click(view.getByText('managed.vaults.cred.connect'))
      await Promise.resolve()
    })

    view.unmount()

    await act(async () => {
      create.resolve({ id: 'cred-created-after-unmount' })
      await Promise.resolve()
    })

    expect(invalidateSpy).not.toHaveBeenCalled()
    expect(onOpenChange).not.toHaveBeenCalled()
  })
})
