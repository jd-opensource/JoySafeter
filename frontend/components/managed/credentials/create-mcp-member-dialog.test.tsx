import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react'
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
import { parseCredentialGroupId, type CredentialGroupId } from '@/types/entity-id'

import { CreateMcpMemberDialog } from './create-mcp-member-dialog'

const managedPostMock = managedPost as unknown as ReturnType<typeof vi.fn>
const vaultAId = parseCredentialGroupId('credgrp_00000000-0000-0000-0000-000000000001')
const vaultBId = parseCredentialGroupId('credgrp_00000000-0000-0000-0000-000000000002')

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
  credentialGroupId: CredentialGroupId,
  queryClient: QueryClient,
  onOpenChange: (open: boolean) => void = () => {},
) {
  return (
    <QueryClientProvider client={queryClient}>
      <CreateMcpMemberDialog
        key={credentialGroupId}
        open
        onOpenChange={onOpenChange}
        credentialGroupId={credentialGroupId}
        queryKey={['credential-group-members', credentialGroupId]}
      />
    </QueryClientProvider>
  )
}

describe('CreateMcpMemberDialog object lifecycle', () => {
  beforeEach(() => {
    managedPostMock.mockReset()
    managedPostMock.mockResolvedValue({
      id: 'cred_00000000-0000-0000-0000-000000000003',
      group_id: 'credgrp_00000000-0000-0000-0000-000000000001',
      kind: 'mcp',
      name: 'https://mcp-a.example.com',
      mcp_server_url: 'https://mcp-a.example.com',
      provider: null,
      protocol: null,
      model: null,
      compatible_engine_ids: [],
      is_default: false,
      auth_scheme: 'static_bearer',
      data: { token_value: '********' },
      archived_at: null,
      created_at: '2026-08-10T00:00:00Z',
      updated_at: '2026-08-10T00:00:00Z',
    })
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

  it('closes and clears credential data when the current project becomes archived', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const onOpenChange = vi.fn()
    const view = render(renderDialog(vaultAId, queryClient, onOpenChange))

    fireEvent.input(view.getByPlaceholderText('https://mcp.example.com'), {
      target: { value: 'https://mcp-a.example.com' },
    })
    fireEvent.input(
      view.getByPlaceholderText('managed.credentials.groups.members.tokenPlaceholder'),
      {
        target: { value: 'bearer-token' },
      },
    )

    act(() => {
      useProjectStore.setState((state) => ({
        currentProject: state.currentProject
          ? { ...state.currentProject, archived_at: '2026-08-14T00:00:00Z' }
          : null,
      }))
    })

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false))
    expect(view.getByPlaceholderText('https://mcp.example.com')).toHaveValue('')
    expect(
      view.getByPlaceholderText('managed.credentials.groups.members.tokenPlaceholder'),
    ).toHaveValue('')
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
      renderDialog(vaultAId, queryClient),
    )

    await act(async () => {
      fireEvent.input(getByPlaceholderText('managed.credentials.groups.members.namePlaceholder'), {
        target: { value: 'Vault A Credential' },
      })
      fireEvent.input(getByPlaceholderText('https://mcp.example.com'), {
        target: { value: 'https://mcp-a.example.com' },
      })
      fireEvent.input(getByPlaceholderText('managed.credentials.groups.members.tokenPlaceholder'), {
        target: { value: 'bearer-token' },
      })
    })

    await act(async () => {
      rerender(renderDialog(vaultBId, queryClient))
    })

    await act(async () => {
      fireEvent.click(getByText('managed.credentials.groups.members.add'))
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
      renderDialog(vaultAId, queryClient),
    )

    await act(async () => {
      fireEvent.input(getByPlaceholderText('https://mcp.example.com'), {
        target: { value: 'https://mcp-a.example.com' },
      })
      fireEvent.input(getByPlaceholderText('managed.credentials.groups.members.tokenPlaceholder'), {
        target: { value: 'bearer-token' },
      })
    })
    await act(async () => {
      fireEvent.click(getByText('managed.credentials.groups.members.add'))
      await Promise.resolve()
    })

    await waitFor(() =>
      expect(managedPostMock).toHaveBeenCalledWith(
        `/credential-groups/${vaultAId}/members`,
        expect.objectContaining({
          mcp_server_url: 'https://mcp-a.example.com',
          data: { token_value: 'bearer-token' },
        }),
        managedOptions(),
      ),
    )

    await act(async () => {
      rerender(renderDialog(vaultBId, queryClient))
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

    const view = render(renderDialog(vaultAId, queryClient, onOpenChange))

    await act(async () => {
      fireEvent.input(view.getByPlaceholderText('https://mcp.example.com'), {
        target: { value: 'https://mcp-a.example.com' },
      })
      fireEvent.input(
        view.getByPlaceholderText('managed.credentials.groups.members.tokenPlaceholder'),
        {
          target: { value: 'bearer-token' },
        },
      )
    })

    await act(async () => {
      fireEvent.click(view.getByText('managed.credentials.groups.members.add'))
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

  it('defaults a blank optional name to the server url and accepts the member response', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')
    const onOpenChange = vi.fn()
    let wirePayload: Record<string, unknown> | undefined
    managedPostMock.mockImplementationOnce(async (_path, payload) => {
      wirePayload = JSON.parse(JSON.stringify(payload)) as Record<string, unknown>
      return {
        id: 'cred_00000000-0000-0000-0000-000000000003',
        group_id: vaultAId,
        kind: 'mcp',
        name: 'https://mcp-a.example.com',
        mcp_server_url: 'https://mcp-a.example.com',
        provider: null,
        protocol: null,
        model: null,
        compatible_engine_ids: [],
        is_default: false,
        auth_scheme: 'static_bearer',
        data: { token_value: '********' },
        archived_at: null,
        created_at: '2026-08-10T00:00:00Z',
        updated_at: '2026-08-10T00:00:00Z',
      }
    })
    const view = render(renderDialog(vaultAId, queryClient, onOpenChange))

    expect(view.queryByText('OAuth')).toBeNull()
    const submit = view.getByText('managed.credentials.groups.members.add').closest('button')!
    expect(submit.disabled).toBe(true)

    fireEvent.input(view.getByPlaceholderText('https://mcp.example.com'), {
      target: { value: 'https://mcp-a.example.com' },
    })
    fireEvent.input(
      view.getByPlaceholderText('managed.credentials.groups.members.tokenPlaceholder'),
      {
        target: { value: ' bearer-token ' },
      },
    )
    await act(async () => {
      fireEvent.click(submit)
    })

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false))
    expect(wirePayload).toEqual({
      name: 'https://mcp-a.example.com',
      mcp_server_url: 'https://mcp-a.example.com',
      auth_scheme: 'static_bearer',
      data: { token_value: 'bearer-token' },
    })
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ['credential-group-members', vaultAId],
    })
  })

  it('submits a canonical API-key header credential and clears secret mutation state', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const view = render(renderDialog(vaultAId, queryClient))

    fireEvent.change(view.getByLabelText('managed.credentials.groups.members.authScheme'), {
      target: { value: 'header_api_key' },
    })
    fireEvent.input(view.getByPlaceholderText('https://mcp.example.com'), {
      target: { value: ' https://mcp.example.com/api ' },
    })
    fireEvent.input(
      view.getByPlaceholderText('managed.credentials.groups.members.headerNamePlaceholder'),
      { target: { value: ' X-Corp-Key ' } },
    )
    fireEvent.input(
      view.getByPlaceholderText('managed.credentials.groups.members.tokenPlaceholder'),
      {
        target: { value: ' api-secret ' },
      },
    )

    await act(async () => {
      fireEvent.click(view.getByText('managed.credentials.groups.members.add'))
    })

    await waitFor(() => expect(managedPostMock).toHaveBeenCalledOnce())
    expect(managedPostMock.mock.calls[0][1]).toEqual({
      name: 'https://mcp.example.com/api',
      mcp_server_url: 'https://mcp.example.com/api',
      auth_scheme: 'header_api_key',
      data: { token_value: 'api-secret', header_name: 'X-Corp-Key' },
    })
    await waitFor(() => {
      expect(
        JSON.stringify(
          queryClient
            .getMutationCache()
            .getAll()
            .map((entry) => entry.state.variables),
        ),
      ).not.toContain('api-secret')
    })
  })

  it('submits custom-header prefix only for the custom-header scheme', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const view = render(renderDialog(vaultAId, queryClient))

    fireEvent.change(view.getByLabelText('managed.credentials.groups.members.authScheme'), {
      target: { value: 'custom_header' },
    })
    fireEvent.input(view.getByPlaceholderText('https://mcp.example.com'), {
      target: { value: 'https://mcp.example.com/custom' },
    })
    fireEvent.input(
      view.getByPlaceholderText('managed.credentials.groups.members.headerNamePlaceholder'),
      { target: { value: 'X-Service-Authorization' } },
    )
    fireEvent.input(
      view.getByPlaceholderText('managed.credentials.groups.members.valuePrefixPlaceholder'),
      { target: { value: 'Token ' } },
    )
    fireEvent.input(
      view.getByPlaceholderText('managed.credentials.groups.members.tokenPlaceholder'),
      {
        target: { value: 'custom-secret' },
      },
    )

    await act(async () => {
      fireEvent.click(view.getByText('managed.credentials.groups.members.add'))
    })

    await waitFor(() => expect(managedPostMock).toHaveBeenCalledOnce())
    expect(managedPostMock.mock.calls[0][1]).toEqual({
      name: 'https://mcp.example.com/custom',
      mcp_server_url: 'https://mcp.example.com/custom',
      auth_scheme: 'custom_header',
      data: {
        token_value: 'custom-secret',
        header_name: 'X-Service-Authorization',
        value_prefix: 'Token ',
      },
    })
  })
})
