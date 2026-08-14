import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

// Real Next useRouter() returns a STABLE reference; a fresh object per render
// would re-fire router-dependent effects every render (infinite loop / OOM).
const routerMock = { push: vi.fn(), replace: vi.fn() }
// useManagedRequestScope MUST also return a STABLE object: it is a dependency of a
// useEffect that calls setState, so a fresh object per render = infinite loop / OOM.
const scopeMock = { orgId: 'o', projectId: 'p', key: 'o:p' }

vi.mock('@/lib/i18n', () => ({ useTranslation: () => ({ t: (k: string) => k }) }))
vi.mock('next/navigation', () => ({ useRouter: () => routerMock }))
vi.mock('@/lib/api-client', () => ({ managedGet: vi.fn(), managedPost: vi.fn(), managedDelete: vi.fn() }))
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
vi.mock('@/stores/managed/project-store', () => ({ useProjectStore: { getState: () => ({ currentOrgId: 'o', currentProjectId: 'p' }) } }))
vi.mock('@/app/managed/vaults/components/create-credential-dialog', () => ({ CreateCredentialDialog: () => null }))

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
        : { id: GROUP, name: 'v', description: null, archived_at: null, created_at: '', updated_at: '' },
    )
    render(<Wrap><McpVaultDetail credentialGroupId={GROUP as never} /></Wrap>)
    await waitFor(() => {
      expect(managedGetMock.mock.calls.some(([u]) => (u as string).includes('/members'))).toBe(true)
      expect(managedGetMock.mock.calls.some(([u]) => (u as string).endsWith(GROUP))).toBe(true)
    })
  })
})
