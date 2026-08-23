import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const replaceMock = vi.fn()
const pushMock = vi.fn()
const routerMock = { replace: replaceMock, push: pushMock }
vi.mock('@/lib/i18n', () => ({ useTranslation: () => ({ t: (k: string) => k }) }))
vi.mock('next/navigation', () => ({ useRouter: () => routerMock }))
vi.mock('@/lib/api-client', () => ({ managedGet: vi.fn() }))
vi.mock('@/lib/managed/request-scope', () => ({
  useManagedRequestScope: () => ({ orgId: 'o', projectId: 'p', key: 'o:p' }),
  managedRequestOptions: () => ({}),
  hasManagedRequestScope: () => true,
}))
vi.mock('./model-connection-detail', () => ({
  ModelConnectionDetail: () => <div>model-detail</div>,
}))
vi.mock('./service-credential-detail', () => ({
  ServiceCredentialDetail: () => <div>service-detail</div>,
}))

import { managedGet } from '@/lib/api-client'

import { CredentialDetail } from './credential-detail'

const managedGetMock = managedGet as unknown as ReturnType<typeof vi.fn>
const ID = 'cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f001'
const GROUP = 'credgrp_018f6f42-0a51-7cc4-98c8-4f6f0ca5f040'

function base(overrides: Record<string, unknown>) {
  return {
    id: ID,
    name: 'x',
    provider: null,
    protocol: null,
    model: null,
    compatible_engine_ids: [],
    is_default: false,
    mcp_server_url: null,
    group_id: null,
    archived_at: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    data: {},
    ...overrides,
  }
}
function Wrap({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

describe('CredentialDetail dispatch', () => {
  beforeEach(() => {
    managedGetMock.mockReset()
    replaceMock.mockClear()
    pushMock.mockClear()
  })

  it('renders model detail for kind=model without fetching the catalog', async () => {
    managedGetMock.mockResolvedValue(
      base({ kind: 'model', provider: 'anthropic', protocol: 'anthropic_messages' }),
    )
    const { getByText } = render(
      <Wrap>
        <CredentialDetail credentialId={ID as never} />
      </Wrap>,
    )
    await waitFor(() => expect(getByText('model-detail')).toBeTruthy())
    expect(managedGetMock.mock.calls.some(([u]) => (u as string).startsWith('/llm/catalog'))).toBe(
      false,
    )
  })

  it('renders service detail for kind=service', async () => {
    managedGetMock.mockResolvedValue(base({ kind: 'service' }))
    const { getByText } = render(
      <Wrap>
        <CredentialDetail credentialId={ID as never} />
      </Wrap>,
    )
    await waitFor(() => expect(getByText('service-detail')).toBeTruthy())
  })

  it('redirects an mcp credential WITH group_id to the vault detail route', async () => {
    managedGetMock.mockResolvedValue(
      base({ kind: 'mcp', group_id: GROUP, mcp_server_url: 'https://x' }),
    )
    render(
      <Wrap>
        <CredentialDetail credentialId={ID as never} />
      </Wrap>,
    )
    await waitFor(() =>
      expect(replaceMock).toHaveBeenCalledWith(`/managed/credentials/mcp/${GROUP}`),
    )
  })

  it('shows an explicit error for an ORPHAN mcp credential (no group_id) — never blank', async () => {
    managedGetMock.mockResolvedValue(base({ kind: 'mcp', group_id: null }))
    const { getByText } = render(
      <Wrap>
        <CredentialDetail credentialId={ID as never} />
      </Wrap>,
    )
    await waitFor(() => expect(getByText('managed.credentials.orphanCredential')).toBeTruthy())
    expect(replaceMock).not.toHaveBeenCalled()
  })
})
