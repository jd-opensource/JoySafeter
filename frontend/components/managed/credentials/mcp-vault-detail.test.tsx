import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

// Real Next useRouter() returns a STABLE reference; a fresh object per render
// would re-fire router-dependent effects every render (infinite loop / OOM).
const routerMock = { push: vi.fn(), replace: vi.fn() }
// useManagedRequestScope MUST also return a STABLE object: it is a dependency of a
// useEffect that calls setState, so a fresh object per render = infinite loop / OOM.
const scopeMock = { orgId: 'o', projectId: 'p', key: 'o:p' }

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({ t: (k: string) => k, i18n: { language: 'en' } }),
}))
vi.mock('next/navigation', () => ({ useRouter: () => routerMock }))
vi.mock('@/lib/api-client', () => ({
  managedGet: vi.fn(),
  managedPost: vi.fn(),
  managedDelete: vi.fn(),
}))
vi.mock('@/lib/managed/request-scope', () => ({
  useManagedRequestScope: () => scopeMock,
  managedRequestOptions: () => ({}),
  hasManagedRequestScope: () => true,
  managedScopeKey: () => 'o:p',
}))
vi.mock('@/hooks/managed/use-current-project-read-only', () => ({
  useCurrentProjectReadOnly: () => false,
  currentProjectAllowsWrite: () => true,
}))
vi.mock('@/stores/managed/project-store', () => ({
  useProjectStore: { getState: () => ({ currentOrgId: 'o', currentProjectId: 'p' }) },
}))
vi.mock('@/components/managed/shared', async () => {
  const actual = await vi.importActual<typeof import('@/components/managed/shared')>(
    '@/components/managed/shared',
  )
  return {
    ...actual,
    DataTable: ({
      data,
      actionMenu,
    }: {
      data: Array<{ id: string }>
      actionMenu?: (row: { id: string }) => Array<{ label: string }>
    }) => (
      <div>
        {data.map((row) => (
          <div key={row.id} data-testid={`table-row:${row.id}`}>
            {(actionMenu?.(row) ?? []).map((item) => (
              <span key={`${row.id}:${item.label}`}>{item.label}</span>
            ))}
          </div>
        ))}
      </div>
    ),
  }
})
vi.mock('@/app/managed/vaults/components/create-credential-dialog', () => ({
  CreateCredentialDialog: ({ open }: { open: boolean }) =>
    open ? <div data-testid="create-credential-dialog" /> : null,
}))

import { managedGet } from '@/lib/api-client'

import { McpVaultDetail } from './mcp-vault-detail'

const managedGetMock = managedGet as unknown as ReturnType<typeof vi.fn>
const GROUP = 'credgrp_018f6f42-0a51-7cc4-98c8-4f6f0ca5f040'
function Wrap({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

describe('McpVaultDetail', () => {
  it('fetches the group and its members', async () => {
    managedGetMock.mockImplementation(async (url: string) =>
      (url as string).includes('/members')
        ? { data: [], has_more: false }
        : {
            id: GROUP,
            name: 'v',
            description: null,
            archived_at: null,
            created_at: '',
            updated_at: '',
          },
    )
    render(
      <Wrap>
        <McpVaultDetail credentialGroupId={GROUP as never} />
      </Wrap>,
    )
    await waitFor(() => {
      expect(managedGetMock.mock.calls.some(([u]) => (u as string).includes('/members'))).toBe(true)
      expect(managedGetMock.mock.calls.some(([u]) => (u as string).endsWith(GROUP))).toBe(true)
    })
  })

  it('opens the add-credential dialog after an auto-open vault finishes loading', async () => {
    managedGetMock.mockImplementation(async (url: string) =>
      (url as string).includes('/members')
        ? { data: [], has_more: false }
        : {
            id: GROUP,
            name: 'v',
            description: null,
            archived_at: null,
            created_at: '',
            updated_at: '',
          },
    )

    render(
      <Wrap>
        <McpVaultDetail credentialGroupId={GROUP as never} autoOpenAddCredential />
      </Wrap>,
    )

    expect(await screen.findByTestId('create-credential-dialog')).toBeInTheDocument()
  })

  it('does not expose member lifecycle actions for an archived vault', async () => {
    managedGetMock.mockImplementation(async (url: string) =>
      (url as string).includes('/members')
        ? {
            data: [
              {
                id: 'cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f041',
                group_id: GROUP,
                name: 'member',
                mcp_server_url: 'https://mcp.example.com',
                data: { token_value: '********' },
                archived_at: null,
                created_at: '2026-08-13T00:00:00Z',
                updated_at: '2026-08-13T00:00:00Z',
              },
            ],
            has_more: false,
          }
        : {
            id: GROUP,
            name: 'v',
            description: null,
            archived_at: '2026-08-14T00:00:00Z',
            created_at: '2026-08-13T00:00:00Z',
            updated_at: '2026-08-14T00:00:00Z',
          },
    )

    render(
      <Wrap>
        <McpVaultDetail credentialGroupId={GROUP as never} />
      </Wrap>,
    )

    await screen.findByTestId('table-row:cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f041')
    expect(screen.queryByText('managed.vaults.credArchiveTitle')).toBeNull()
  })
})
