import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/i18n', async () => {
  const { default: en } = await import('@/lib/i18n/locales/en')
  return {
    i18n: { language: 'en' },
    useTranslation: () => ({
      t: (key: string, _params?: unknown) =>
        key === 'managed.vaults.sharedWarning'
          ? en.translation.managed.vaults.sharedWarning
          : key,
    }),
  }
})

vi.mock('@/lib/api-client', () => ({
  extractErrorFromResponse: vi.fn(async () => new Error('mock api error')),
  managedPost: vi.fn(),
}))

vi.mock('@/lib/managed/errors', () => ({
  toastOperationError: vi.fn(),
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

import { managedPost } from '@/lib/api-client'
import { useProjectStore } from '@/stores/managed/project-store'

import { CreateVaultDialog } from './create-vault-dialog'

const managedPostMock = managedPost as unknown as ReturnType<typeof vi.fn>

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

describe('CreateVaultDialog managed scope lifecycle', () => {
  beforeEach(() => {
    managedPostMock.mockReset()
    managedPostMock.mockResolvedValue({ id: 'credgrp_018f6f42-0a51-7cc4-98c8-4f6f0ca5f012' })
    useProjectStore.setState({
      currentOrgId: 'org-a',
      currentProjectId: 'project-a',
      currentProject: {
        id: 'project-a',
        org_id: 'org-a',
        name: 'Project A',
        slug: 'project-a',
        is_default: true,
        capability: 'write',
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

  it('renders the current-project permission warning', () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const view = render(
      <QueryClientProvider client={queryClient}>
        <CreateVaultDialog open onOpenChange={() => {}} />
      </QueryClientProvider>,
    )

    expect(view.container.textContent).toContain(
      'MCP credential vaults are shared within the current project. Access and management require appropriate project permissions.',
    )
  })

  it('does not create a vault from old dialog state in the same turn as a project switch', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByPlaceholderText, getByText } = render(
      <QueryClientProvider client={queryClient}>
        <CreateVaultDialog open onOpenChange={() => {}} />
      </QueryClientProvider>,
    )

    await act(async () => {
      fireEvent.input(getByPlaceholderText('managed.vaults.namePlaceholder'), {
        target: { value: 'Project A Vault' },
      })
    })

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      fireEvent.click(getByText('common.create'))
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith(
      '/credential-groups',
      expect.anything(),
      managedOptions(),
    )
  })

  it('does not invalidate from a create completion after the managed project changes', async () => {
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

    const { getByPlaceholderText, getByText } = render(
      <QueryClientProvider client={queryClient}>
        <CreateVaultDialog open onOpenChange={onOpenChange} />
      </QueryClientProvider>,
    )

    await act(async () => {
      fireEvent.input(getByPlaceholderText('managed.vaults.namePlaceholder'), {
        target: { value: 'Project A Vault' },
      })
    })

    await act(async () => {
      fireEvent.click(getByText('common.create'))
      await Promise.resolve()
    })

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      create.resolve({ id: 'vault-created-in-project-a' })
      await Promise.resolve()
    })

    expect(invalidateSpy).not.toHaveBeenCalledWith({
      queryKey: ['credential-groups', 'org-a:project-a'],
    })
  })

  it('does not invalidate from a create completion after the dialog unmounts', async () => {
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

    const view = render(
      <QueryClientProvider client={queryClient}>
        <CreateVaultDialog open onOpenChange={onOpenChange} />
      </QueryClientProvider>,
    )

    await act(async () => {
      fireEvent.input(view.getByPlaceholderText('managed.vaults.namePlaceholder'), {
        target: { value: 'Unmounted Vault' },
      })
    })

    await act(async () => {
      fireEvent.click(view.getByText('common.create'))
      await Promise.resolve()
    })

    view.unmount()

    await act(async () => {
      create.resolve({ id: 'vault-created-after-unmount' })
      await Promise.resolve()
    })

    expect(invalidateSpy).not.toHaveBeenCalledWith({
      queryKey: ['credential-groups', 'org-a:project-a'],
    })
    expect(onOpenChange).not.toHaveBeenCalled()
  })
})
